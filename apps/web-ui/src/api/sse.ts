// SSE transport for the realtime event stream (Wave 3).
//
// EventSource cannot send Authorization headers, and tokens never travel in
// URLs — so the stream is consumed via fetch + ReadableStream with the Wave 1
// bearer token. Reconnect policy (bounded exponential backoff + jitter) lives
// in the office store; this module is transport-only and fully testable.

import { getApiToken } from "./client";
import type { ControlFrame, EventEnvelope } from "../types";

export interface SseHandlers {
  onEnvelope: (envelope: EventEnvelope) => void;
  onControl: (frame: ControlFrame) => void;
}

export interface StreamHandle {
  /** Resolves when the stream ends (server close, abort, or network error). */
  done: Promise<void>;
  abort: () => void;
}

/** Incremental SSE frame parser over arbitrary text chunks. */
export class SseParser {
  private buffer = "";
  private event: string | null = null;
  private data: string[] = [];

  /** Feed one text chunk; returns the complete frames parsed from it. */
  push(chunk: string): { event: string | null; data: string }[] {
    this.buffer = (this.buffer + chunk).replace(/\r\n/g, "\n");
    if (this.buffer.length > 262_144) throw new Error("SSE frame exceeds client limit");
    const frames: { event: string | null; data: string }[] = [];
    let boundary = this.buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const raw = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      const frame = this.consume(raw);
      if (frame) frames.push(frame);
      boundary = this.buffer.indexOf("\n\n");
    }
    return frames;
  }

  private consume(raw: string): { event: string | null; data: string } | null {
    for (const line of raw.split("\n")) {
      if (line.startsWith(":")) continue; // heartbeat comment
      if (line.startsWith("event:")) this.event = line.slice(6).trim();
      else if (line.startsWith("data:")) this.data.push(line.slice(5).trim());
      // `id:` is the server cursor; the store tracks it from the envelope itself.
    }
    if (this.data.length === 0) return null;
    const data = this.data.join("\n");
    const event = this.event;
    this.event = null;
    this.data = [];
    return { event, data };
  }
}

function parseEnvelope(data: string): EventEnvelope | null {
  try {
    const body = JSON.parse(data) as EventEnvelope;
    if (!body || body.schema_version !== 1 ||
        typeof body.event_id !== "string" || typeof body.event_type !== "string" ||
        typeof body.project_id !== "string" || typeof body.timestamp !== "string" ||
        !Number.isFinite(Date.parse(body.timestamp)) ||
        !Number.isSafeInteger(body.sequence) || (body.sequence ?? 0) < 1 ||
        !body.payload || typeof body.payload !== "object" || Array.isArray(body.payload)) {
      return null;
    }
    return body;
  } catch {
    return null; // malformed frame — never crash the stream
  }
}

function parseControl(data: string): ControlFrame | null {
  try {
    const body = JSON.parse(data) as ControlFrame;
    if (!body || typeof body.kind !== "string") return null;
    return body;
  } catch {
    return null;
  }
}

/**
 * Open one SSE request to `/api/events/stream`. Resolves when the stream ends;
 * the caller decides whether to reconnect (with its own backoff).
 */
export function streamEvents(
  projectId: string,
  since: number | null,
  handlers: SseHandlers,
  signal: AbortSignal,
): StreamHandle {
  const params = new URLSearchParams({ project_id: projectId });
  if (since !== null) params.set("since", String(since));
  const token = getApiToken();
  const headers: Record<string, string> = { Accept: "text/event-stream" };
  if (token) headers.Authorization = `Bearer ${token}`;

  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal.aborted) controller.abort();
  else signal.addEventListener("abort", () => controller.abort(), { once: true });

  const done = (async () => {
    const response = await fetch(`/api/events/stream?${params.toString()}`, {
      headers,
      signal: controller.signal,
      cache: "no-store",
    });
    if (!response.ok || !response.body) {
      throw new Error(`stream failed: HTTP ${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const parser = new SseParser();
    for (;;) {
      const { value, done: finished } = await reader.read();
      if (finished) break;
      for (const frame of parser.push(decoder.decode(value, { stream: true }))) {
        if (frame.event === "harness.control") {
          const control = parseControl(frame.data);
          if (control) handlers.onControl(control);
        } else {
          const envelope = parseEnvelope(frame.data);
          if (!envelope || envelope.project_id !== projectId) {
            handlers.onControl({ kind: "RESYNC_REQUIRED", detail: "Invalid event schema or scope" });
            controller.abort();
            return;
          }
          handlers.onEnvelope(envelope);
        }
      }
    }
  })();

  return { done, abort };
}

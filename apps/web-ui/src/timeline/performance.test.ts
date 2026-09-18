// Timeline scale measurements (Wave 9 §20): seeded synthetic histories at
// 1k/10k/100k events. Measures normalize, filter, search, fold, and merge —
// node-side derivation only (DOM cost is bounded separately by chunked
// rendering). No model calls.
import { describe, expect, it } from "vitest";

import type { EventEntry } from "../types";
import {
  foldReplay,
  mergeHistoryPages,
  normalizeEvent,
  rosterMaps,
  searchTimeline,
} from "./model";

function mulberry(seed: number): () => number {
  let s = seed;
  return () => {
    s |= 0;
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const TYPES = [
  "TASK_CREATED",
  "TASK_EXECUTION_STARTED",
  "AGENT_CREATED",
  "AGENT_STATUS_CHANGED",
  "TOOL_RUN_COMPLETED",
  "TASK_COMPLETED",
  "TASK_FAILED",
  "RECOVERY_SELECTED",
  "GIT_COMMIT",
  "HITL_REQUESTED",
];

function generate(count: number, seed: number): EventEntry[] {
  const rand = mulberry(seed);
  const base = Date.parse("2026-09-01T00:00:00.000Z");
  return Array.from({ length: count }, (_, i) => {
    const type = TYPES[Math.floor(rand() * TYPES.length)];
    const taskId = rand() < 0.7 ? `task-${Math.floor(rand() * 100)}` : null;
    const agentId = rand() < 0.5 ? `agent-${Math.floor(rand() * 50)}` : null;
    return {
      id: `synth-${i}`,
      occurred_at: new Date(base + i * 1000).toISOString(),
      event_type: type,
      source: "synth",
      project_id: "p",
      task_id: taskId,
      agent_id: agentId,
      payload:
        type === "TOOL_RUN_COMPLETED"
          ? { tool: "test", exit_code: rand() < 0.8 ? 0 : 1, path: `f${i}.py`, artifact_ids: [] }
          : type === "GIT_COMMIT"
            ? { message: `commit ${i}`, paths: [`f${i}.py`] }
            : {},
      project_seq: i + 1,
    };
  });
}

describe("timeline at scale", () => {
  for (const count of [1000, 10000, 100000]) {
    it(`handles ${count} events within budget`, () => {
      const entries = generate(count, 42);
      const roster = rosterMaps([], [], []);
      const names = { agents: new Map<string, string>(), tasks: new Map<string, string>() };
      const started = Date.now();
      const normalized = entries.map((e) => normalizeEvent(e, roster));
      const searched = searchTimeline(normalized, "failed", names);
      const ascending = [...entries].sort(
        (a, b) => Date.parse(a.occurred_at) - Date.parse(b.occurred_at),
      );
      const snap = foldReplay(ascending, ascending.length, roster);
      const merged = mergeHistoryPages(entries.slice(0, count / 2), entries.slice(count / 4));
      const elapsedMs = Date.now() - started;
      if (count === 100000) {
        console.log(JSON.stringify({
          benchmark: "wave9-timeline",
          events: count,
          normalized: normalized.length,
          searched: searched.length,
          rosterTasks: snap.tasks.length,
          merged: merged.length,
          elapsedMs,
        }));
      }
      expect(normalized).toHaveLength(count);
      expect(merged.length).toBeLessThanOrEqual(count);
      expect(snap.applied).toBe(count);
      expect(elapsedMs).toBeLessThan(count === 100000 ? 30000 : 5000);
    });
  }
});

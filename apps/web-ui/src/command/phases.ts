// Entry lifecycle phases (UI2, pure): DISCUSSING / PLANNING / AWAITING
// APPROVAL / EXECUTING / VERIFYING / COMPLETED / BLOCKED / FAILED. Every
// phase derives from existing entry + task state — no invented states.

import type { CenterEntry } from "./types";
import type { TaskInfo } from "../types";

export type EntryPhaseId =
  | "discussing"
  | "planning"
  | "awaiting"
  | "executing"
  | "verifying"
  | "completed"
  | "blocked"
  | "failed";

export const PHASE_META: Record<EntryPhaseId, { label: string; tone: string; glyph: string }> = {
  discussing: { label: "Discussing", tone: "muted", glyph: "•" },
  planning: { label: "Planning", tone: "info", glyph: "•" },
  awaiting: { label: "Awaiting approval", tone: "warn", glyph: "!" },
  executing: { label: "Executing", tone: "ok", glyph: "▶" },
  verifying: { label: "Verifying", tone: "warn", glyph: "!" },
  completed: { label: "Completed", tone: "ok", glyph: "✓" },
  blocked: { label: "Blocked", tone: "warn", glyph: "!" },
  failed: { label: "Failed", tone: "down", glyph: "✗" },
};

function linkedTasks(entry: CenterEntry, tasks: TaskInfo[]): TaskInfo[] {
  const ids = new Set([
    ...entry.dispatches.map((d) => d.taskId).filter((id): id is string => !!id),
    ...(entry.intent.scope.taskId ? [entry.intent.scope.taskId] : []),
  ]);
  if (ids.size === 0) return [];
  return tasks.filter((t) => ids.has(t.id));
}

/** Derive the user-facing phase. Order matters: entry truth first, then
 * linked-task truth, then preview intent. */
export function entryPhase(entry: CenterEntry, tasks: TaskInfo[]): EntryPhaseId {
  if (entry.status === "error" || entry.error) return "failed";
  const linked = linkedTasks(entry, tasks);
  if (entry.status === "running" || entry.awaiting) {
    if (entry.awaiting) return "awaiting";
    if (linked.some((t) => t.status === "failed")) return "blocked";
    if (linked.some((t) => t.status === "blocked")) return "blocked";
    if (linked.some((t) => t.status === "verifying")) return "verifying";
    return "executing";
  }
  if (entry.status === "done") {
    if (linked.some((t) => t.status === "failed" || t.status === "blocked")) return "blocked";
    const verdict = entry.dispatches.find((d) => d.reviewVerdict)?.reviewVerdict;
    if (verdict && !["approve", "approved"].includes(verdict)) return "blocked";
    return "completed";
  }
  // preview
  if (entry.intent.intentType === "unknown" || entry.intent.intentType === "unsupported") {
    return "discussing";
  }
  return "planning";
}

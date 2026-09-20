// Canonical agent states + roster ordering/filtering (UI3, pure logic).
//
// Display-only translation of backend lifecycle states into user language
// (§7 blueprint). Unknown states render raw (muted) — never invented.
// Sorting: needs-attention first, then active, then the rest by recency.

import type { AgentInfo, EventEntry, HitlRequestInfo, TaskInfo } from "../types";
import { currentTaskForAgent, lastAgentEvent, tasksForAgent } from "./selectors";

export interface AgentStatus {
  label: string;
  tone: "ok" | "warn" | "down" | "muted" | "info";
  glyph: string;
}

const STATES: Record<string, AgentStatus> = {
  created: { label: "Starting", tone: "muted", glyph: "○" },
  planning: { label: "Planning", tone: "muted", glyph: "○" },
  running: { label: "Working", tone: "ok", glyph: "▶" },
  waiting: { label: "Waiting", tone: "warn", glyph: "!" },
  blocked: { label: "Blocked", tone: "warn", glyph: "!" },
  pause_requested: { label: "Pausing", tone: "warn", glyph: "⏸" },
  draining: { label: "Draining", tone: "warn", glyph: "⏸" },
  paused: { label: "Paused", tone: "warn", glyph: "⏸" },
  resuming: { label: "Resuming", tone: "warn", glyph: "▶" },
  verifying: { label: "Verifying", tone: "warn", glyph: "!" },
  recovering: { label: "Recovering", tone: "warn", glyph: "!" },
  completed: { label: "Completed", tone: "ok", glyph: "✓" },
  failed: { label: "Failed", tone: "down", glyph: "✗" },
  cancelled: { label: "Cancelled", tone: "muted", glyph: "•" },
};

/** Canonical display status; unknown backend states pass through muted. */
export function agentStatus(state: string): AgentStatus {
  return STATES[state] ?? { label: state.replaceAll("_", " "), tone: "muted", glyph: "•" };
}

export type AttentionKind = "failed" | "approval" | "blocked" | "waiting" | null;

/** Why this agent needs the supervisor, if anything. Failed owned tasks
 * outrank approvals; approvals outrank blocks; blocks outrank plain waits. */
export function agentAttention(
  agentId: string,
  tasks: TaskInfo[],
  hitl: HitlRequestInfo[],
): { kind: Exclude<AttentionKind, null>; detail: string } | null {
  const owned = tasksForAgent(tasks, agentId);
  const ownedIds = new Set(owned.map((t) => t.id));
  const failed = owned.filter((t) => t.status === "failed");
  if (failed.length > 0) {
    return { kind: "failed", detail: `${failed.length} failed task${failed.length === 1 ? "" : "s"}` };
  }
  const approvals = hitl.filter((h) => h.status === "pending" && h.task_id && ownedIds.has(h.task_id));
  if (approvals.length > 0) {
    return { kind: "approval", detail: `${approvals.length} approval${approvals.length === 1 ? "" : "s"} needed` };
  }
  const blocked = owned.filter((t) => t.status === "blocked");
  if (blocked.length > 0) {
    return { kind: "blocked", detail: `${blocked.length} blocked task${blocked.length === 1 ? "" : "s"}` };
  }
  const current = currentTaskForAgent(tasks, agentId);
  if (current && (current.status === "waiting" || current.status === "blocked")) {
    return { kind: "waiting", detail: `waiting on ${current.title}` };
  }
  return null;
}

const ATTENTION_RANK: Record<Exclude<AttentionKind, null>, number> = {
  failed: 0,
  approval: 1,
  blocked: 2,
  waiting: 3,
};

const ACTIVE_STATES = new Set(["running", "planning", "verifying", "recovering", "resuming"]);

/** Roster order: needs-attention (ranked), then active, then the rest by
 * most recent event. Stable and cheap (no repeated sorting downstream). */
export function sortRoster(
  agents: AgentInfo[],
  tasks: TaskInfo[],
  hitl: HitlRequestInfo[],
  events: EventEntry[],
): AgentInfo[] {
  const attention = new Map(agents.map((a) => [a.id, agentAttention(a.id, tasks, hitl)]));
  const lastSeen = new Map<string, number>();
  for (const e of events) {
    if (e.agent_id && !lastSeen.has(e.agent_id)) lastSeen.set(e.agent_id, Date.parse(e.occurred_at) || 0);
  }
  return [...agents].sort((a, b) => {
    const aa = attention.get(a.id);
    const ab = attention.get(b.id);
    if ((aa === null) !== (ab === null)) return aa === null ? 1 : -1;
    if (aa && ab && ATTENTION_RANK[aa.kind] !== ATTENTION_RANK[ab.kind]) {
      return ATTENTION_RANK[aa.kind] - ATTENTION_RANK[ab.kind];
    }
    const aActive = ACTIVE_STATES.has(a.state);
    const bActive = ACTIVE_STATES.has(b.state);
    if (aActive !== bActive) return aActive ? -1 : 1;
    return (lastSeen.get(b.id) ?? 0) - (lastSeen.get(a.id) ?? 0);
  });
}

export type RosterFilter = "all" | "working" | "waiting" | "attention" | "failed" | "completed";

/** Filter predicate over recorded state only. "working" = active lifecycle
 * states; "waiting" = waiting/blocked/paused; "attention" = any flag. */
export function filterRoster(
  agents: AgentInfo[],
  tasks: TaskInfo[],
  hitl: HitlRequestInfo[],
  filter: RosterFilter,
  query: string,
): AgentInfo[] {
  const q = query.trim().toLowerCase();
  return agents.filter((agent) => {
    if (q) {
      const current = currentTaskForAgent(tasks, agent.id);
      const hay = `${agent.name} ${agent.role} ${current?.title ?? ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    switch (filter) {
      case "all": return true;
      case "working": return ACTIVE_STATES.has(agent.state);
      case "waiting": return ["waiting", "blocked", "paused", "pause_requested", "draining"].includes(agent.state);
      case "attention": return agentAttention(agent.id, tasks, hitl) !== null;
      case "failed": return agent.state === "failed" || tasksForAgent(tasks, agent.id).some((t) => t.status === "failed");
      case "completed": return agent.state === "completed" || agent.state === "cancelled";
    }
  });
}

/** One-line activity summary from the latest recorded event + task. Honest:
 * lifecycle + event vocabulary only, falls back to state when silent. */
export function activitySummary(
  agentId: string,
  tasks: TaskInfo[],
  events: EventEntry[],
): string | null {
  const last = lastAgentEvent(events, agentId);
  if (!last) {
    const current = currentTaskForAgent(tasks, agentId);
    return current ? `Assigned: ${current.title}` : null;
  }
  const when = last.occurred_at ? new Date(last.occurred_at).toLocaleTimeString() : null;
  const what = last.event_type.replaceAll("_", " ").toLowerCase();
  const detail = typeof last.payload?.detail === "string" && last.payload.detail.length > 0
    ? `: ${last.payload.detail.slice(0, 80)}`
    : "";
  return `${what}${detail}${when ? ` · ${when}` : ""}`;
}

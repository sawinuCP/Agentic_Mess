// Execution Timeline model (Wave 9): normalization, sanitization,
// correlation, search, pagination merge, and the replay fold.
//
// Pure functions over EventEntry + current roster snapshots. No React, no
// fetch — unit-testable in node Vitest. Every rule mirrors
// docs/execution-timeline-architecture.md. Anything not recorded is labeled,
// never invented.

import type { AgentInfo, EventEntry, TaskInfo } from "../types";

export type TimelineCategory =
  | "execution"
  | "tasks"
  | "agents"
  | "tools"
  | "communication"
  | "recovery"
  | "validation"
  | "artifacts"
  | "hitl"
  | "requirements"
  | "system";

export type TimelineTone = "ok" | "warn" | "down" | "muted";

export interface TimelineActor {
  type: "agent" | "task" | "system";
  id: string | null;
  label: string;
}

export interface TimelineResource {
  type: "file" | "worktree" | "commit" | "test" | "tool" | "artifact" | "requirement" | "agent" | "task";
  id: string;
  label?: string;
}

export interface TimelineEvent {
  id: string;
  type: string;
  timestamp: string;
  seq: number | null;
  category: TimelineCategory;
  executionId: string | null;
  requirementId: string | null;
  taskId: string | null;
  agentId: string | null;
  correlationId: string | null;
  actor: TimelineActor;
  summary: string;
  status: string;
  tone: TimelineTone;
  resources: TimelineResource[];
  evidenceRefs: string[];
  raw: unknown;
}

export interface RosterMaps {
  agentName: (id: string | null) => string;
  agentRole: (id: string | null) => string | null;
  taskTitle: (id: string | null) => string;
  requirementTitle: (id: string | null) => string | null;
}

export function rosterMaps(
  agents: AgentInfo[],
  tasks: TaskInfo[],
  requirements: { id: string; title: string }[],
): RosterMaps {
  const agentById = new Map(agents.map((a) => [a.id, a]));
  const taskById = new Map(tasks.map((t) => [t.id, t]));
  const reqById = new Map(requirements.map((r) => [r.id, r.title]));
  return {
    agentName: (id) => (id && agentById.get(id)?.name) ?? (id ? id.slice(0, 8) : "?"),
    agentRole: (id) => (id && agentById.get(id)?.role) ?? null,
    taskTitle: (id) => (id && taskById.get(id)?.title) ?? (id ? id.slice(0, 8) : "?"),
    requirementTitle: (id) => (id && reqById.get(id)) ?? null,
  };
}

const CATEGORY_PREFIXES: { category: TimelineCategory; prefixes: string[] }[] = [
  { category: "recovery", prefixes: ["RECOVERY_", "RETRY_", "MODEL_SWITCHED", "MODEL_BUDGET", "CONTEXT_COMPACTED", "DEBUGGER_SPAWNED", "AGENT_REPLACED", "DEPENDENCY_"] },
  { category: "hitl", prefixes: ["HITL_"] },
  { category: "validation", prefixes: ["REVIEW_", "DECISION_", "SECURITY_", "SCOPE_"] },
  { category: "artifacts", prefixes: ["TOOL_", "MCP_", "BROWSER_", "GIT_"] },
  { category: "agents", prefixes: ["AGENT_"] },
  { category: "requirements", prefixes: ["REQUIREMENT_", "PLAN_"] },
  { category: "system", prefixes: ["LEASE_", "PORT_", "WORKTREE_", "INTEGRATION_", "PROJECT_"] },
];

export function eventCategory(eventType: string): TimelineCategory {
  if (eventType === "TASK_EXECUTION_STARTED" || eventType === "TASK_SCHEDULED") return "execution";
  for (const { category, prefixes } of CATEGORY_PREFIXES) {
    if (prefixes.some((p) => eventType.startsWith(p))) return category;
  }
  if (eventType.startsWith("TASK_")) return "tasks";
  return "system";
}

export const CATEGORIES: { category: TimelineCategory; label: string }[] = [
  { category: "execution", label: "Execution" },
  { category: "tasks", label: "Tasks" },
  { category: "agents", label: "Agents" },
  { category: "tools", label: "Tools" },
  { category: "communication", label: "Communication" },
  { category: "recovery", label: "Recovery" },
  { category: "validation", label: "Validation" },
  { category: "artifacts", label: "Artifacts" },
  { category: "hitl", label: "Approvals" },
  { category: "requirements", label: "Requirements" },
  { category: "system", label: "System" },
];

const TEST_TOOLS = new Set(["test", "lint", "build"]);

function payloadText(payload: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "string" && value) return value;
  }
  return null;
}

function toolOutcome(payload: Record<string, unknown>): { status: string; tone: TimelineTone } {  const exit = payload.exit_code;
  if (exit === 0) return { status: "passed", tone: "ok" };
  if (exit === null || exit === undefined) return { status: "unknown", tone: "muted" };
  return { status: "failed", tone: "down" };
}

/** Rich one-line summary per event kind; falls back to the raw type. */
export function summarizeEvent(entry: EventEntry, roster: RosterMaps): string {
  const p = entry.payload;
  const t = entry.event_type;
  switch (t) {
    case "TASK_CREATED":
      return `Task created: ${payloadText(p, ["title"]) ?? entry.task_id?.slice(0, 8) ?? "?"}`;
    case "TASK_EXECUTION_STARTED":
      return `Execution started${entry.task_id ? `: ${roster.taskTitle(entry.task_id)}` : ""}`;
    case "TASK_SCHEDULED":
      return `Task scheduled${entry.task_id ? `: ${roster.taskTitle(entry.task_id)}` : ""}`;
    case "TASK_COMPLETED":
      return `Task completed${entry.task_id ? `: ${roster.taskTitle(entry.task_id)}` : ""}`;
    case "TASK_FAILED":
    case "TASK_TERMINALLY_FAILED": {
      const attempts = Array.isArray(p.attempts) ? p.attempts.length : 0;
      return `Task failed${entry.task_id ? `: ${roster.taskTitle(entry.task_id)}` : ""}${attempts > 0 ? ` after ${attempts} attempt${attempts === 1 ? "" : "s"}` : ""}`;
    }
    case "TASK_CANCELLED":
      return `Task cancelled${entry.task_id ? `: ${roster.taskTitle(entry.task_id)}` : ""}`;
    case "TASK_REPLANNED":
      return "Task replanned";
    case "AGENT_CREATED":
      return `Agent created: ${payloadText(p, ["role"]) ?? roster.agentName(entry.agent_id)}`;
    case "AGENT_STATUS_CHANGED": {
      const from = payloadText(p, ["from"]) ?? "?";
      const to = payloadText(p, ["to"]) ?? "?";
      return `${roster.agentName(entry.agent_id)}: ${from} → ${to}`;
    }
    case "AGENT_REPLACED":
      return `Agent replaced${entry.task_id ? ` on ${roster.taskTitle(entry.task_id)}` : ""}`;
    case "RECOVERY_SELECTED":
      return `Recovery decision: ${payloadText(p, ["action"]) ?? "recorded"}${payloadText(p, ["failure_class"]) ? ` (${payloadText(p, ["failure_class"])})` : ""}`;
    case "RETRY_STARTED": {
      const n = typeof p.attempt_number === "number" ? ` #${p.attempt_number}` : "";
      return `Retry started${n}${typeof p.backoff_seconds === "number" ? ` (backoff ${p.backoff_seconds}s)` : ""}`;
    }
    case "MODEL_SWITCHED":
      return `Model switched${payloadText(p, ["model"]) ? `: ${payloadText(p, ["model"])}` : ""}`;
    case "CONTEXT_COMPACTED":
      return "Context compacted";
    case "DEBUGGER_SPAWNED":
      return "Debugger spawned";
    case "DEPENDENCY_WAIT_STARTED":
      return `Waiting on dependency${typeof p.max_wait_seconds === "number" ? ` (up to ${p.max_wait_seconds}s)` : ""}`;
    case "DEPENDENCY_RESUMED":
      return "Dependency resolved";
    case "TOOL_RUN_COMPLETED": {
      const tool = typeof p.tool === "string" ? p.tool : "tool";
      const path = typeof p.path === "string" ? ` ${p.path.split("/").pop()}` : "";
      const ms = typeof p.duration_ms === "number" ? `, ${p.duration_ms}ms` : "";
      const exit = p.exit_code;
      return `${tool}${path} — exit ${exit ?? "?"}${ms}`;
    }
    case "GIT_COMMIT": {
      const message = typeof p.message === "string" ? p.message.split("\n")[0] : "commit";
      const paths = Array.isArray(p.paths) ? p.paths.length : 0;
      return `${message}${paths > 0 ? ` (${paths} file${paths === 1 ? "" : "s"})` : ""}`;
    }
    case "HITL_REQUESTED":
      return `Approval requested (${payloadText(p, ["kind"]) ?? "review"})`;
    case "HITL_RESPONDED":
      return `Approval ${p.approved === true ? "approved" : p.approved === false ? "rejected" : "responded"}`;
    case "HITL_RECOVERY_REQUESTED":
      return `Recovery approval requested: ${payloadText(p, ["action"]) ?? ""}`;
    case "REQUIREMENT_CREATED":
      return `Requirement created: ${payloadText(p, ["title"]) ?? "?"}`;
    case "SECURITY_SCAN_COMPLETED":
      return "Security scan completed";
    default: {
      const detail = payloadText(p, ["detail", "title", "action", "status", "verdict"]);
      return detail ? `${t} — ${detail}` : t;
    }
  }
}

function toneFor(entry: EventEntry): { status: string; tone: TimelineTone } {
  const t = entry.event_type;
  if (
    t.includes("FAIL") || t === "TASK_TERMINALLY_FAILED" ||
    entry.payload.outcome === "failed" || entry.payload.outcome === "timeout"
  ) {
    return { status: "failed", tone: "down" };
  }
  if (t === "TOOL_RUN_COMPLETED") return toolOutcome(entry.payload);
  if (
    t.endsWith("_COMPLETED") || t === "TASK_COMPLETED" || t === "DEPENDENCY_RESUMED" ||
    entry.payload.approved === true || entry.payload.status === "passed"
  ) {
    return { status: "completed", tone: "ok" };
  }
  if (
    t.includes("WAIT") || t.includes("BLOCKED") || t === "TASK_SCHEDULED" ||
    t === "HITL_REQUESTED" || t === "HITL_RECOVERY_REQUESTED" ||
    entry.payload.status === "pending"
  ) {
    return { status: "waiting", tone: "warn" };
  }
  if (t.includes("PAUSE") || (typeof entry.payload.to === "string" && entry.payload.to === "paused")) {
    return { status: "paused", tone: "warn" };
  }
  if (t.includes("RECOVER") || t.includes("RETRY") || t === "MODEL_SWITCHED" || t === "DEBUGGER_SPAWNED") {
    return { status: "recovering", tone: "warn" };
  }
  return { status: "recorded", tone: "muted" };
}

function asStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

/** Normalize one durable event for presentation. Tools category refines artifacts. */
export function normalizeEvent(entry: EventEntry, roster: RosterMaps): TimelineEvent {
  let category = eventCategory(entry.event_type);
  const tool = entry.payload.tool;
  if (entry.event_type === "TOOL_RUN_COMPLETED" && typeof tool === "string") {
    category = TEST_TOOLS.has(tool) ? "validation" : "tools";
  }
  const agentId = entry.agent_id;
  const taskId = entry.task_id;
  const actor: TimelineActor = agentId
    ? { type: "agent", id: agentId, label: `${roster.agentName(agentId)}${roster.agentRole(agentId) ? ` (${roster.agentRole(agentId)})` : ""}` }
    : taskId
      ? { type: "task", id: taskId, label: roster.taskTitle(taskId) }
      : { type: "system", id: null, label: entry.source ?? "system" };
  const resources: TimelineResource[] = [];
  if (taskId) resources.push({ type: "task", id: taskId, label: roster.taskTitle(taskId) });
  if (agentId) resources.push({ type: "agent", id: agentId, label: roster.agentName(agentId) });
  const path = entry.payload.path;
  if (typeof path === "string") resources.push({ type: "file", id: path, label: path.split("/").pop() });
  for (const p of asStrings(entry.payload.paths)) {
    resources.push({ type: "file", id: p, label: p.split("/").pop() });
  }
  const evidenceRefs = [
    ...asStrings(entry.payload.artifact_ids),
    ...asStrings(entry.payload.evidence_artifact_ids),
  ];
  for (const id of evidenceRefs) {
    resources.push({ type: "artifact", id, label: id.slice(0, 8) });
  }
  if (typeof entry.payload.tool === "string") {
    resources.push({ type: "tool", id: String(entry.payload.tool), label: String(entry.payload.tool) });
  }
  const { status, tone } = toneFor(entry);
  return {
    id: entry.id,
    type: entry.event_type,
    timestamp: entry.occurred_at,
    seq: typeof entry.project_seq === "number" ? entry.project_seq : null,
    category,
    executionId: entry.execution_id ?? null,
    requirementId: null, // resolved by callers through task links; never guessed here
    taskId,
    agentId,
    correlationId: entry.correlation_id ?? null,
    actor,
    summary: summarizeEvent(entry, roster),
    status,
    tone,
    resources,
    evidenceRefs: [...new Set(evidenceRefs)],
    raw: sanitizePayload(entry.payload),
  };
}

// --- sanitization ---------------------------------------------------------------

const SECRET_KEY = /(token|secret|passwd|password|api[_-]?key|authorization|bearer|session|cookie|private[_-]?key|credentials|access[_-]?key|client[_-]?secret)/i;

/** Redact secret-shaped keys, truncate long strings, cap depth/breadth. */
export function sanitizePayload(value: unknown, depth = 0): unknown {
  if (depth > 4) return "[truncated: depth]";
  if (typeof value === "string") {
    return value.length > 500 ? `${value.slice(0, 500)}…[truncated]` : value;
  }
  if (Array.isArray(value)) {
    const capped = value.slice(0, 20).map((v) => sanitizePayload(v, depth + 1));
    if (value.length > 20) capped.push(`…[${value.length - 20} more truncated]`);
    return capped;
  }
  if (value !== null && typeof value === "object") {
    const out: Record<string, unknown> = {};
    const keys = Object.keys(value).slice(0, 50);
    for (const key of keys) {
      out[key] = SECRET_KEY.test(key)
        ? "[redacted]"
        : sanitizePayload((value as Record<string, unknown>)[key], depth + 1);
    }
    if (Object.keys(value).length > 50) out["…"] = "[truncated: too many keys]";
    return out;
  }
  return value;
}

// --- correlation ------------------------------------------------------------------

export interface RelatedEvents {
  byCorrelation: TimelineEvent[];
  byTask: TimelineEvent[];
}

/**
 * Real chains only: shared non-null correlation ids, plus same-task events
 * (bounded, chronological) labeled as task-scoped — never invented links.
 */
export function relatedEvents(
  event: TimelineEvent,
  all: TimelineEvent[],
  limit = 20,
): RelatedEvents {
  const byCorrelation = event.correlationId
    ? all
        .filter((e) => e.id !== event.id && e.correlationId === event.correlationId)
        .sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp))
        .slice(0, limit)
    : [];
  const byTask = event.taskId
    ? all
        .filter((e) => e.id !== event.id && e.taskId === event.taskId)
        .sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp))
        .slice(0, limit)
    : [];
  return { byCorrelation, byTask };
}

// --- failure predicate (shared by Activity and History views) ---------------

/** True for failed/timeout outcomes and failure-typed events. */
export function isFailureEvent(eventType: string, payload: Record<string, unknown>): boolean {
  if (eventType.includes("FAIL") || eventType === "TASK_TERMINALLY_FAILED") return true;
  const outcome = payload.outcome;
  return outcome === "failed" || outcome === "timeout";
}

// --- search + pagination merge ------------------------------------------------------

const SEARCHABLE = ["summary", "type", "status"] as const;

/** Client-side search over loaded rows (labels/names/paths/ids). Server can narrow by event_type. */
export function searchTimeline(
  events: TimelineEvent[],
  query: string,
  names: { agents: Map<string, string>; tasks: Map<string, string> },
): TimelineEvent[] {
  const q = query.trim().toLowerCase();
  if (!q) return events;
  return events.filter((e) => {
    const hay = [
      ...SEARCHABLE.map((k) => String(e[k] ?? "")),
      names.agents.get(e.agentId ?? "") ?? "",
      names.tasks.get(e.taskId ?? "") ?? "",
      ...e.resources.map((r) => `${r.id} ${r.label ?? ""}`),
      e.correlationId ?? "",
    ].join(" ").toLowerCase();
    return q.split(/\s+/).every((token) => hay.includes(token));
  });
}

/** Merge a newly fetched page (newest-first) with id-dedupe, preserving order. */
export function mergeHistoryPages(existing: EventEntry[], page: EventEntry[]): EventEntry[] {
  const seen = new Set(existing.map((e) => e.id));
  const fresh = page.filter((e) => !seen.has(e.id));
  return [...existing, ...fresh];
}

// --- replay fold ----------------------------------------------------------------------

export interface ReplayRosterEntry {
  id: string;
  label: string;
  state: string;
  since: string;
  lastEvent: string;
}

export interface ReplaySnapshot {
  /** Ascending events applied (0..n). */
  applied: number;
  total: number;
  asOf: string | null;
  agents: ReplayRosterEntry[];
  tasks: ReplayRosterEntry[];
  counts: {
    agentsRunning: number;
    tasksRunning: number;
    tasksFailed: number;
    tasksBlocked: number;
    tasksCompleted: number;
  };
  recoveryMilestones: { type: string; timestamp: string; taskId: string | null }[];
  tests: { passed: number; failed: number };
  hitl: { requested: number; responded: number };
  commits: { message: string; timestamp: string; paths: string[] }[];
  requirements: { id: string; title: string }[];
}

const TASK_STATUS: Record<string, string> = {
  TASK_CREATED: "pending",
  TASK_SCHEDULED: "running",
  TASK_EXECUTION_STARTED: "running",
  TASK_COMPLETED: "completed",
  TASK_FAILED: "failed",
  TASK_TERMINALLY_FAILED: "failed",
  TASK_CANCELLED: "cancelled",
  TASK_REPLANNED: "pending",
  DEPENDENCY_WAIT_STARTED: "blocked",
  DEPENDENCY_RESUMED: "ready",
};

const RECOVERY_MILESTONES = new Set([
  "RECOVERY_SELECTED",
  "RETRY_STARTED",
  "AGENT_REPLACED",
  "MODEL_SWITCHED",
  "CONTEXT_COMPACTED",
  "DEBUGGER_SPAWNED",
  "TASK_TERMINALLY_FAILED",
]);

/**
 * Fold ascending events into the reconstructed state at step `upTo`
 * (exclusive count). O(steps) per call — measured in milliseconds at 10k.
 * Only event-recorded facts are reconstructed; attempts, payload values,
 * pre-window history, and requirement verification states are NOT
 * (documented at every surface that shows them).
 */
export function foldReplay(
  ascending: EventEntry[],
  upTo: number,
  roster: RosterMaps,
): ReplaySnapshot {
  const agents = new Map<string, ReplayRosterEntry>();
  const tasks = new Map<string, ReplayRosterEntry>();
  const requirements = new Map<string, { id: string; title: string }>();
  const recoveryMilestones: ReplaySnapshot["recoveryMilestones"] = [];
  const commits: ReplaySnapshot["commits"] = [];
  let testsPassed = 0;
  let testsFailed = 0;
  let hitlRequested = 0;
  let hitlResponded = 0;
  const steps = ascending.slice(0, Math.max(0, Math.min(upTo, ascending.length)));
  for (const e of steps) {
    const t = e.event_type;
    if (t === "TASK_CREATED") {
      const title = typeof e.payload.title === "string" ? e.payload.title : roster.taskTitle(e.task_id);
      if (e.task_id) tasks.set(e.task_id, { id: e.task_id, label: title, state: "pending", since: e.occurred_at, lastEvent: t });
    } else if (TASK_STATUS[t] && e.task_id) {
      const prev = tasks.get(e.task_id);
      tasks.set(e.task_id, {
        id: e.task_id,
        label: prev?.label ?? roster.taskTitle(e.task_id),
        state: TASK_STATUS[t],
        since: e.occurred_at,
        lastEvent: t,
      });
    }
    if (t === "AGENT_CREATED" && e.agent_id) {
      const role = typeof e.payload.role === "string" ? e.payload.role : (roster.agentRole(e.agent_id) ?? "worker");
      agents.set(e.agent_id, { id: e.agent_id, label: roster.agentName(e.agent_id), state: "created", since: e.occurred_at, lastEvent: `${t} (${role})` });
    } else if (t === "AGENT_STATUS_CHANGED" && e.agent_id) {
      const to = typeof e.payload.to === "string" ? e.payload.to : null;
      const prev = agents.get(e.agent_id);
      agents.set(e.agent_id, {
        id: e.agent_id,
        label: prev?.label ?? roster.agentName(e.agent_id),
        state: to ?? prev?.state ?? "unknown",
        since: e.occurred_at,
        lastEvent: t,
      });
    }
    if (RECOVERY_MILESTONES.has(t)) {
      recoveryMilestones.push({ type: t, timestamp: e.occurred_at, taskId: e.task_id });
    }
    if (t === "TOOL_RUN_COMPLETED" && typeof e.payload.tool === "string" && ["test", "lint", "build"].includes(e.payload.tool)) {
      if (e.payload.exit_code === 0) testsPassed += 1;
      else testsFailed += 1;
    }
    if (t === "HITL_REQUESTED" || t === "HITL_RECOVERY_REQUESTED") hitlRequested += 1;
    if (t === "HITL_RESPONDED" || t === "HITL_RECOVERY_RESPONDED") hitlResponded += 1;
    if (t === "GIT_COMMIT") {
      commits.push({
        message: typeof e.payload.message === "string" ? e.payload.message.split("\n")[0] : "commit",
        timestamp: e.occurred_at,
        paths: asStrings(e.payload.paths),
      });
      if (commits.length > 50) commits.shift();
    }
    if (t === "REQUIREMENT_CREATED") {
      const rid = typeof e.payload.requirement_id === "string" ? e.payload.requirement_id : null;
      const title = typeof e.payload.title === "string" ? e.payload.title : (rid ? roster.requirementTitle(rid) : null) ?? "?";
      if (rid) requirements.set(rid, { id: rid, title });
    }
  }
  const agentList = [...agents.values()];
  const taskList = [...tasks.values()];
  return {
    applied: steps.length,
    total: ascending.length,
    asOf: steps.length > 0 ? steps[steps.length - 1].occurred_at : null,
    agents: agentList,
    tasks: taskList,
    counts: {
      agentsRunning: agentList.filter((a) => a.state === "running").length,
      tasksRunning: taskList.filter((x) => x.state === "running").length,
      tasksFailed: taskList.filter((x) => x.state === "failed").length,
      tasksBlocked: taskList.filter((x) => x.state === "blocked").length,
      tasksCompleted: taskList.filter((x) => x.state === "completed").length,
    },
    recoveryMilestones: recoveryMilestones.slice(-20),
    tests: { passed: testsPassed, failed: testsFailed },
    hitl: { requested: hitlRequested, responded: hitlResponded },
    commits,
    requirements: [...requirements.values()],
  };
}

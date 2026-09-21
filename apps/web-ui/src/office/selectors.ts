// Agent Office derivation (Wave 7): pure projections over durable state.
//
// No React, no fetch — unit-testable in the node Vitest suite. Every rule
// here mirrors docs/agent-office-architecture.md §3. Anything the backend
// does not record is labeled as derived/last-recorded, never invented.

import type {
  CostsSummary,
  EventEntry,
  HitlRequestInfo,
  MessageInfo,
  TaskInfo,
  ToolRunResult,
} from "../types";
import { taskCommands } from "../commands/taskCommands";

export const TERMINAL_TASK = new Set(["completed", "cancelled", "failed"]);

/** Tasks that reference this agent in any attempt, most-recent attempt first. */
export function tasksForAgent(tasks: TaskInfo[], agentId: string): TaskInfo[] {
  const owned = tasks.filter((t) => t.attempts.some((a) => a.agent_id === agentId));
  const lastAttemptIndex = (t: TaskInfo): number => {
    let latest = -1;
    for (const a of t.attempts) {
      if (a.agent_id === agentId && a.attempt_number > latest) latest = a.attempt_number;
    }
    return latest;
  };
  return owned.sort((a, b) => lastAttemptIndex(b) - lastAttemptIndex(a));
}

/** The agent's live work: newest non-terminal owned task, else newest owned. */
export function currentTaskForAgent(tasks: TaskInfo[], agentId: string): TaskInfo | null {
  const owned = tasksForAgent(tasks, agentId);
  if (owned.length === 0) return null;
  return owned.find((t) => !TERMINAL_TASK.has(t.status)) ?? owned[0];
}

function taskTitle(tasks: TaskInfo[], id: string): string {
  return tasks.find((t) => t.id === id)?.title ?? id.slice(0, 8);
}

function taskStatus(tasks: TaskInfo[], id: string): string {
  return tasks.find((t) => t.id === id)?.status ?? "unknown";
}

/**
 * Why this task is waiting/blocked: unresolved dependencies with their live
 * statuses. Null when nothing is pending (caller decides tone).
 */
export function waitingReason(task: TaskInfo, allTasks: TaskInfo[]): string | null {
  const pending = task.depends_on.filter(
    (id) => taskStatus(allTasks, id) !== "completed",
  );
  if (pending.length === 0) return null;
  const parts = pending.map((id) => `${taskTitle(allTasks, id)} (${taskStatus(allTasks, id)})`);
  return `Waiting for ${parts.join(", ")}`;
}

/** Latest recorded moment this task started waiting (event-derived, if any). */
export function waitingSince(taskId: string, events: EventEntry[]): string | null {
  const started = events.find(
    (e) => e.task_id === taskId && e.event_type === "DEPENDENCY_WAIT_STARTED",
  );
  return started ? started.occurred_at : null;
}

/** Compact duration: 45s, 12m, 3h 4m. Negative/clamped to zero. */
export function formatDuration(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

/** Elapsed time since an ISO timestamp, or null when unparseable. */
export function elapsedSince(iso: string | null, nowMs = Date.now()): string | null {
  if (!iso) return null;
  const parsed = Date.parse(iso);
  if (Number.isNaN(parsed)) return null;
  return formatDuration(nowMs - parsed);
}

/** Agent-level waiting line via its current task. */
export function agentWaitingReason(
  agentId: string,
  agentState: string,
  tasks: TaskInfo[],
): string | null {
  if (agentState !== "waiting" && agentState !== "blocked") return null;
  const current = currentTaskForAgent(tasks, agentId);
  if (!current) return "Waiting — no task recorded for this agent";
  return waitingReason(current, tasks) ?? "Waiting — no dependency detail recorded";
}

// --- recovery ---------------------------------------------------------------

export interface RecoveryStep {
  label: string;
  detail: string | null;
  tone: "down" | "warn" | "ok" | "muted";
}

const RECOVERY_LABELS: Record<string, string> = {
  RECOVERY_SELECTED: "Recovery decision",
  RETRY_STARTED: "Retry started",
  AGENT_REPLACED: "Agent replaced",
  MODEL_SWITCHED: "Model switched",
  CONTEXT_COMPACTED: "Context compacted",
  DEBUGGER_SPAWNED: "Debugger spawned",
  DEPENDENCY_WAIT_STARTED: "Waiting for dependency",
  DEPENDENCY_RESUMED: "Dependency resolved",
  TASK_TERMINALLY_FAILED: "Terminally failed",
};

const RECOVERY_TYPES = new Set(Object.keys(RECOVERY_LABELS));

function payloadText(payload: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = payload[key];
    if (typeof value === "string" && value) return value;
  }
  return null;
}

/**
 * The real recovery lifecycle for one task: attempt outcomes (with failure
 * class + detail) interleaved with recorded recovery events, oldest first.
 * Empty when nothing ever failed and no recovery was recorded.
 */
export function recoveryForTask(task: TaskInfo, events: EventEntry[]): RecoveryStep[] {
  const steps: RecoveryStep[] = [];
  for (const attempt of [...task.attempts].sort((a, b) => a.attempt_number - b.attempt_number)) {
    if (attempt.outcome === null || attempt.outcome === "success") continue;
    const what = attempt.failure_class ?? attempt.outcome;
    steps.push({
      label: `Attempt ${attempt.attempt_number} ${attempt.outcome}`,
      detail: [what, attempt.failure_detail].filter(Boolean).join(" — "),
      tone: "down",
    });
  }
  const related = events
    .filter((e) => e.task_id === task.id && RECOVERY_TYPES.has(e.event_type))
    .sort((a, b) => Date.parse(a.occurred_at) - Date.parse(b.occurred_at));
  for (const event of related) {
    const action =
      event.event_type === "RECOVERY_SELECTED"
        ? (payloadText(event.payload, ["action"]) ?? "decision recorded")
        : null;
    steps.push({
      label: event.event_type === "RECOVERY_SELECTED"
        ? `Recovery decision: ${action}`
        : (RECOVERY_LABELS[event.event_type] ?? event.event_type),
      detail: payloadText(event.payload, ["failure_class", "detail", "reason"]),
      tone: event.event_type === "TASK_TERMINALLY_FAILED" ? "down" : "warn",
    });
  }
  return steps;
}

export interface RecoveryState {
  label: string;
  tone: "ok" | "warn" | "down" | "muted";
}

/** One-line recovery verdict for cards: recovered / recovering / failing. */
export function recoveryState(task: TaskInfo, events: EventEntry[]): RecoveryState | null {
  const hadFailure = task.attempts.some(
    (a) => a.outcome !== null && a.outcome !== "success",
  );
  const recoveryEvents = events.filter(
    (e) => e.task_id === task.id && RECOVERY_TYPES.has(e.event_type),
  );
  if (!hadFailure && recoveryEvents.length === 0) return null;
  if (task.status === "completed" && hadFailure) return { label: "Recovered", tone: "ok" };
  if (task.status === "failed") {
    return recoveryEvents.length > 0
      ? { label: "Recovery attempted · still failing", tone: "down" }
      : { label: "Failed · no recovery recorded", tone: "down" };
  }
  if (recoveryEvents.length > 0) return { label: "Recovering", tone: "warn" };
  if (hadFailure) return { label: "Failed attempts on record", tone: "warn" };
  return null;
}

// --- execution overview ------------------------------------------------------

export interface ExecutionSummary {
  label: string;
  tone: "ok" | "warn" | "down" | "muted";
  running: number;
  waiting: number;
  failed: number;
  total: number;
}

export function summarizeExecution(
  agentStates: string[],
  tasks: TaskInfo[],
): ExecutionSummary {
  const running = tasks.filter((t) => t.status === "running").length;
  const waiting = tasks.filter((t) =>
    ["waiting", "blocked", "ready", "pending"].includes(t.status),
  ).length;
  const failed = tasks.filter((t) => t.status === "failed").length;
  const recovering = agentStates.filter((s) => s === "recovering").length;
  const total = tasks.length;
  if (total === 0) return { label: "No tasks", tone: "muted", running, waiting, failed, total };
  if (failed > 0 || recovering > 0) {
    return { label: "Needs attention", tone: "down", running, waiting, failed, total };
  }
  if (running > 0) return { label: "Running", tone: "ok", running, waiting, failed, total };
  if (agentStates.some((s) => ["paused", "waiting", "blocked"].includes(s)) || waiting > 0) {
    return { label: "Waiting", tone: "warn", running, waiting, failed, total };
  }
  if (tasks.every((t) => TERMINAL_TASK.has(t.status))) {
    return { label: "Completed", tone: "ok", running, waiting, failed, total };
  }
  return { label: "Ready", tone: "muted", running, waiting, failed, total };
}

// --- agent activity from the event stream ------------------------------------

export function lastAgentEvent(events: EventEntry[], agentId: string): EventEntry | null {
  return events.find((e) => e.agent_id === agentId) ?? null;
}

export function firstAgentEvent(events: EventEntry[], agentId: string): EventEntry | null {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].agent_id === agentId) return events[i];
  }
  return null;
}

/** Human sentence for what the agent last did — event type + payload detail. */
export function describeEvent(event: EventEntry): string {
  const detail = payloadText(event.payload, ["detail", "title", "action", "status", "verdict"]);
  const type = event.event_type.replaceAll("_", " ").toLowerCase();
  return detail ? `${type}: ${detail}` : type;
}

// --- timeline grouping -------------------------------------------------------

export interface TimelineGroup {
  key: string;
  event_type: string;
  count: number;
  newest: EventEntry;
  oldest: EventEntry;
  details: string[];
}

/** Burst window for "3 agents started in parallel"-style aggregation. */
export const GROUP_WINDOW_MS = 90_000;

function brief(event: EventEntry): string | null {
  const detail = payloadText(event.payload, ["detail", "verdict", "status", "title"]);
  return detail ? `${event.event_type} — ${detail}` : null;
}

/** Merge consecutive same-type events inside the time window (newest-first). */
export function groupTimeline(events: EventEntry[]): TimelineGroup[] {
  const groups: TimelineGroup[] = [];
  for (const event of events) {
    const current = groups[groups.length - 1];
    if (
      current &&
      current.event_type === event.event_type &&
      Date.parse(String(current.oldest.occurred_at)) - Date.parse(String(event.occurred_at)) <= GROUP_WINDOW_MS
    ) {
      current.count += 1;
      current.oldest = event;
      const text = brief(event);
      if (text && !current.details.includes(text) && current.details.length < 3) {
        current.details.push(text);
      }
      continue;
    }
    const text = brief(event);
    groups.push({
      key: `${event.id}`,
      event_type: event.event_type,
      count: 1,
      newest: event,
      oldest: event,
      details: text ? [text] : [],
    });
  }
  return groups;
}

// --- timeline categories -----------------------------------------------------

const CATEGORY_PREFIXES: { category: string; label: string; prefixes: string[] }[] = [
  // Recovery first: AGENT_REPLACED belongs to recovery, not the agent feed.
  { category: "recovery", label: "Recovery", prefixes: ["RECOVERY_", "RETRY_", "MODEL_SWITCHED", "CONTEXT_COMPACTED", "DEBUGGER_SPAWNED", "AGENT_REPLACED"] },
  { category: "agents", label: "Agents", prefixes: ["AGENT_"] },
  { category: "tasks", label: "Tasks", prefixes: ["TASK_", "DEPENDENCY_"] },
  { category: "tools", label: "Tools", prefixes: ["TOOL_", "MCP_", "BROWSER_"] },
  { category: "tests", label: "Tests", prefixes: ["REVIEW_", "DECISION_", "SECURITY_", "SCOPE_"] },
  { category: "hitl", label: "Approvals", prefixes: ["HITL_"] },
];

export function eventCategory(eventType: string): string {
  for (const { category, prefixes } of CATEGORY_PREFIXES) {
    if (prefixes.some((p) => eventType.startsWith(p))) return category;
  }
  return "other";
}

export function categories(): { category: string; label: string }[] {
  return CATEGORY_PREFIXES.map(({ category, label }) => ({ category, label }));
}

// --- bulk execution ----------------------------------------------------------

/**
 * Tasks eligible for a bulk lifecycle action. Single source of truth: the
 * same per-task availability builder the buttons and palette use, so bulk
 * buttons can never offer what the endpoints would refuse. Retry is
 * per-task only (each failed task deserves its own confirmation).
 */
export function bulkEligible(
  tasks: TaskInfo[],
  action: "pause" | "resume" | "cancel",
): TaskInfo[] {
  const enabled = new Set(
    taskCommands(tasks, async () => undefined)
      .filter((c) => c.id.endsWith(`.${action}`) && !c.disabledReason)
      .map((c) => c.id),
  );
  return tasks.filter((t) => enabled.has(`task.${t.id}.${action}`));
}

export const BULK_LABEL: Record<"pause" | "resume" | "cancel", string> = {
  pause: "Pause",
  resume: "Resume",
  cancel: "Cancel",
};

export function bulkConfirm(
  action: "pause" | "resume" | "cancel",
  count: number,
): string {
  if (action === "cancel") {
    return `Cancel ${count} task${count === 1 ? "" : "s"}? History is preserved and statuses become cancelled.`;
  }
  return action === "pause"
    ? `Pause ${count} task${count === 1 ? "" : "s"}? Signals apply at safe checkpoints; acknowledgement is not a state change.`
    : `Resume ${count} task${count === 1 ? "" : "s"}? Paused workflows continue from their checkpoints.`;
}

// --- attention (UI3): backend-side failures included -------------------------

export interface AttentionItem {
  kind: "task-failed" | "task-blocked" | "tool-failed" | "approval" | "requirement-failed" | "requirement-blocked";
  title: string;
  detail: string | null;
  taskId: string | null;
  agentId: string | null;
  requirementId?: string | null;
}

/**
 * Everything that needs the supervisor, from RECORDED state: failed/blocked
 * tasks, failed tool runs (latest per signature), pending approvals, and
 * failed/blocked requirements (UI4). Client-only output failures stay with
 * the caller (Center keeps its last-run row). Requirements are optional so
 * older callers keep working. Sorted: approvals and failures first, blocks
 * (tasks, then requirements) last.
 */
export function collectAttention(
  events: EventEntry[],
  tasks: TaskInfo[],
  hitl: HitlRequestInfo[],
  requirements: { id: string; title: string; status: string; task_ids: string[] }[] = [],
): AttentionItem[] {
  const items: AttentionItem[] = [];
  const byId = new Map(tasks.map((t) => [t.id, t]));
  const requirementByTask = new Map<string, string>();
  for (const requirement of requirements) {
    for (const taskId of requirement.task_ids) {
      if (!requirementByTask.has(taskId)) requirementByTask.set(taskId, requirement.title);
    }
  }
  for (const task of tasks) {
    if (task.status === "failed") {
      const last = [...task.attempts].sort((a, b) => b.attempt_number - a.attempt_number)[0];
      items.push({
        kind: "task-failed",
        title: `Task failed: ${task.title}`,
        detail: last?.failure_class ? `${last.failure_class} (attempt #${last.attempt_number})` : null,
        taskId: task.id,
        agentId: last?.agent_id ?? null,
      });
    } else if (task.status === "blocked") {
      items.push({
        kind: "task-blocked",
        title: `Task blocked: ${task.title}`,
        detail: waitingReason(task, tasks),
        taskId: task.id,
        agentId: null,
      });
    }
  }
  const seen = new Set<string>();
  for (const e of events) {
    if (e.event_type !== "TOOL_RUN_COMPLETED") continue;
    const exit = typeof e.payload.exit_code === "number" ? e.payload.exit_code : null;
    if (exit === null || exit === 0) continue;
    const tool = typeof e.payload.tool === "string" ? e.payload.tool : "tool";
    // One row per failure signature (tool + exit + task): repeat runs of the
    // same failing step collapse to the latest instead of spamming the strip.
    // Events arrive newest-first, so the first occurrence wins.
    const key = `${tool}:${exit}:${e.task_id ?? "unscoped"}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const taskTitle = e.task_id ? byId.get(e.task_id)?.title : null;
    items.push({
      kind: "tool-failed",
      title: `Tool failed: ${tool} (exit ${exit})`,
      detail: taskTitle ? `on task ${taskTitle}` : null,
      taskId: e.task_id,
      agentId: e.agent_id,
    });
  }
  for (const h of hitl) {
    if (h.status !== "pending") continue;
    const reqTitle = h.task_id ? requirementByTask.get(h.task_id) ?? null : null;
    items.push({
      kind: "approval",
      title: `Approval: ${h.question}`,
      detail: h.task_id ? (reqTitle ? `${byId.get(h.task_id)?.title ?? "task"} · ${reqTitle}` : (byId.get(h.task_id)?.title ?? null)) : null,
      taskId: h.task_id,
      agentId: null,
    });
  }
  for (const requirement of requirements) {
    const state = requirement.status.toUpperCase();
    if (state === "FAILED") {
      items.push({
        kind: "requirement-failed",
        title: `Verification failed: ${requirement.title}`,
        detail: null,
        taskId: null,
        agentId: null,
        requirementId: requirement.id,
      });
    } else if (state !== "VERIFIED") {
      const linked = requirement.task_ids.map((id) => byId.get(id)).filter((t): t is TaskInfo => !!t);
      if (linked.some((t) => t.status === "blocked" || t.status === "failed")) {
        items.push({
          kind: "requirement-blocked",
          title: `Verification blocked: ${requirement.title}`,
          detail: "A linked task is blocked or failed",
          taskId: null,
          agentId: null,
          requirementId: requirement.id,
        });
      }
    }
  }
  const rank: Record<AttentionItem["kind"], number> = {
    approval: 0,
    "task-failed": 1,
    "requirement-failed": 1,
    "tool-failed": 2,
    "task-blocked": 3,
    "requirement-blocked": 3,
  };
  return items.sort((a, b) => rank[a.kind] - rank[b.kind]);
}

// --- dependency map ----------------------------------------------------------

export interface DepNode {
  id: string;
  title: string;
  status: string;
  layer: number;
  x: number;
  y: number;
}

export interface DepEdge {
  from: string;
  to: string;
}

export const DEP_NODE_W = 132;
export const DEP_NODE_H = 34;
const DEP_GAP_X = 12;
const DEP_GAP_Y = 44;

/**
 * Layered layout for the task dependency DAG (roots at the top). Edges to
 * tasks outside the set are dropped (shown as "(external)" nowhere — the
 * inspector names them instead). Cycle-guarded: a repeated id resolves to
 * its first depth rather than recursing forever.
 */
export function layoutDeps(tasks: TaskInfo[]): {
  nodes: DepNode[];
  edges: DepEdge[];
  width: number;
  height: number;
} {
  const byId = new Map(tasks.map((t) => [t.id, t]));
  const depth = new Map<string, number>();
  const visit = (id: string, trail: string[]): number => {
    const known = depth.get(id);
    if (known !== undefined) return known;
    if (trail.includes(id)) return trail.indexOf(id); // cycle: pin to first depth
    const task = byId.get(id);
    if (!task) return 0;
    const inner = task.depends_on.filter((d) => byId.has(d));
    const level = inner.length === 0 ? 0 : 1 + Math.max(...inner.map((d) => visit(d, [...trail, id])));
    depth.set(id, level);
    return level;
  };
  for (const t of tasks) visit(t.id, []);
  const layers = new Map<number, TaskInfo[]>();
  for (const t of tasks) {
    const layer = depth.get(t.id) ?? 0;
    layers.set(layer, [...(layers.get(layer) ?? []), t]);
  }
  const nodes: DepNode[] = [];
  const index = new Map<string, DepNode>();
  for (const [layer, members] of [...layers.entries()].sort((a, b) => a[0] - b[0])) {
    members.forEach((t, i) => {
      const node: DepNode = {
        id: t.id,
        title: t.title,
        status: t.status,
        layer,
        x: i * (DEP_NODE_W + DEP_GAP_X),
        y: layer * (DEP_NODE_H + DEP_GAP_Y),
      };
      nodes.push(node);
      index.set(t.id, node);
    });
  }
  const edges: DepEdge[] = [];
  for (const t of tasks) {
    for (const dep of t.depends_on) {
      if (byId.has(dep)) edges.push({ from: dep, to: t.id });
    }
  }
  const width = Math.max(1, ...nodes.map((n) => n.x + DEP_NODE_W));
  const height = Math.max(1, ...nodes.map((n) => n.y + DEP_NODE_H));
  return { nodes, edges, width, height };
}

// --- event replay ---------------------------------------------------------------

export interface ReplayStep {
  id: string;
  event: EventEntry;
  label: string;
  agentId: string | null;
  taskId: string | null;
}

/**
 * Chronological replay script over the LOADED event window (newest-first in
 * the store). Bounded by construction: replaying cannot reach history the
 * server never sent, and the UI labels that scope everywhere it matters.
 */
export function replaySteps(events: EventEntry[]): ReplayStep[] {
  return [...events]
    .sort((a, b) => Date.parse(a.occurred_at) - Date.parse(b.occurred_at))
    .map((e) => ({
      id: e.id,
      event: e,
      label: describeEvent(e),
      agentId: e.agent_id,
      taskId: e.task_id,
    }));
}

// --- costs -------------------------------------------------------------------

/**
 * Who else touched this task: honest cost attribution. A task scoped cost
 * summary belongs to one agent only when no other agent attempted it;
 * otherwise it is shared and the UI must say so instead of dividing numbers.
 */
export function costAttribution(
  task: TaskInfo,
  agentId: string,
): { sole: boolean; others: number } {
  const ids = [...new Set(task.attempts.map((a) => a.agent_id).filter(Boolean))];
  return {
    sole: ids.length === 1 && ids[0] === agentId,
    others: ids.filter((id) => id !== agentId).length,
  };
}

/** Shape guard: a malformed ledger payload must read as absent, never crash. */
export function validCosts(costs: CostsSummary | null | undefined): costs is CostsSummary {
  return (
    !!costs &&
    typeof costs.total_tokens === "number" &&
    typeof costs.by_role === "object" &&
    costs.by_role !== null
  );
}

export function topEntries(record: Record<string, number>, limit = 4): [string, number][] {
  return Object.entries(record)
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit);
}

export function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return `${n}`;
}

// --- communication -----------------------------------------------------------

/** "Backend Agent → Test Agent" with unknown endpoints labeled honestly. */
export function messageEndpoints(
  message: MessageInfo,
  nameOf: (id: string | null) => string,
): string {
  const from = message.sender_agent_id ? nameOf(message.sender_agent_id) : "system";
  const to = message.recipient_agent_id ? nameOf(message.recipient_agent_id) : "broadcast";
  return `${from} → ${to}`;
}

export function messageSummary(message: MessageInfo): string {
  const text = payloadText(message.payload, ["summary", "text", "detail", "question"]);
  if (text) return text.length > 140 ? `${text.slice(0, 140)}…` : text;
  const keys = Object.keys(message.payload);
  return keys.length > 0 ? `payload: ${keys.slice(0, 4).join(", ")}` : "empty payload";
}

export interface ProblemItem {
  kind: "task-failed" | "task-blocked" | "tool-failed" | "approval-pending";
  title: string;
  detail: string;
  taskId: string | null;
}

/**
 * Problems view projection (Wave 6): failed/blocked tasks, failed tool runs
 * and pending approvals from already-loaded store state — no new fetches.
 * Empty result means genuinely clean, never "no data loaded".
 */
export function collectProblems(input: {
  tasks: TaskInfo[];
  output: ToolRunResult | null;
  hitl: HitlRequestInfo[];
}): ProblemItem[] {
  const problems: ProblemItem[] = [];
  for (const task of input.tasks) {
    if (task.status === "failed") {
      const lastFailure = [...task.attempts]
        .reverse()
        .find((a) => a.outcome === "failed" || a.failure_class);
      problems.push({
        kind: "task-failed",
        title: task.title,
        detail:
          lastFailure?.failure_detail ??
          lastFailure?.failure_class ??
          "Failed without recorded detail",
        taskId: task.id,
      });
    } else if (task.status === "blocked" || task.status === "ready") {
      const reason = waitingReason(task, input.tasks);
      problems.push({
        kind: "task-blocked",
        title: task.title,
        detail: reason ?? "Waiting",
        taskId: task.id,
      });
    }
  }
  const output = input.output;
  if (output && output.exit_code !== null && output.exit_code !== 0) {
    problems.push({
      kind: "tool-failed",
      title: `${output.tool} ${output.language} failed (exit ${output.exit_code})`,
      detail: output.diagnostics[0] ?? output.stderr.slice(0, 200) ?? "See output panel",
      taskId: null,
    });
  }
  for (const request of input.hitl) {
    if (request.status !== "pending") continue;
    problems.push({
      kind: "approval-pending",
      title: request.question,
      detail: `${request.kind} · ${request.risk} risk — decide in Office oversight`,
      taskId: request.task_id,
    });
  }
  return problems;
}

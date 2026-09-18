// Deterministic realtime event reducer (Wave 3, §14/§15/§16).
//
// Pure functions only: validate → deduplicate → check ordering → project into
// state. No fetches, no React, no business logic in components. The office
// store consumes these; the timeline and team/oversight projections update
// incrementally — never by reloading whole state per event.

import type {
  AgentInfo,
  EventEntry,
  EventEnvelope,
  HitlRequestInfo,
  TaskInfo,
} from "../types";

/** Client-side timeline cap (mirrors the server list limit). */
export const MAX_TIMELINE_EVENTS = 120;
/** Bounded dedup window: recent event ids only (memory-safe). */
const DEDUP_WINDOW = 512;

export interface ProjectionState {
  agents: AgentInfo[];
  tasks: TaskInfo[];
  hitl: HitlRequestInfo[];
  events: EventEntry[];
  lastSequence: number | null;
  /** Rolling window of recent event ids for duplicate detection. */
  seenEventIds: string[];
}

export function projectionFromLists(
  agents: AgentInfo[],
  tasks: TaskInfo[],
  hitl: HitlRequestInfo[],
  events: EventEntry[],
): ProjectionState {
  let lastSequence: number | null = null;
  for (const e of events) {
    if (typeof e.project_seq === "number" && (lastSequence === null || e.project_seq > lastSequence)) {
      lastSequence = e.project_seq;
    }
  }
  return {
    agents,
    tasks,
    hitl,
    events,
    lastSequence,
    seenEventIds: events.slice(0, DEDUP_WINDOW).map((e) => e.id),
  };
}

/** True when this exact event was already applied (duplicate delivery). */
export function isDuplicate(state: ProjectionState, envelope: EventEnvelope): boolean {
  return state.seenEventIds.includes(envelope.event_id);
}

/**
 * Sequence gate: "apply" | "duplicate" | "gap".
 * A gap means events were missed → the caller must resync from the
 * authoritative API before trusting the projection.
 */
export function sequenceCheck(
  state: ProjectionState,
  envelope: EventEnvelope,
): "apply" | "duplicate" | "gap" {
  if (envelope.sequence === null) return "apply"; // unsequenced (global) events
  if (isDuplicate(state, envelope)) return "duplicate";
  if (state.lastSequence !== null && envelope.sequence > state.lastSequence + 1) return "gap";
  if (state.lastSequence !== null && envelope.sequence <= state.lastSequence) return "duplicate";
  return "apply";
}

function envelopeToEntry(envelope: EventEnvelope): EventEntry {
  return {
    id: envelope.event_id,
    occurred_at: envelope.timestamp,
    event_type: envelope.event_type,
    source: envelope.source,
    project_id: envelope.project_id,
    task_id: envelope.task_id,
    agent_id: envelope.agent_id,
    payload: envelope.payload,
    project_seq: envelope.sequence,
    execution_id: envelope.execution_id,
  };
}

function recordSeen(state: ProjectionState, envelope: EventEnvelope): ProjectionState {
  const seenEventIds = [envelope.event_id, ...state.seenEventIds].slice(0, DEDUP_WINDOW);
  const lastSequence =
    envelope.sequence !== null &&
    (state.lastSequence === null || envelope.sequence > state.lastSequence)
      ? envelope.sequence
      : state.lastSequence;
  return { ...state, seenEventIds, lastSequence };
}

// --- agent lifecycle events ----------------------------------------------------

function applyAgentEvent(state: ProjectionState, envelope: EventEnvelope): ProjectionState {
  const payload = envelope.payload;
  const agentId = envelope.agent_id ?? (payload.agent_id as string | undefined) ?? null;
  if (!agentId) return state;

  if (envelope.event_type === "AGENT_CREATED") {
    if (state.agents.some((a) => a.id === agentId)) return state;
    const agent: AgentInfo = {
      id: agentId,
      project_id: envelope.project_id,
      name: (payload.name as string | undefined) ?? agentId.slice(0, 8),
      role: (payload.role as string | undefined) ?? "worker",
      model: (payload.model as string | undefined) ?? null,
      capabilities: [],
      state: (payload.to as string | undefined) ?? "created",
    };
    return { ...state, agents: [...state.agents, agent] };
  }

  const target = payload.to as string | undefined;
  const agents = state.agents.map((agent) => {
    if (agent.id !== agentId) return agent;
    if (target && (envelope.event_type === "AGENT_STATUS_CHANGED" || envelope.event_type === "AGENT_STARTED")) {
      return { ...agent, state: target };
    }
    return agent;
  });
  return { ...state, agents };
}

// --- task lifecycle events -------------------------------------------------------

const TASK_TERMINAL: Record<string, string> = {
  TASK_COMPLETED: "completed",
  TASK_FAILED: "failed",
  TASK_TERMINALLY_FAILED: "failed",
  TASK_CANCELLED: "cancelled",
};

const TASK_TRANSITIONS: Record<string, string> = {
  TASK_SCHEDULED: "running",
  TASK_EXECUTION_STARTED: "running",
  TASK_REPLANNED: "pending",
  DEPENDENCY_WAIT_STARTED: "blocked",
  DEPENDENCY_RESUMED: "ready",
};

function applyTaskEvent(state: ProjectionState, envelope: EventEnvelope): ProjectionState {
  const taskId = envelope.task_id;
  if (!taskId) return state;
  const nextStatus = TASK_TERMINAL[envelope.event_type] ?? TASK_TRANSITIONS[envelope.event_type];
  if (!nextStatus) return state;
  const tasks = state.tasks.map((task) =>
    task.id === taskId && task.status !== nextStatus ? { ...task, status: nextStatus } : task,
  );
  return { ...state, tasks };
}

// --- HITL events -------------------------------------------------------------------

function applyHitlEvent(state: ProjectionState, envelope: EventEnvelope): ProjectionState {
  if (
    envelope.event_type === "HITL_RESPONDED" ||
    envelope.event_type === "HITL_RECOVERY_RESPONDED"
  ) {
    const hitl = state.hitl.filter(
      (h) => !envelope.task_id || h.task_id !== envelope.task_id || h.status !== "pending",
    );
    return { ...state, hitl };
  }
  return state;
}

/**
 * Apply one validated, deduplicated, in-order envelope.
 * Returns the next projection plus a flag telling the store whether a targeted
 * HITL list refresh is wanted (request bodies live in the durable API).
 */
export function applyEnvelope(
  state: ProjectionState,
  envelope: EventEnvelope,
): { projection: ProjectionState; hitlDirty: boolean } {
  let next = recordSeen(state, envelope);
  let hitlDirty = false;

  if (envelope.event_type.startsWith("AGENT_")) {
    next = applyAgentEvent(next, envelope);
  } else if (
    envelope.event_type.startsWith("TASK_") ||
    envelope.event_type.startsWith("DEPENDENCY_")
  ) {
    next = applyTaskEvent(next, envelope);
  } else if (envelope.event_type.startsWith("HITL_")) {
    hitlDirty = true;
    next = applyHitlEvent(next, envelope);
  }
  // RECOVERY_*/MODEL_SWITCHED/DEBUGGER_SPAWNED stay timeline-only: the durable
  // rows reconcile via targeted resync when they matter (no speculative edits).

  const events = [envelopeToEntry(envelope), ...next.events].slice(0, MAX_TIMELINE_EVENTS);
  return { projection: { ...next, events }, hitlDirty };
}

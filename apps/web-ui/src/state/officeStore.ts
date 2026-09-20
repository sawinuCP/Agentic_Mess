// Office state (Phase 9, FR-025; realtime since Wave 3).
//
// The office projection is fed by the SSE event stream (`/api/events/stream`):
// one authoritative load on start, then incremental updates via the pure event
// reducer. The 2.5 s REST polling is GONE (AR-01). Reconnection uses bounded
// exponential backoff with jitter; sequence gaps or RESYNC_REQUIRED trigger an
// authoritative resync. A slow fallback poll runs ONLY while the gateway is
// degraded (visible in the UI) — the realtime stream is a projection, the REST
// API is always the source of truth.

import { create } from "zustand";

import * as api from "../api/client";
import { streamEvents, type StreamHandle } from "../api/sse";
import type {
  AgentInfo,
  ConnectionState,
  ControlFrame,
  CostsSummary,
  EventEnvelope,
  EventEntry,
  HitlRequestInfo,
  MessageInfo,
  ReviewOutcome,
  TaskInfo,
  TraceabilityReport,
  WorktreeInfo,
} from "../types";
import {
  applyEnvelope,
  projectionFromLists,
  sequenceCheck,
  type ProjectionState,
} from "./eventReducer";

/** Ledger shape guard kept local so malformed payloads read as absent. */
function isCostsSummary(value: unknown): value is CostsSummary {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return typeof v.total_tokens === "number" && typeof v.by_role === "object" && v.by_role !== null;
}

/** Visible fallback ONLY while degraded (NATS/gateway down): slow, explicit. */
export const DEGRADED_POLL_MS = 10_000;
/** Bounded exponential reconnect backoff with jitter. */
export const RECONNECT_BASE_MS = 500;
export const RECONNECT_MAX_MS = 15_000;

export type OfficeTab = "team" | "timeline" | "comms" | "oversight";

export function backoffDelay(attempt: number): number {
  const raw = Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS);
  const jitter = raw * 0.25 * Math.random(); // ±25% — no reconnect storms
  return Math.min(RECONNECT_MAX_MS, Math.round(raw + jitter - (raw * 0.25) / 2));
}

interface OfficeState {
  projectId: string | null;
  tab: OfficeTab;
  selectedAgentId: string | null;
  selectedTaskId: string | null;
  selectedRequirementId: string | null;
  activityFilter: { agentId: string | null; taskId: string | null } | null;
  spawnDialog: boolean;
  taskDialog: boolean;
  /** Prefilled comms recipient (UI3 contextual Message action). Draft-only. */
  commsRecipient: string | null;
  connectionState: ConnectionState;
  gatewayMode: "live" | "degraded" | "unknown";
  lastEventSequence: number | null;
  lastEventTimestamp: string | null;
  eventRate: number;
  resyncRequired: boolean;
  agents: AgentInfo[];
  tasks: TaskInfo[];
  hitl: HitlRequestInfo[];
  events: EventEntry[];
  messages: MessageInfo[];
  messagesLoading: boolean;
  messagesError: string | null;
  worktrees: WorktreeInfo[];
  worktreesLoading: boolean;
  worktreesError: string | null;
  costs: CostsSummary | null;
  costsLoading: boolean;
  costsError: string | null;
  taskCosts: Record<string, CostsSummary>;
  traceability: TraceabilityReport | null;
  completionBusy: boolean;
  reviewBusyTaskId: string | null;
  lastReview: ReviewOutcome | null;
  notice: string | null;

  start: (projectId: string) => void;
  stop: () => void;
  resync: () => Promise<void>;
  refresh: () => Promise<void>;
  loadMessages: () => Promise<void>;
  loadWorktrees: () => Promise<void>;
  loadCosts: () => Promise<void>;
  loadTaskCosts: (taskId: string) => Promise<void>;
  set: (partial: Partial<OfficeState>) => void;
  decideHitl: (
    requestId: string,
    decision: "approved" | "rejected",
    note?: string,
  ) => Promise<void>;
  reviewTask: (taskId: string, title: string, proposal: string) => Promise<void>;
  generateCompletion: () => Promise<void>;
}

// Non-reactive connection machinery (module scope — one stream per page).
let streamHandle: StreamHandle | null = null;
let abortController: AbortController | null = null;
let reconnectAttempt = 0;
let stopped = true;
let generation = 0;
let syncJob: Promise<void> | null = null;
let degradedTimer: number | null = null;
let rateWindow: number[] = [];

function eventsPerSecond(): number {
  const cutoff = Date.now() - 10_000;
  rateWindow = rateWindow.filter((t) => t >= cutoff);
  return Math.round((rateWindow.length / 10) * 10) / 10;
}

export const useOffice = create<OfficeState>((set, get) => {
  async function refreshHitl(): Promise<void> {
    const projectId = get().projectId;
    if (!projectId) return;
    try {
      set({ hitl: await api.listHitl(projectId, "pending") });
    } catch {
      // targeted refresh failed — the next resync covers it
    }
  }

  function startDegradedPoll(): void {
    if (degradedTimer !== null) return;
    degradedTimer = window.setInterval(() => {
      const projectId = get().projectId;
      if (!projectId || stopped) return;
      void get()
        .resync()
        .catch(() => undefined);
    }, DEGRADED_POLL_MS);
  }

  function stopDegradedPoll(): void {
    if (degradedTimer !== null) {
      window.clearInterval(degradedTimer);
      degradedTimer = null;
    }
  }

  function applyControl(frame: ControlFrame): void {
    if (frame.kind === "GATEWAY_STATUS") {
      const mode = frame.state ?? "unknown";
      reconnectAttempt = 0;
      set({
        gatewayMode: mode,
        connectionState: mode === "degraded" ? "degraded" : "live",
      });
      if (mode === "degraded") startDegradedPoll();
      else stopDegradedPoll();
      return;
    }
    if (frame.kind === "RESYNC_REQUIRED") {
      set({ resyncRequired: true });
      void get().resync();
      return;
    }
    if (frame.kind === "DISCONNECT") {
      streamHandle?.abort();
    }
  }

  function applyEnvelopeToStore(envelope: EventEnvelope): void {
    const state = get();
    if (syncJob || state.resyncRequired || envelope.project_id !== state.projectId) return;
    const projection: ProjectionState = projectionFromLists(
      state.agents,
      state.tasks,
      state.hitl,
      state.events,
    );
    projection.lastSequence = state.lastEventSequence;
    const check = sequenceCheck(projection, envelope);
    if (check === "duplicate") return; // at-least-once delivery is safe
    if (check === "gap") {
      set({ resyncRequired: true });
      void get().resync();
      return;
    }
    const { projection: next, hitlDirty } = applyEnvelope(projection, envelope);
    rateWindow = [...rateWindow.slice(-49), Date.now()];
    set({
      agents: next.agents,
      tasks: next.tasks,
      hitl: next.hitl,
      events: next.events,
      lastEventSequence: next.lastSequence,
      lastEventTimestamp: envelope.timestamp,
      eventRate: eventsPerSecond(),
      resyncRequired: false,
    });
    if (hitlDirty) void refreshHitl();
  }

  async function runStreamLoop(session: number): Promise<void> {
    const active = () => !stopped && generation === session;
    while (active()) {
      if (get().resyncRequired) await get().resync();
      if (!active()) return;
      if (get().resyncRequired) {
        await new Promise((resolve) => window.setTimeout(resolve, backoffDelay(reconnectAttempt++)));
        continue;
      }
      const projectId = get().projectId;
      if (!projectId) return;
      abortController = new AbortController();
      const controller = abortController;
      try {
        const since = get().lastEventSequence;
        const handle = streamEvents(
          projectId,
          since,
          {
            onEnvelope: (event) => { if (active()) applyEnvelopeToStore(event); },
            onControl: (frame) => { if (active()) applyControl(frame); },
          },
          controller.signal,
        );
        streamHandle = handle;
        await handle.done;
        if (!active()) return;
        set({ connectionState: "reconnecting" });
      } catch {
        if (!active()) return;
        set({ connectionState: "reconnecting" });
      } finally {
        if (active()) streamHandle = null;
      }
      if (syncJob) await syncJob;
      if (!active()) return;
      await new Promise((resolve) => window.setTimeout(resolve, backoffDelay(reconnectAttempt)));
      if (!active()) return;
      reconnectAttempt = Math.min(reconnectAttempt + 1, 10);
      set({ connectionState: reconnectAttempt > 2 ? "offline" : "reconnecting" });
    }
  }

  return {
    projectId: null,
    tab: "team",
    selectedAgentId: null,
    selectedTaskId: null,
    selectedRequirementId: null,
    activityFilter: null,
    spawnDialog: false,
    taskDialog: false,
    commsRecipient: null,
    connectionState: "connecting",
    gatewayMode: "unknown",
    lastEventSequence: null,
    lastEventTimestamp: null,
    eventRate: 0,
    resyncRequired: false,
    agents: [],
    tasks: [],
    hitl: [],
    events: [],
    messages: [],
    messagesLoading: false,
    messagesError: null,
    worktrees: [],
    worktreesLoading: false,
    worktreesError: null,
    costs: null,
    costsLoading: false,
    costsError: null,
    taskCosts: {},
    traceability: null,
    completionBusy: false,
    reviewBusyTaskId: null,
    lastReview: null,
    notice: null,

    set: (partial) => set(partial),

    start: (projectId) => {
      if (get().projectId === projectId && !stopped) return;
      get().stop();
      const session = generation;
      streamHandle?.abort();
      stopDegradedPoll();
      stopped = false;
      reconnectAttempt = 0;
      rateWindow = [];
      set({
        projectId,
        connectionState: "connecting",
        gatewayMode: "unknown",
        lastEventSequence: null,
        lastEventTimestamp: null,
        eventRate: 0,
        resyncRequired: false,
        notice: null,
        selectedAgentId: null,
        selectedTaskId: null,
        selectedRequirementId: null,
        activityFilter: null,
        messages: [],
        messagesError: null,
        worktrees: [],
        worktreesError: null,
        costs: null,
        costsError: null,
        taskCosts: {},
      });
      void (async () => {
        await get().resync();
        if (!stopped && generation === session) void runStreamLoop(session);
      })();
    },

    stop: () => {
      stopped = true;
      generation++;
      syncJob = null;
      streamHandle?.abort();
      streamHandle = null;
      abortController?.abort();
      abortController = null;
      stopDegradedPoll();
      set({ connectionState: "offline" });
    },

    resync: () => {
      if (syncJob) return syncJob;
      const session = generation;
      const projectId = get().projectId;
      if (!projectId || stopped) return Promise.resolve();
      set({ connectionState: "resyncing", resyncRequired: true });
      // Discard this live connection while replacing the snapshot. Reconnect
      // replays from the cursor captured BEFORE entity reads, not after them.
      streamHandle?.abort();
      const job = (async () => {
        try {
          const events = await api.listEvents(projectId);
          if (session !== generation || stopped) return;
          const [agents, tasks, hitl, traceability] = await Promise.all([
            api.listAgents(projectId), api.listTasks(projectId),
            api.listHitl(projectId, "pending"), api.getTraceability(projectId),
          ]);
          if (session !== generation || stopped) return;
          const projection = projectionFromLists(agents, tasks, hitl, events);
          set({
            agents, tasks, hitl, events, traceability,
            lastEventSequence: projection.lastSequence ?? 0,
            lastEventTimestamp: events[0]?.occurred_at ?? null,
            resyncRequired: false,
            connectionState: get().gatewayMode === "degraded" ? "degraded" : "connecting",
            notice: null,
          });
        } catch (err) {
          if (session !== generation || stopped) return;
          set({ connectionState: "offline", resyncRequired: true,
            notice: err instanceof Error ? err.message : String(err) });
        }
      })();
      syncJob = job;
      void job.finally(() => { if (session === generation) syncJob = null; });
      return job;
    },

    refresh: async () => {
      await get().resync();
    },

    loadMessages: async () => {
      const { projectId, agents } = get();
      if (!projectId || get().messagesLoading) return;
      set({ messagesLoading: true, messagesError: null });
      try {
        // No project-level inbox endpoint exists: merge bounded per-agent
        // inboxes (tolerant of per-agent failures), newest first, capped.
        const results = await Promise.allSettled(
          agents.map((agent) => api.listAgentMessages(agent.id, 40)),
        );
        if (get().projectId !== projectId) return;
        // One message lives in both the sender's and the recipient's
        // inbox — dedupe by id, newest first, bounded.
        const seen = new Set<string>();
        const merged = results
          .flatMap((r) => (r.status === "fulfilled" && Array.isArray(r.value) ? r.value : []))
          .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
          .filter((m) => (seen.has(m.id) ? false : (seen.add(m.id), true)))
          .slice(0, 200);
        set({ messages: merged, messagesLoading: false });
      } catch (err) {
        if (get().projectId !== projectId) return;
        set({
          messagesLoading: false,
          messagesError: err instanceof Error ? err.message : String(err),
        });
      }
    },

    loadWorktrees: async () => {
      const projectId = get().projectId;
      if (!projectId || get().worktreesLoading) return;
      set({ worktreesLoading: true, worktreesError: null });
      try {
        const worktrees = await api.listWorktrees(projectId, 100);
        if (get().projectId !== projectId) return;
        if (!Array.isArray(worktrees)) throw new Error("Unexpected worktree list shape");
        set({ worktrees, worktreesLoading: false });
      } catch (err) {
        if (get().projectId !== projectId) return;
        set({
          worktreesLoading: false,
          worktreesError: err instanceof Error ? err.message : String(err),
        });
      }
    },

    loadCosts: async () => {
      const projectId = get().projectId;
      if (!projectId || get().costsLoading) return;
      set({ costsLoading: true, costsError: null });
      try {
        const costs = await api.getCosts(projectId);
        if (get().projectId !== projectId) return;
        if (!isCostsSummary(costs)) throw new Error("Unexpected cost summary shape");
        set({ costs, costsLoading: false });
      } catch (err) {
        if (get().projectId !== projectId) return;
        set({
          costsLoading: false,
          costsError: err instanceof Error ? err.message : String(err),
        });
      }
    },

    loadTaskCosts: async (taskId: string) => {
      const projectId = get().projectId;
      if (!projectId || get().taskCosts[taskId]) return;
      try {
        const summary = await api.getCosts(projectId, taskId);
        if (get().projectId !== projectId) return;
        if (!isCostsSummary(summary)) return;
        set({ taskCosts: { ...get().taskCosts, [taskId]: summary } });
      } catch {
        // Task-scoped costs stay absent; the detail section explains why.
      }
    },

    decideHitl: async (requestId, decision, note) => {
      const projectId = get().projectId;
      if (!projectId) return;
      await api.decideHitl(projectId, requestId, {
        decision,
        decided_by: "human",
        note,
      });
      await refreshHitl();
    },

    reviewTask: async (taskId, title, proposal) => {
      set({ reviewBusyTaskId: taskId, notice: null });
      try {
        const outcome = await api.runReview(taskId, { title, proposal });
        set({ lastReview: outcome });
        await refreshHitl();
      } catch (err) {
        set({ notice: err instanceof Error ? err.message : String(err) });
      } finally {
        set({ reviewBusyTaskId: null });
      }
    },

    generateCompletion: async () => {
      const projectId = get().projectId;
      if (!projectId) return;
      set({ completionBusy: true, notice: null });
      try {
        const report = await api.requestCompletion(projectId);
        set({ traceability: report });
      } catch (err) {
        // 409 carries the blocked report — still the freshest oversight data.
        if (err instanceof api.ApiError) {
          set({ notice: err.message });
        } else {
          set({ notice: err instanceof Error ? err.message : String(err) });
        }
      } finally {
        set({ completionBusy: false });
      }
    },
  };
});

export const runningAgents = (agents: AgentInfo[]): AgentInfo[] =>
  agents.filter((a) => a.state === "running" || a.state === "working");

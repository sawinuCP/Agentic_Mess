// Office state (Phase 9, FR-025): live agent/team view, timeline, oversight.
//
// A dedicated zustand store polls the control plane on a bounded interval and
// feeds the Office sidebar. Typographic polish (Typehug) and text morphing
// (Torph) are applied in the components, never here.

import { create } from "zustand";

import * as api from "../api/client";
import type {
  AgentInfo,
  EventEntry,
  HitlRequestInfo,
  ReviewOutcome,
  TaskInfo,
  TraceabilityReport,
} from "../types";

export const POLL_MS = 2500;

export type OfficeTab = "team" | "timeline" | "oversight";

interface OfficeState {
  projectId: string | null;
  tab: OfficeTab;
  live: boolean;
  lastPolledAt: string | null;
  agents: AgentInfo[];
  tasks: TaskInfo[];
  hitl: HitlRequestInfo[];
  events: EventEntry[];
  traceability: TraceabilityReport | null;
  completionBusy: boolean;
  reviewBusyTaskId: string | null;
  lastReview: ReviewOutcome | null;
  notice: string | null;

  start: (projectId: string) => void;
  stop: () => void;
  poll: () => Promise<void>;
  set: (partial: Partial<OfficeState>) => void;
  decideHitl: (
    requestId: string,
    decision: "approved" | "rejected",
    note?: string,
  ) => Promise<void>;
  reviewTask: (taskId: string, title: string, proposal: string) => Promise<void>;
  generateCompletion: () => Promise<void>;
}

export const useOffice = create<OfficeState>((set, get) => ({
  projectId: null,
  tab: "team",
  live: false,
  lastPolledAt: null,
  agents: [],
  tasks: [],
  hitl: [],
  events: [],
  traceability: null,
  completionBusy: false,
  reviewBusyTaskId: null,
  lastReview: null,
  notice: null,

  set: (partial) => set(partial),

  start: (projectId) => {
    get().stop();
    set({ projectId, live: true, notice: null });
    void get().poll();
  },

  stop: () => set({ live: false }),

  poll: async () => {
    const projectId = get().projectId;
    if (!projectId || !get().live) return;
    try {
      const [agents, tasks, hitl, events] = await Promise.all([
        api.listAgents(projectId),
        api.listTasks(projectId),
        api.listHitl(projectId, "pending"),
        api.listEvents(projectId),
      ]);
      set({ agents, tasks, hitl, events, lastPolledAt: new Date().toISOString() });
      // Traceability is heavier — refresh every other poll is unnecessary; it is
      // cheap enough at this cadence for the data volumes the UI shows.
      const traceability = await api.getTraceability(projectId);
      set({ traceability });
    } catch (err) {
      set({ notice: err instanceof Error ? err.message : String(err) });
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
    await get().poll();
  },

  reviewTask: async (taskId, title, proposal) => {
    set({ reviewBusyTaskId: taskId, notice: null });
    try {
      const outcome = await api.runReview(taskId, { title, proposal });
      set({ lastReview: outcome });
      await get().poll();
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
}));

export const runningAgents = (agents: AgentInfo[]): AgentInfo[] =>
  agents.filter((a) => a.state === "running" || a.state === "working");

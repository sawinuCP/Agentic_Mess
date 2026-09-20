// Unit tests for canonical agent states + roster ordering/filtering.
import { describe, expect, it } from "vitest";

import { activitySummary, agentAttention, agentStatus, filterRoster, sortRoster } from "./agentStates";
import type { AgentInfo, EventEntry, HitlRequestInfo, TaskInfo } from "../types";

const agent = (id: string, state: string, name = id): AgentInfo => ({
  id, project_id: "p", name, role: "worker", model: null, capabilities: [], state,
});

const task = (id: string, status: string, agentId: string | null = null): TaskInfo => ({
  id, project_id: "p", requirement_id: null, title: id, request: "", status,
  priority: 1, depends_on: [],
  attempts: agentId ? [{ attempt_number: 1, agent_id: agentId, outcome: null, failure_class: null, failure_detail: null, evidence_artifact_ids: [] }] : [],
});

const hitl = (id: string, taskId: string | null): HitlRequestInfo => ({
  id, task_id: taskId, kind: "k", question: "q", choices: [], risk: "high",
  status: "pending", created_at: new Date().toISOString(),
});

const event = (id: string, agentId: string, type: string): EventEntry => ({
  id, occurred_at: new Date().toISOString(), event_type: type, source: null,
  project_id: "p", task_id: null, agent_id: agentId, payload: {},
});

describe("agentStatus", () => {
  it("maps lifecycle states to canonical labels", () => {
    expect(agentStatus("running")).toMatchObject({ label: "Working", tone: "ok" });
    expect(agentStatus("pause_requested")).toMatchObject({ label: "Pausing" });
    expect(agentStatus("created")).toMatchObject({ label: "Starting", tone: "muted" });
    expect(agentStatus("failed")).toMatchObject({ label: "Failed", tone: "down" });
  });

  it("passes unknown states through muted, never success", () => {
    expect(agentStatus("dreaming")).toMatchObject({ label: "dreaming", tone: "muted" });
  });
});

describe("agentAttention", () => {
  it("ranks failed above approval above blocked", () => {
    const tasks = [task("t1", "failed", "a"), task("t2", "blocked", "a")];
    expect(agentAttention("a", tasks, [hitl("h", "t1")], [])).toMatchObject({ kind: "failed" });
    expect(agentAttention("a", [task("t2", "blocked", "a")], [hitl("h", "t2")], [])).toMatchObject({ kind: "approval" });
    expect(agentAttention("a", [task("t2", "blocked", "a")], [], [])).toMatchObject({ kind: "blocked" });
    expect(agentAttention("a", [task("t3", "running", "a")], [], [])).toBeNull();
  });

  it("flags attributable failed tool runs", () => {
    const toolFail = (agentId: string | null, taskId: string | null): EventEntry => ({
      id: "e", occurred_at: new Date().toISOString(), event_type: "TOOL_RUN_COMPLETED",
      source: null, project_id: "p", task_id: taskId, agent_id: agentId, payload: { tool: "pytest", exit_code: 1 },
    });
    expect(agentAttention("a", [task("t", "running", "a")], [], [toolFail("a", null)]))
      .toMatchObject({ kind: "blocked" });
    expect(agentAttention("a", [task("t", "running", "a")], [], [toolFail(null, "t")]))
      .toMatchObject({ kind: "blocked" });
    expect(agentAttention("a", [task("t", "running", "a")], [], [toolFail(null, null)]))
      .toBeNull();
  });
});

describe("sortRoster", () => {
  it("orders attention first, then active, then the rest", () => {
    const agents = [agent("idle", "completed"), agent("work", "running"), agent("bad", "running")];
    const tasks = [task("t", "failed", "bad")];
    const sorted = sortRoster(agents, tasks, [], []).map((a) => a.id);
    expect(sorted).toEqual(["bad", "work", "idle"]);
  });
});

describe("filterRoster", () => {
  it("filters by state group and query", () => {
    const agents = [agent("a1", "running", "Backend"), agent("a2", "paused", "Tester")];
    const tasks = [task("t", "failed", "a1")];
    expect(filterRoster(agents, tasks, [], "attention", "")).toHaveLength(1);
    expect(filterRoster(agents, tasks, [], "working", "")).toHaveLength(1);
    expect(filterRoster(agents, tasks, [], "all", "test")).toHaveLength(1);
    expect(filterRoster(agents, tasks, [], "completed", "")).toHaveLength(0);
  });
});

describe("activitySummary", () => {
  it("summarizes the latest event, falls back to assignment", () => {
    expect(activitySummary("a", [task("t", "running", "a")], [event("e", "a", "TOOL_RUN_COMPLETED")]))
      .toContain("tool run completed");
    expect(activitySummary("a", [task("t", "running", "a")], [])).toBe("Assigned: t");
    expect(activitySummary("a", [], [])).toBeNull();
  });
});

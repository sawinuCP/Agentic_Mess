// Unit tests for the timeline model (pure logic, node environment).
import { describe, expect, it } from "vitest";

import type { EventEntry } from "../types";
import {
  eventCategory,
  foldReplay,
  mergeHistoryPages,
  normalizeEvent,
  relatedEvents,
  rosterMaps,
  sanitizePayload,
  searchTimeline,
  summarizeEvent,
  type TimelineEvent,
} from "./model";

function entry(overrides: Partial<EventEntry> = {}): EventEntry {
  return {
    id: "e1",
    occurred_at: "2026-09-18T10:00:00.000Z",
    event_type: "TASK_CREATED",
    source: "test",
    project_id: "p",
    task_id: "t1",
    agent_id: null,
    payload: { title: "Build auth" },
    project_seq: 7,
    ...overrides,
  };
}

const roster = rosterMaps(
  [{ id: "a1", project_id: "p", name: "Backend", role: "backend", model: null, capabilities: [], state: "running" }],
  [{ id: "t1", project_id: "p", requirement_id: "r1", title: "Build auth", request: "", status: "running", priority: 1, depends_on: [], attempts: [] }],
  [{ id: "r1", title: "Auth" }],
);

describe("eventCategory", () => {
  it("maps the real vocabulary, execution first", () => {
    expect(eventCategory("TASK_EXECUTION_STARTED")).toBe("execution");
    expect(eventCategory("TASK_SCHEDULED")).toBe("execution");
    expect(eventCategory("TASK_FAILED")).toBe("tasks");
    expect(eventCategory("AGENT_STATUS_CHANGED")).toBe("agents");
    expect(eventCategory("AGENT_REPLACED")).toBe("recovery");
    expect(eventCategory("RECOVERY_SELECTED")).toBe("recovery");
    expect(eventCategory("HITL_REQUESTED")).toBe("hitl");
    expect(eventCategory("TOOL_RUN_COMPLETED")).toBe("artifacts");
    expect(eventCategory("GIT_COMMIT")).toBe("artifacts");
    expect(eventCategory("REQUIREMENT_CREATED")).toBe("requirements");
    expect(eventCategory("LEASE_ACQUIRED")).toBe("system");
    expect(eventCategory("SOMETHING_NEW")).toBe("system");
  });
});

describe("summarizeEvent", () => {
  it("writes engineering sentences, never raw dumps", () => {
    expect(summarizeEvent(entry(), roster)).toBe("Task created: Build auth");
    expect(summarizeEvent(entry({ event_type: "TASK_FAILED", payload: { attempts: [{}, {}], outcome: "failed" } }), roster))
      .toBe("Task failed: Build auth after 2 attempts");
    expect(summarizeEvent(entry({ event_type: "AGENT_STATUS_CHANGED", agent_id: "a1", payload: { from: "running", to: "paused" } }), roster))
      .toBe("Backend: running → paused");
    expect(summarizeEvent(entry({ event_type: "TOOL_RUN_COMPLETED", payload: { tool: "pytest", exit_code: 1, duration_ms: 40, path: "tests/a.py" } }), roster))
      .toBe("pytest a.py — exit 1, 40ms");
    expect(summarizeEvent(entry({ event_type: "RECOVERY_SELECTED", payload: { action: "retry_if_safe", failure_class: "TOOL_FAILURE" } }), roster))
      .toBe("Recovery decision: retry_if_safe (TOOL_FAILURE)");
    expect(summarizeEvent(entry({ event_type: "TOTAL_MYSTERY", payload: {} }), roster)).toBe("TOTAL_MYSTERY");
  });
});

describe("normalizeEvent", () => {
  it("builds actors, resources, tones, and sanitized raw", () => {
    const n = normalizeEvent(
      entry({ event_type: "TOOL_RUN_COMPLETED", agent_id: "a1", payload: { tool: "test", exit_code: 0, path: "a.py", artifact_ids: ["art1"], api_token: "sekret" } }),
      roster,
    );
    expect(n.category).toBe("validation");
    expect(n.actor).toMatchObject({ type: "agent", label: "Backend (backend)" });
    expect(n.tone).toBe("ok");
    expect(n.resources.map((r) => r.type)).toContain("file");
    expect(n.evidenceRefs).toEqual(["art1"]);
    expect(n.raw).toMatchObject({ api_token: "[redacted]" });
    expect(n.correlationId).toBeNull();
  });

  it("keeps unknown types honest", () => {
    const n = normalizeEvent(entry({ event_type: "WILDCARD_X", task_id: null, agent_id: null, payload: {} }), roster);
    expect(n.category).toBe("system");
    expect(n.tone).toBe("muted");
    expect(n.actor.type).toBe("system");
  });
});

describe("sanitizePayload", () => {
  it("redacts secrets, truncates, caps depth and breadth", () => {
    expect(sanitizePayload({ api_key: "x", nested: { password: "y", ok: 1 } }))
      .toEqual({ api_key: "[redacted]", nested: { password: "[redacted]", ok: 1 } });
    expect(sanitizePayload({ Authorization: "Bearer z" })).toEqual({ Authorization: "[redacted]" });
    const long = sanitizePayload({ out: "x".repeat(600) }) as Record<string, string>;
    expect(long.out.endsWith("[truncated]")).toBe(true);
    expect(sanitizePayload({ a: { b: { c: { d: { e: { f: 1 } } } } } })).toEqual(
      { a: { b: { c: { d: { e: "[truncated: depth]" } } } } },
    );
    const wide = sanitizePayload(Array.from({ length: 25 }, (_, i) => i)) as unknown[];
    expect(wide).toHaveLength(21);
    expect(sanitizePayload(42)).toBe(42);
    expect(sanitizePayload(null)).toBeNull();
  });
});

describe("relatedEvents", () => {
  const base = (id: string, extra: Partial<EventEntry> = {}): TimelineEvent =>
    normalizeEvent(entry({ id, ...extra }), roster);

  it("chains real correlation ids and task scope, bounded", () => {
    const a = base("a", { correlation_id: "c1" } as Partial<EventEntry>);
    const b = base("b", { correlation_id: "c1", occurred_at: "2026-09-18T10:01:00Z" } as Partial<EventEntry>);
    const c = base("c", { correlation_id: "c2" } as Partial<EventEntry>);
    const rel = relatedEvents(a, [a, b, c]);
    expect(rel.byCorrelation.map((e) => e.id)).toEqual(["b"]);
    // Same task t1 links all three (task-scoped, labeled as such).
    expect(rel.byTask.map((e) => e.id).sort()).toEqual(["b", "c"]);
  });

  it("returns empty chains without links", () => {
    const solo = base("s", { task_id: null });
    expect(relatedEvents(solo, [solo])).toEqual({ byCorrelation: [], byTask: [] });
  });
});

describe("searchTimeline", () => {
  const names = { agents: new Map([["a1", "Backend"]]), tasks: new Map([["t1", "Build auth"]]) };
  const rows = [
    normalizeEvent(entry({ id: "a", event_type: "TASK_FAILED", agent_id: "a1", payload: { failure_class: "TOOL_FAILURE" } }), roster),
    normalizeEvent(entry({ id: "b", event_type: "GIT_COMMIT", task_id: null, agent_id: null, payload: { message: "fix login", paths: ["auth.py"] } }), roster),
  ];

  it("matches summaries, names, paths, and all tokens", () => {
    expect(searchTimeline(rows, "", names)).toHaveLength(2);
    expect(searchTimeline(rows, "failed", names).map((e) => e.id)).toEqual(["a"]);
    expect(searchTimeline(rows, "backend build", names).map((e) => e.id)).toEqual(["a"]);
    expect(searchTimeline(rows, "auth.py", names).map((e) => e.id)).toEqual(["b"]);
    expect(searchTimeline(rows, "zzz", names)).toEqual([]);
  });
});

describe("mergeHistoryPages", () => {
  it("dedupes by id preserving newest-first order", () => {
    const p1 = [entry({ id: "a" }), entry({ id: "b" })];
    const p2 = [entry({ id: "b" }), entry({ id: "c" })];
    expect(mergeHistoryPages(p1, p2).map((e) => e.id)).toEqual(["a", "b", "c"]);
  });
});

describe("foldReplay", () => {
  const asc = [
    entry({ id: "e1", event_type: "TASK_CREATED", task_id: "t9", payload: { title: "Fresh" }, project_seq: 1 }),
    entry({ id: "e2", event_type: "AGENT_CREATED", agent_id: "a9", payload: { role: "worker" }, project_seq: 2, task_id: null }),
    entry({ id: "e3", event_type: "AGENT_STATUS_CHANGED", agent_id: "a9", payload: { from: "created", to: "running" }, project_seq: 3, task_id: null }),
    entry({ id: "e4", event_type: "TASK_EXECUTION_STARTED", task_id: "t9", payload: {}, project_seq: 4 }),
    entry({ id: "e5", event_type: "TOOL_RUN_COMPLETED", payload: { tool: "test", exit_code: 1 }, project_seq: 5, task_id: null }),
    entry({ id: "e6", event_type: "TASK_FAILED", task_id: "t9", payload: {}, project_seq: 6 }),
    entry({ id: "e7", event_type: "RECOVERY_SELECTED", task_id: "t9", payload: { action: "retry_if_safe" }, project_seq: 7 }),
  ];

  it("reconstructs roster state step by step", () => {
    const s0 = foldReplay(asc, 0, roster);
    expect(s0.tasks).toEqual([]);
    expect(s0.applied).toBe(0);
    const s2 = foldReplay(asc, 2, roster);
    expect(s2.tasks.map((t) => [t.id, t.state])).toEqual([["t9", "pending"]]);
    expect(s2.agents.map((a) => [a.id, a.state])).toEqual([["a9", "created"]]);
    const s4 = foldReplay(asc, 4, roster);
    expect(s4.agents[0].state).toBe("running");
    expect(s4.tasks[0].state).toBe("running");
    expect(s4.counts).toMatchObject({ agentsRunning: 1, tasksRunning: 1 });
  });

  it("records milestones, tests, and failures without inventing attempts", () => {
    const full = foldReplay(asc, 99, roster);
    expect(full.applied).toBe(7);
    expect(full.tasks[0].state).toBe("failed");
    expect(full.recoveryMilestones.map((m) => m.type)).toEqual(["RECOVERY_SELECTED"]);
    expect(full.tests).toEqual({ passed: 0, failed: 1 });
    expect(full.asOf).toBe("2026-09-18T10:00:00.000Z");
  });

  it("clamps out-of-range steps", () => {
    expect(foldReplay(asc, -5, roster).applied).toBe(0);
    expect(foldReplay([], 10, roster).total).toBe(0);
  });
});

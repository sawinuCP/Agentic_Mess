// Unit tests for Agent Office derivation (pure logic, node environment).
import { describe, expect, it } from "vitest";

import type { EventEntry, TaskInfo } from "../types";
import {
  agentWaitingReason,
  bulkConfirm,
  bulkEligible,
  costAttribution,
  currentTaskForAgent,
  describeEvent,
  elapsedSince,
  eventCategory,
  formatDuration,
  formatTokens,
  groupTimeline,
  messageEndpoints,
  messageSummary,
  recoveryForTask,
  recoveryState,
  summarizeExecution,
  tasksForAgent,
  topEntries,
  validCosts,
  waitingReason,
  waitingSince,
} from "./selectors";
import type { CostsSummary } from "../types";

function task(overrides: Partial<TaskInfo> = {}): TaskInfo {
  return {
    id: "t1",
    project_id: "p",
    requirement_id: null,
    title: "Build auth",
    request: "do it",
    status: "pending",
    priority: 1,
    depends_on: [],
    attempts: [],
    ...overrides,
  };
}

function event(overrides: Partial<EventEntry> = {}): EventEntry {
  return {
    id: "e1",
    occurred_at: "2026-09-18T10:00:00.000Z",
    event_type: "AGENT_STATUS_CHANGED",
    source: null,
    project_id: "p",
    task_id: null,
    agent_id: "a1",
    payload: {},
    ...overrides,
  };
}

describe("agent ↔ task mapping", () => {
  const tasks = [
    task({ id: "t1", status: "completed", attempts: [{ attempt_number: 1, agent_id: "a1", outcome: "success", evidence_artifact_ids: [], failure_class: null, failure_detail: null }] }),
    task({ id: "t2", status: "running", attempts: [{ attempt_number: 2, agent_id: "a1", outcome: null, evidence_artifact_ids: [], failure_class: null, failure_detail: null }] }),
    task({ id: "t3", status: "pending", attempts: [] }),
  ];

  it("finds owned tasks newest-attempt first", () => {
    expect(tasksForAgent(tasks, "a1").map((t) => t.id)).toEqual(["t2", "t1"]);
    expect(tasksForAgent(tasks, "nobody")).toEqual([]);
  });

  it("prefers the live task as current work", () => {
    expect(currentTaskForAgent(tasks, "a1")?.id).toBe("t2");
    expect(currentTaskForAgent(tasks, "nobody")).toBeNull();
  });

  it("falls back to the newest owned task when all are terminal", () => {
    const done = [tasks[0]];
    expect(currentTaskForAgent(done, "a1")?.id).toBe("t1");
  });
});

describe("waiting reasons", () => {
  const dep = task({ id: "d1", title: "Migrations", status: "running" });
  const blocked = task({ id: "t9", title: "API", status: "blocked", depends_on: ["d1", "missing"] });

  it("names unresolved dependencies with live statuses", () => {
    expect(waitingReason(blocked, [blocked, dep])).toBe(
      "Waiting for Migrations (running), missing (unknown)",
    );
  });

  it("finds the recorded moment waiting started", () => {
    const wait = event({ id: "w", event_type: "DEPENDENCY_WAIT_STARTED", task_id: "t9", occurred_at: "2026-09-18T10:01:00Z" });
    const other = event({ id: "x", event_type: "TASK_SCHEDULED", task_id: "t9" });
    expect(waitingSince("t9", [other, wait])).toBe("2026-09-18T10:01:00Z");
    expect(waitingSince("t9", [other])).toBeNull();
  });

  it("formats durations and elapsed times honestly", () => {
    expect(formatDuration(45_000)).toBe("45s");
    expect(formatDuration(12 * 60_000)).toBe("12m");
    expect(formatDuration(3 * 3_600_000 + 4 * 60_000)).toBe("3h 4m");
    expect(elapsedSince(null)).toBeNull();
    expect(elapsedSince("not-a-date")).toBeNull();
    expect(elapsedSince("2026-09-18T10:00:00Z", Date.parse("2026-09-18T10:12:00Z"))).toBe("12m");
  });

  it("returns null when every dependency completed", () => {
    expect(waitingReason(task({ depends_on: [] }), [])).toBeNull();
    const done = task({ depends_on: ["d1"] });
    expect(waitingReason(done, [{ ...dep, status: "completed" }])).toBeNull();
  });

  it("only explains waiting/blocked agent states", () => {
    const all = [blocked, dep];
    expect(agentWaitingReason("x", "running", all)).toBeNull();
    expect(agentWaitingReason("x", "waiting", all)).toBe(
      "Waiting — no task recorded for this agent",
    );
  });
});

describe("recovery derivation", () => {
  const failed = task({
    id: "t5",
    status: "failed",
    attempts: [
      { attempt_number: 1, agent_id: "a1", outcome: "failed", evidence_artifact_ids: [], failure_class: "TOOL_FAILURE", failure_detail: "exit 1" },
      { attempt_number: 2, agent_id: "a2", outcome: "failed", evidence_artifact_ids: [], failure_class: "MODEL_FAILURE", failure_detail: null },
    ],
  });
  const events = [
    event({ id: "r1", event_type: "RECOVERY_SELECTED", task_id: "t5", occurred_at: "2026-09-18T10:01:00Z", payload: { action: "retry_if_safe", failure_class: "TOOL_FAILURE" } }),
    event({ id: "r2", event_type: "RETRY_STARTED", task_id: "t5", occurred_at: "2026-09-18T10:02:00Z", payload: {} }),
  ];

  it("chains attempts and recovery events oldest-first", () => {
    const steps = recoveryForTask(failed, events);
    expect(steps.map((s) => s.label)).toEqual([
      "Attempt 1 failed",
      "Attempt 2 failed",
      "Recovery decision: retry_if_safe",
      "Retry started",
    ]);
    expect(steps[0].detail).toContain("TOOL_FAILURE");
    expect(steps[0].tone).toBe("down");
  });

  it("is empty when nothing failed", () => {
    expect(recoveryForTask(task(), [])).toEqual([]);
  });

  it("verdicts recovered / still-failing / recovering", () => {
    expect(recoveryState(failed, events)?.label).toContain("still failing");
    expect(recoveryState(failed, [])?.label).toContain("no recovery recorded");
    expect(recoveryState({ ...failed, status: "completed" }, events)).toEqual({ label: "Recovered", tone: "ok" });
    expect(recoveryState({ ...failed, status: "running" }, events)?.label).toBe("Recovering");
    expect(recoveryState(task(), [])).toBeNull();
  });
});

describe("execution summary", () => {
  it("prioritizes failure over running", () => {
    const s = summarizeExecution(["running", "failed"], [
      task({ status: "running" }),
      task({ status: "failed" }),
    ]);
    expect(s).toMatchObject({ label: "Needs attention", tone: "down", running: 1, failed: 1 });
  });

  it("handles empty, waiting, and completed workspaces", () => {
    expect(summarizeExecution([], []).label).toBe("No tasks");
    expect(summarizeExecution(["waiting"], [task({ status: "blocked" })]).label).toBe("Waiting");
    expect(
      summarizeExecution([], [task({ status: "completed" }), task({ status: "cancelled" })]).label,
    ).toBe("Completed");
    expect(summarizeExecution(["running"], [task({ status: "running" })]).label).toBe("Running");
  });
});

describe("event description + grouping", () => {
  it("describes events in human sentences", () => {
    expect(describeEvent(event({ payload: { detail: "done" } }))).toBe(
      "agent status changed: done",
    );
    expect(describeEvent(event())).toBe("agent status changed");
  });

  it("merges bursts of the same type within 90s", () => {
    const burst = [
      event({ id: "e3", event_type: "AGENT_STARTED", occurred_at: "2026-09-18T10:00:40Z" }),
      event({ id: "e2", event_type: "AGENT_STARTED", occurred_at: "2026-09-18T10:00:10Z" }),
      event({ id: "e1", event_type: "TASK_COMPLETED", occurred_at: "2026-09-18T10:00:00Z" }),
    ];
    const groups = groupTimeline(burst);
    expect(groups).toHaveLength(2);
    expect(groups[0]).toMatchObject({ event_type: "AGENT_STARTED", count: 2 });
    expect(groups[1]).toMatchObject({ event_type: "TASK_COMPLETED", count: 1 });
  });

  it("splits the same type across the time window", () => {
    const spread = [
      event({ id: "e2", event_type: "AGENT_STARTED", occurred_at: "2026-09-18T10:05:00Z" }),
      event({ id: "e1", event_type: "AGENT_STARTED", occurred_at: "2026-09-18T10:00:00Z" }),
    ];
    expect(groupTimeline(spread)).toHaveLength(2);
  });

  it("categorizes event types for filters", () => {
    expect(eventCategory("AGENT_REPLACED")).toBe("recovery");
    expect(eventCategory("TOOL_RUN_COMPLETED")).toBe("tools");
    expect(eventCategory("REVIEW_FAILED_CLOSED")).toBe("tests");
    expect(eventCategory("HITL_REQUESTED")).toBe("hitl");
    expect(eventCategory("LEASE_ACQUIRED")).toBe("other");
  });
});

describe("bulk execution eligibility", () => {
  const running = task({ id: "r", status: "running" });
  const blocked = task({ id: "b", status: "blocked" });
  const failed = task({ id: "f", status: "failed" });
  const done = task({ id: "d", status: "completed" });
  const all = [running, blocked, failed, done];

  it("derives bulk sets from the same per-task availability builder", () => {
    // Pause/resume signal active durable workflows (running/blocked/ready);
    // there is no separate "paused" DB status — signals, not states.
    expect(bulkEligible(all, "pause").map((t) => t.id).sort()).toEqual(["b", "r"]);
    expect(bulkEligible(all, "resume").map((t) => t.id).sort()).toEqual(["b", "r"]);
    expect(bulkEligible(all, "cancel").map((t) => t.id).sort()).toEqual(["b", "r"]);
  });

  it("words confirmations honestly (signals vs recorded stops)", () => {
    expect(bulkConfirm("pause", 2)).toContain("acknowledgement is not a state change");
    expect(bulkConfirm("resume", 1)).toContain("checkpoints");
    expect(bulkConfirm("cancel", 3)).toContain("History is preserved");
  });
});

describe("cost attribution", () => {
  it("credits sole contributors and labels shared work", () => {
    const sole = task({ attempts: [{ attempt_number: 1, agent_id: "a1", outcome: "success", evidence_artifact_ids: [], failure_class: null, failure_detail: null }] });
    expect(costAttribution(sole, "a1")).toEqual({ sole: true, others: 0 });
    const shared = task({ attempts: [
      { attempt_number: 1, agent_id: "a1", outcome: "failed", evidence_artifact_ids: [], failure_class: "TOOL_FAILURE", failure_detail: null },
      { attempt_number: 2, agent_id: "a2", outcome: "success", evidence_artifact_ids: [], failure_class: null, failure_detail: null },
    ] });
    expect(costAttribution(shared, "a1")).toEqual({ sole: false, others: 1 });
    expect(costAttribution(task(), "a1")).toEqual({ sole: false, others: 0 });
  });
});

describe("costs + messages", () => {
  it("ranks breakdown entries and formats tokens", () => {
    expect(topEntries({ a: 1, b: 5, c: 3 }, 2)).toEqual([["b", 5], ["c", 3]]);
    expect(formatTokens(999)).toBe("999");
    expect(formatTokens(1500)).toBe("1.5k");
    expect(formatTokens(2_400_000)).toBe("2.4M");
  });

  it("rejects malformed ledger payloads instead of crashing", () => {
    const good = { invocations: 1, total_tokens: 10, by_model: {}, by_role: {}, task_id: null, budget_tokens_per_task: 5 };
    expect(validCosts(good)).toBe(true);
    expect(validCosts(null)).toBe(false);
    expect(validCosts(undefined)).toBe(false);
    expect(validCosts([] as unknown as CostsSummary)).toBe(false);
    expect(validCosts({ total_tokens: "10", by_role: {} } as unknown as CostsSummary)).toBe(false);
    expect(validCosts({ total_tokens: 10 } as unknown as CostsSummary)).toBe(false);
  });

  it("labels message endpoints honestly", () => {
    const names = (id: string | null): string => ({ a1: "Backend", a2: "Tester" })[id ?? ""] ?? (id ?? "?");
    const base = {
      id: "m", conversation_id: "c", task_id: "t", type: "request", payload: {},
      sender_agent_id: "a1", recipient_agent_id: "a2",
      payload_ref: null, priority: 5, correlation_id: null, reply_to: null,
      created_at: "", expires_at: null, delivered_at: null, delivery_attempts: 0,
    };
    expect(messageEndpoints({ ...base, sender_agent_id: "a1", recipient_agent_id: "a2" }, names)).toBe("Backend → Tester");
    expect(messageEndpoints({ ...base, sender_agent_id: null, recipient_agent_id: null }, names)).toBe("system → broadcast");
    expect(messageSummary({ ...base, payload: { summary: "All green" } })).toBe("All green");
    expect(messageSummary({ ...base, payload: {} })).toBe("empty payload");
  });
});

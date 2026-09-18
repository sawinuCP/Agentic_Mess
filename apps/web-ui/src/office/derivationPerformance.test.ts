// Derivation performance baseline (Wave 7): synthetic control-room load.
//
// 50 agents, 500 tasks with attempts, 5000 events — measures the pure
// selector layer (no React). See docs/agent-office-performance.md. The bound
// is generous on purpose: this guards against accidental quadratic blowups,
// not for frame-budget claims (no browser timing here).
import { describe, expect, it } from "vitest";

import type { EventEntry, TaskInfo } from "../types";
import {
  currentTaskForAgent,
  groupTimeline,
  recoveryForTask,
  summarizeExecution,
  tasksForAgent,
} from "./selectors";

const STATUSES = ["pending", "ready", "running", "blocked", "completed", "failed"];

function buildFixture(): { agentIds: string[]; tasks: TaskInfo[]; events: EventEntry[] } {
  const agentIds = Array.from({ length: 50 }, (_, i) => `agent-${i}`);
  const tasks: TaskInfo[] = Array.from({ length: 500 }, (_, i) => ({
    id: `task-${i}`,
    project_id: "p",
    requirement_id: null,
    title: `Task ${i}`,
    request: "",
    status: STATUSES[i % STATUSES.length],
    priority: i,
    depends_on: i > 0 ? [`task-${i - 1}`] : [],
    attempts: [
      {
        attempt_number: 1,
        agent_id: agentIds[i % agentIds.length],
        outcome: i % 6 === 5 ? "failed" : "success",
        failure_class: i % 6 === 5 ? "TOOL_FAILURE" : null,
        failure_detail: null,
        evidence_artifact_ids: [],
      },
    ],
  }));
  const types = ["AGENT_STATUS_CHANGED", "TASK_EXECUTION_STARTED", "TOOL_RUN_COMPLETED", "RECOVERY_SELECTED"];
  const events: EventEntry[] = Array.from({ length: 5000 }, (_, i) => ({
    id: `e${i}`,
    occurred_at: new Date(Date.UTC(2026, 8, 18, 10, 0, 0) + i * 1000).toISOString(),
    event_type: types[i % types.length],
    source: null,
    project_id: "p",
    task_id: `task-${i % 500}`,
    agent_id: agentIds[i % agentIds.length],
    payload: i % 4 === 3 ? { action: "retry_if_safe" } : {},
  }));
  return { agentIds, tasks, events };
}

describe("office derivation at control-room scale", () => {
  it("projects 50 agents / 500 tasks / 5000 events within budget", () => {
    const { agentIds, tasks, events } = buildFixture();
    const newestFirst = [...events].reverse();
    const started = Date.now();
    let owned = 0;
    for (const id of agentIds) {
      const mine = tasksForAgent(tasks, id);
      owned += mine.length;
      currentTaskForAgent(tasks, id);
    }
    const groups = groupTimeline(newestFirst.slice(0, 120));
    const chains = tasks.slice(0, 120).map((t) => recoveryForTask(t, newestFirst.slice(0, 120)));
    const summary = summarizeExecution(
      agentIds.map((_, i) => (i % 3 === 0 ? "running" : "waiting")),
      tasks,
    );
    const elapsedMs = Date.now() - started;
    console.log(JSON.stringify({
      benchmark: "wave7-derivation",
      agents: agentIds.length,
      tasks: tasks.length,
      events: events.length,
      ownedMappings: owned,
      groups: groups.length,
      tasksWithRecovery: chains.filter((c) => c.length > 0).length,
      summary: summary.label,
      elapsedMs,
    }));
    expect(owned).toBe(500);
    expect(summary.total).toBe(500);
    expect(elapsedMs).toBeLessThan(5000);
  });
});

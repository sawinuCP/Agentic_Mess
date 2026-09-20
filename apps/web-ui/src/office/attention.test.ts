// Unit tests for the attention collector (pure logic, node environment).
import { describe, expect, it } from "vitest";

import { collectAttention } from "./selectors";
import type { EventEntry, HitlRequestInfo, TaskInfo } from "../types";

const task = (id: string, status: string): TaskInfo => ({
  id, project_id: "p", requirement_id: null, title: id, request: "", status,
  priority: 1, depends_on: [], attempts: [],
});

const toolEvent = (id: string, exit: number | null, taskId: string | null): EventEntry => ({
  id, occurred_at: new Date().toISOString(), event_type: "TOOL_RUN_COMPLETED",
  source: null, project_id: "p", task_id: taskId, agent_id: "a",
  payload: { tool: "pytest", exit_code: exit },
});

const approval = (id: string, taskId: string | null): HitlRequestInfo => ({
  id, task_id: taskId, kind: "publish", question: "Ship it?", choices: [],
  risk: "high", status: "pending", created_at: new Date().toISOString(),
});

describe("collectAttention", () => {
  it("collects backend-side failures: failed tasks, failed tools, approvals", () => {
    const items = collectAttention(
      [toolEvent("e1", 1, "t1"), toolEvent("e2", 1, "t1"), toolEvent("e3", 0, "t1")],
      [task("t1", "running"), task("t2", "failed"), task("t3", "blocked")],
      [approval("h", "t1")],
    );
    const kinds = items.map((i) => i.kind);
    expect(kinds).toContain("task-failed");
    expect(kinds).toContain("task-blocked");
    expect(kinds).toContain("tool-failed");
    expect(kinds).toContain("approval");
    // latest tool failure per task only
    expect(items.filter((i) => i.kind === "tool-failed")).toHaveLength(1);
    // approvals first
    expect(items[0].kind).toBe("approval");
  });

  it("ignores successes and decided approvals", () => {
    const items = collectAttention(
      [toolEvent("e", 0, null)],
      [task("t", "completed")],
      [{ ...approval("h", null), status: "approved" }],
    );
    expect(items).toEqual([]);
  });
});

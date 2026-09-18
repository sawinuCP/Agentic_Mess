import { describe, expect, it, vi } from "vitest";
import type { TaskInfo } from "../types";
import { taskCommands } from "./taskCommands";
const task: TaskInfo = { id: "t", project_id: "p", requirement_id: null, title: "Implement", request: "",
  status: "pending", priority: 1, depends_on: [], attempts: [] };
describe("task commands", () => {
  it("exposes real actions and unique task-scoped IDs", async () => {
    const control = vi.fn().mockResolvedValue(undefined);
    const commands = taskCommands([task, { ...task, id: "other" }], control);
    expect(new Set(commands.map((c) => c.id)).size).toBe(8);
    await commands[0].run();
    expect(control).toHaveBeenCalledWith("t", "execute");
  });
  it("blocks unverified dependencies and terminal/retried tasks", () => {
    expect(taskCommands([{ ...task, depends_on: ["missing"] }], vi.fn())[0].disabledReason).toContain("dependencies");
    expect(taskCommands([{ ...task, status: "failed" }], vi.fn()).every((c) => c.disabledReason)).toBe(true);
  });
  it("offers both signals for active workflows without inventing paused task status", () => {
    const commands = taskCommands([{ ...task, status: "running" }], vi.fn());
    expect(commands[0].disabledReason).toBeTruthy();
    expect(commands[1].disabledReason).toBeUndefined();
    expect(commands[2].disabledReason).toBeUndefined();
  });
  it("offers cancellation for live tasks and blocks it for finished ones", async () => {
    const control = vi.fn().mockResolvedValue(undefined);
    const running = taskCommands([{ ...task, status: "running" }], control);
    const cancel = running.find((c) => c.id === "task.t.cancel");
    expect(cancel?.label).toContain("Cancel task");
    expect(cancel?.disabledReason).toBeUndefined();
    await cancel?.run();
    expect(control).toHaveBeenCalledWith("t", "cancel");
    for (const status of ["completed", "cancelled", "failed"]) {
      const finished = taskCommands([{ ...task, status }], vi.fn());
      expect(finished.find((c) => c.id === "task.t.cancel")?.disabledReason).toBe(
        "Task is already finished",
      );
    }
  });
});

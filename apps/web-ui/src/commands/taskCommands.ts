import type { TaskInfo } from "../types";
import type { Command } from "./registry";

export type TaskAction = "execute" | "pause" | "resume" | "cancel";
export function taskCommands(tasks: TaskInfo[], control: (id: string, action: TaskAction) => Promise<void>): Command[] {
  return tasks.flatMap((task) => {
    const active = ["running", "blocked", "ready"].includes(task.status);
    const startable = ["pending", "ready", "created"].includes(task.status) && task.attempts.length === 0;
    const dependenciesReady = task.depends_on.every((id) => tasks.some((other) => other.id === id && other.status === "completed"));
    // Cancellation is a terminal human intervention (FR-014): only live tasks.
    // Finished tasks keep their recorded outcome — cancelling them would
    // rewrite history rather than stop anything.
    const cancellable = !["completed", "cancelled", "failed"].includes(task.status);
    return (["execute", "pause", "resume", "cancel"] as const).map((action) => ({
      id: `task.${task.id}.${action}`,
      category: "Execution",
      label: `${action === "execute" ? "Start task execution" : action === "pause" ? "Request pause" : action === "resume" ? "Send resume signal" : "Cancel task"}: ${task.title}`,
      keywords: [task.id, task.status, "task", action, ...(action === "cancel" ? ["stop"] : [])],
      disabledReason: action === "execute"
        ? !startable ? "Only unattempted pending/ready tasks can start here"
          : !dependenciesReady ? "Waiting for verified completed dependencies" : undefined
        : action === "cancel"
          ? !cancellable ? "Task is already finished" : undefined
          : !active ? "Requires an active durable workflow" : undefined,
      run: () => control(task.id, action),
    }));
  });
}

import type { TaskInfo } from "../types";
import type { Command } from "./registry";

export type TaskAction = "execute" | "pause" | "resume";
export function taskCommands(tasks: TaskInfo[], control: (id: string, action: TaskAction) => Promise<void>): Command[] {
  return tasks.flatMap((task) => {
    const active = ["running", "blocked", "ready"].includes(task.status);
    const startable = ["pending", "ready", "created"].includes(task.status) && task.attempts.length === 0;
    const dependenciesReady = task.depends_on.every((id) => tasks.some((other) => other.id === id && other.status === "completed"));
    return (["execute", "pause", "resume"] as const).map((action) => ({
      id: `task.${task.id}.${action}`,
      category: "Execution",
      label: `${action === "execute" ? "Start task execution" : action === "pause" ? "Request pause" : "Send resume signal"}: ${task.title}`,
      keywords: [task.id, task.status, "task", action],
      disabledReason: action === "execute"
        ? !startable ? "Only unattempted pending/ready tasks can start here"
          : !dependenciesReady ? "Waiting for verified completed dependencies" : undefined
        : !active ? "Requires an active durable workflow" : undefined,
      run: () => control(task.id, action),
    }));
  });
}

// Team tab (Phase 9): live agents with morphing lifecycle states + task board.

import { useMemo, useRef, useState } from "react";
import { taskCommands, type TaskAction } from "../../commands/taskCommands";
import { errorMessage } from "../../api/errors";
import { glue } from "@typehug/en";
import { controlTask } from "../../api/client";
import { useOffice } from "../../state/officeStore";
import { StatusLabel } from "../shell/UiState";

const ACTION_LABELS: Record<TaskAction, string> = {
  execute: "Start execution", pause: "Request pause", resume: "Send resume signal",
};

export default function TeamTab() {
  const agents = useOffice((s) => s.agents);
  const tasks = useOffice((s) => s.tasks);
  const reviewBusyTaskId = useOffice((s) => s.reviewBusyTaskId);
  const reviewTask = useOffice((s) => s.reviewTask);
  const refresh = useOffice((s) => s.refresh);
  const [pending, setPending] = useState<string | null>(null);
  const inFlight = useRef(false);
  const [controlError, setControlError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  const available = useMemo(() => taskCommands(tasks, async () => undefined), [tasks]);

  const control = async (taskId: string, action: TaskAction) => {
    if (inFlight.current) return;
    const current = taskCommands(useOffice.getState().tasks, async () => undefined)
      .find((c) => c.id === `task.${taskId}.${action}`);
    if (!current || current.disabledReason) return;
    if (!window.confirm(action === "execute"
      ? "Start this task? This may run tools and use configured model providers."
      : `Send ${action} signal? The workflow applies it at a safe checkpoint.`)) return;
    inFlight.current = true;
    setPending(current.id);
    setControlError(null);
    setFeedback(null);
    try {
      await controlTask(taskId, action);
      setFeedback(action === "execute" ? "Execution request accepted. Refreshing task state."
        : `${action} signal sent. The workflow applies it at a safe checkpoint.`);
      await refresh();
    } catch (err) {
      setControlError(errorMessage(err));
    } finally {
      inFlight.current = false;
      setPending(null);
    }
  };

  return (
    <div className="stack">
      <section>
        <h4 className="office-section-title muted">{glue("Agents on duty")}</h4>
        {agents.length === 0 && (
          <div className="muted small pad-h">{glue("No agents yet — run a task to spawn one.")}</div>
        )}
        {agents.map((agent) => (
          <div key={agent.id} className="agent-card">
            <div className="row spread">
              <span className="strong">{agent.name}</span>
              <StatusLabel state={agent.state} />
            </div>
            <div className="small muted mono">
              {agent.role}
              {agent.model ? ` · ${agent.model}` : ""}
            </div>
          </div>
        ))}
      </section>

      <section>
        <h4 className="office-section-title muted">{glue("Task board")}</h4>
        {tasks.length === 0 && <div className="muted small pad-h">No tasks yet.</div>}
        {feedback && <p className="small" role="status">{feedback}</p>}
        {controlError && (
          <div className="error-text small" role="alert">
            {controlError}
          </div>
        )}
        {tasks.map((task) => {
          const hasEvidence = task.attempts.some(
            (a) => a.outcome === "success" && a.evidence_artifact_ids.length > 0,
          );
          const actions = available.filter((c) => c.id.startsWith(`task.${task.id}.`));
          return (
            <div key={task.id} className="task-row">
              <div className="row spread">
                <span className="task-title">{task.title}</span>
                <StatusLabel state={task.status} />
              </div>
              <div className="row spread small muted">
                <span>
                  {task.requirement_id ? "linked to requirement" : "no requirement link"}
                  {hasEvidence ? " · evidence recorded" : ""}
                </span>
                <span className="row">
                  {actions.map((command) => {
                    const action = command.id.split(".").at(-1) as TaskAction;
                    return <button key={command.id} className="btn btn-small"
                      title={command.disabledReason}
                      aria-label={`${ACTION_LABELS[action]}: ${task.title}`}
                      disabled={pending !== null || Boolean(command.disabledReason)}
                      onClick={() => void control(task.id, action)}>
                      {pending === command.id ? "Sending…" : ACTION_LABELS[action]}
                    </button>;
                  })}
                  <button
                    className="btn btn-small"
                    disabled={reviewBusyTaskId === task.id}
                    onClick={() =>
                      void reviewTask(task.id, task.title, `Review the implementation of: ${task.request ?? task.title}`)
                    }
                  >
                    {reviewBusyTaskId === task.id ? "reviewing…" : "request review"}
                  </button>
                </span>
              </div>
            </div>
          );
        })}
      </section>
    </div>
  );
}

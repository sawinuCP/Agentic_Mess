// Team tab (Phase 9): live agents with morphing lifecycle states + task board.

import { TextMorph } from "torph/react";
import { glue } from "@typehug/en";

import { useOffice } from "../../state/officeStore";

const STATE_CLASS: Record<string, string> = {
  running: "ok",
  working: "ok",
  completed: "ok",
  paused: "warn",
  failed: "down",
  lost: "down",
  created: "muted",
  pending: "muted",
};

export default function TeamTab() {
  const agents = useOffice((s) => s.agents);
  const tasks = useOffice((s) => s.tasks);
  const reviewBusyTaskId = useOffice((s) => s.reviewBusyTaskId);
  const reviewTask = useOffice((s) => s.reviewTask);

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
              <span className={`state-pill ${STATE_CLASS[agent.state] ?? "muted"}`}>
                <TextMorph>{agent.state}</TextMorph>
              </span>
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
        {tasks.map((task) => {
          const hasEvidence = task.attempts.some(
            (a) => a.outcome === "success" && a.evidence_artifact_ids.length > 0,
          );
          return (
            <div key={task.id} className="task-row">
              <div className="row spread">
                <span className="task-title">{task.title}</span>
                <span className={`state-pill ${STATE_CLASS[task.status] ?? "muted"}`}>
                  <TextMorph>{task.status}</TextMorph>
                </span>
              </div>
              <div className="row spread small muted">
                <span>
                  {task.requirement_id ? "linked to requirement" : "no requirement link"}
                  {hasEvidence ? " · evidence recorded" : ""}
                </span>
                <button
                  className="btn btn-small"
                  disabled={reviewBusyTaskId === task.id}
                  onClick={() =>
                    void reviewTask(task.id, task.title, `Review the implementation of: ${task.request ?? task.title}`)
                  }
                >
                  {reviewBusyTaskId === task.id ? "reviewing…" : "request review"}
                </button>
              </div>
            </div>
          );
        })}
      </section>
    </div>
  );
}

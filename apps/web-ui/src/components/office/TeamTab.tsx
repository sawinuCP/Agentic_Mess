// Team tab (Phase 9, Wave 7): live agents + task board as a control room.
//
// Agent cards show recorded status, current work, waiting reasons, last
// activity, and recovery state — all derived from durable state + the event
// stream (see office/selectors.ts). Selecting an agent opens the detail
// panel; selecting a task expands an inline inspector with recovery,
// dependencies, owners, and attempts. Controls reuse the existing task
// endpoints with availability reasons.

import { useMemo, useRef, useState } from "react";
import { taskCommands, type TaskAction } from "../../commands/taskCommands";
import { errorMessage } from "../../api/errors";
import { glue } from "@typehug/en";
import { cancelTask, controlTask } from "../../api/client";
import {
  agentWaitingReason,
  currentTaskForAgent,
  describeEvent,
  elapsedSince,
  lastAgentEvent,
  recoveryForTask,
  recoveryState,
  tasksForAgent,
  waitingReason,
  waitingSince,
} from "../../office/selectors";
import type { AgentInfo, EventEntry, TaskInfo } from "../../types";
import { useOffice } from "../../state/officeStore";
import { StatusLabel } from "../shell/UiState";

const ACTION_LABELS: Record<TaskAction, string> = {
  execute: "Start execution", pause: "Request pause", resume: "Send resume signal",
  cancel: "Cancel task",
};

function agentName(agents: AgentInfo[], id: string | null | undefined): string {
  if (!id) return "unassigned";
  return agents.find((a) => a.id === id)?.name ?? id.slice(0, 8);
}

function AgentCard({ agent, tasks, events }: {
  agent: AgentInfo; tasks: TaskInfo[]; events: EventEntry[];
}) {
  const setOffice = useOffice((s) => s.set);
  const current = currentTaskForAgent(tasks, agent.id);
  const waiting = agentWaitingReason(agent.id, agent.state, tasks);
  const last = lastAgentEvent(events, agent.id);
  const recovery = current ? recoveryState(current, events) : null;
  const ownedCount = tasksForAgent(tasks, agent.id).length;

  return (
    <div className="agent-card">
      <div className="row spread">
        <span className="strong">{agent.name}</span>
        <StatusLabel state={agent.state} />
      </div>
      <div className="small muted mono">
        {agent.role}
        {agent.model ? ` · ${agent.model}` : ""}
        {ownedCount > 0 ? ` · ${ownedCount} task${ownedCount === 1 ? "" : "s"}` : ""}
      </div>
      {current ? (
        <div className="small pad-h">
          ▸ {current.title} <span className="muted">({current.status.replaceAll("_", " ")})</span>
        </div>
      ) : (
        <div className="small muted pad-h">No task recorded for this agent</div>
      )}
      {waiting && (
        <div className="small warn pad-h" role="note">
          ⏳ {waiting}
        </div>
      )}
      {last && (
        <div className="small muted pad-h" title={new Date(last.occurred_at).toLocaleString()}>
          {describeEvent(last)}
        </div>
      )}
      <div className="row spread">
        {recovery ? (
          <span className={`state-pill tiny ${recovery.tone}`}>{recovery.label}</span>
        ) : (
          <span />
        )}
        <button
          className="btn btn-small"
          aria-label={`Inspect agent ${agent.name}`}
          title={agent.id}
          onClick={() => setOffice({ selectedAgentId: agent.id, selectedTaskId: null })}
        >
          Details
        </button>
      </div>
    </div>
  );
}

function TaskInspector({ task, allTasks, agents, events }: {
  task: TaskInfo; allTasks: TaskInfo[]; agents: AgentInfo[]; events: EventEntry[];
}) {
  const setOffice = useOffice((s) => s.set);
  const owners = [...new Set(task.attempts.map((a) => a.agent_id).filter(Boolean))] as string[];
  const deps = waitingReason(task, allTasks);
  const waitedMs = waitingSince(task.id, events);
  const steps = recoveryForTask(task, events);
  const evidence = [...new Set(task.attempts.flatMap((a) => a.evidence_artifact_ids))];

  return (
    <div className="task-inspector">
      {task.request && <p className="small">{task.request}</p>}
      <div className="small muted">
        priority {task.priority}
        {task.requirement_id ? (
          <>
            {" · "}
            <button
              className="link"
              title="Open requirement coverage"
              onClick={() => setOffice({ tab: "oversight" })}
            >
              linked to requirement
            </button>
          </>
        ) : (
          " · no requirement link"
        )}
      </div>
      {deps ? (
        <p className="small warn">
          ⏳ {deps}{waitedMs && elapsedSince(waitedMs) ? ` · waiting ${elapsedSince(waitedMs)}` : ""}
        </p>
      ) : (
        task.depends_on.length > 0 && <p className="small muted">Dependencies completed ✓</p>
      )}
      {task.depends_on.length > 0 && (
        <div className="row wrap gap4">
          <span className="small muted">Depends on:</span>
          {task.depends_on.map((id) => {
            const dep = allTasks.find((t) => t.id === id);
            return (
              <button
                key={id}
                className="btn btn-small"
                title={dep ? `${dep.title} (${dep.status})` : "Not in this project"}
                onClick={() => dep && setOffice({ selectedTaskId: dep.id })}
                disabled={!dep}
              >
                {dep ? dep.title : id.slice(0, 8)} · {dep?.status.replaceAll("_", " ")}
              </button>
            );
          })}
        </div>
      )}
      {owners.length > 0 && (
        <div className="row wrap gap4">
          <span className="small muted">Owner{owners.length === 1 ? "" : "s"}:</span>
          {owners.map((id) => (
            <button
              key={id}
              className="btn btn-small"
              onClick={() => setOffice({ selectedAgentId: id, selectedTaskId: null })}
            >
              {agentName(agents, id)}
            </button>
          ))}
        </div>
      )}
      {task.attempts.length > 0 && (
        <ul className="attempt-list small mono">
          {[...task.attempts]
            .sort((a, b) => a.attempt_number - b.attempt_number)
            .map((a) => (
              <li key={a.attempt_number}>
                #{a.attempt_number} {agentName(agents, a.agent_id)} · {a.outcome ?? "in progress"}
                {a.failure_class ? ` · ${a.failure_class}` : ""}
                {a.evidence_artifact_ids.length > 0 ? ` · ${a.evidence_artifact_ids.length} evidence` : ""}
              </li>
            ))}
        </ul>
      )}
      {steps.length > 0 && (
        <details className="small">
          <summary>Recovery ({steps.length})</summary>
          <ol className="recovery-chain">
            {steps.map((step, i) => (
              <li key={i} className={`recovery-step ${step.tone}`}>
                <span className="strong">{step.label}</span>
                {step.detail && <span className="muted"> — {step.detail}</span>}
              </li>
            ))}
          </ol>
        </details>
      )}
      {evidence.length > 0 && (
        <p className="small muted">Evidence artifacts: {evidence.length} recorded</p>
      )}
    </div>
  );
}

export default function TeamTab() {
  const agents = useOffice((s) => s.agents);
  const tasks = useOffice((s) => s.tasks);
  const events = useOffice((s) => s.events);
  const selectedTaskId = useOffice((s) => s.selectedTaskId);
  const setOffice = useOffice((s) => s.set);
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
      : action === "cancel"
        ? "Cancel this task? Its history is preserved and the status becomes cancelled."
        : `Send ${action} signal? The workflow applies it at a safe checkpoint.`)) return;
    inFlight.current = true;
    setPending(current.id);
    setControlError(null);
    setFeedback(null);
    try {
      if (action === "cancel") {
        await cancelTask(taskId);
      } else {
        await controlTask(taskId, action);
      }
      setFeedback(action === "execute" ? "Execution request accepted. Refreshing task state."
        : action === "cancel" ? "Cancellation recorded. Refreshing task state."
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
      <section aria-label="Agents">
        <h4 className="office-section-title muted">{glue("Agents on duty")}</h4>
        {agents.length === 0 && (
          <div className="muted small pad-h">{glue("No agents yet — run a task to spawn one.")}</div>
        )}
        {agents.map((agent) => (
          <AgentCard key={agent.id} agent={agent} tasks={tasks} events={events} />
        ))}
      </section>

      <section aria-label="Tasks">
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
          const recovery = recoveryState(task, events);
          const waiting = task.status === "blocked" ? waitingReason(task, tasks) : null;
          const waitedMs = task.status === "blocked" ? waitingSince(task.id, events) : null;
          const actions = available.filter((c) => c.id.startsWith(`task.${task.id}.`));
          const expanded = selectedTaskId === task.id;
          return (
            <div key={task.id} className="task-row">
              <div className="row spread">
                <button
                  className="link strong task-title"
                  aria-expanded={expanded}
                  aria-label={`${expanded ? "Collapse" : "Inspect"} task ${task.title}`}
                  onClick={() => setOffice({ selectedTaskId: expanded ? null : task.id })}
                >
                  {expanded ? "▾" : "▸"} {task.title}
                </button>
                <StatusLabel state={task.status} />
              </div>
              {waiting && (
                <div className="small warn pad-h">
                  ⏳ {waiting}{waitedMs && elapsedSince(waitedMs) ? ` · waiting ${elapsedSince(waitedMs)}` : ""}
                </div>
              )}
              {recovery && (
                <div className="pad-h">
                  <span className={`state-pill tiny ${recovery.tone}`}>{recovery.label}</span>
                </div>
              )}
              {expanded && (
                <TaskInspector task={task} allTasks={tasks} agents={agents} events={events} />
              )}
              <div className="row spread small muted">
                <span>
                  {task.requirement_id ? "linked to requirement" : "no requirement link"}
                  {hasEvidence ? " · evidence recorded" : ""}
                </span>
                <span className="row wrap">
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

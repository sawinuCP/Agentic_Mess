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
  elapsedSince,
  recoveryForTask,
  recoveryState,
  waitingReason,
  waitingSince,
} from "../../office/selectors";
import { filterRoster, sortRoster, type RosterFilter } from "../../office/agentStates";
import AgentRow from "../../office/AgentRow";
import OfficeAttention from "../../office/OfficeAttention";
import type { AgentInfo, EventEntry, TaskInfo } from "../../types";
import { useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";
import { confirmAction } from "../shell/confirm";
import { StatusLabel } from "../shell/UiState";
import DepMap from "./DepMap";
import NewTaskDialog from "./NewTaskDialog";
import SpawnAgentDialog from "./SpawnAgentDialog";

const ACTION_LABELS: Record<TaskAction, string> = {
  execute: "Start execution", pause: "Request pause", resume: "Send resume signal",
  cancel: "Cancel task", retry: "Retry task",
};

function agentName(agents: AgentInfo[], id: string | null | undefined): string {
  if (!id) return "unassigned";
  return agents.find((a) => a.id === id)?.name ?? id.slice(0, 8);
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
  const spawnOpen = useOffice((s) => s.spawnDialog);
  const createOpen = useOffice((s) => s.taskDialog);
  const hitl = useOffice((s) => s.hitl);
  const worktrees = useOffice((s) => s.worktrees);
  const available = useMemo(() => taskCommands(tasks, async () => undefined), [tasks]);

  // Roster: search + state filter over recorded state, attention-first order.
  const [rosterQuery, setRosterQuery] = useState("");
  const [rosterFilter, setRosterFilter] = useState<RosterFilter>("all");
  const roster = useMemo(
    () => sortRoster(filterRoster(agents, tasks, hitl, rosterFilter, rosterQuery, events), tasks, hitl, events),
    [agents, tasks, hitl, events, rosterFilter, rosterQuery],
  );
  const rosterRef = useRef<HTMLUListElement>(null);

  const moveRosterFocus = (direction: 1 | -1): void => {
    const buttons = Array.from(
      rosterRef.current?.querySelectorAll<HTMLButtonElement>(".agent-row-name") ?? [],
    );
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = buttons[(index + direction + buttons.length) % buttons.length];
    next?.focus();
  };

  const control = async (taskId: string, action: TaskAction) => {
    if (inFlight.current) return;
    const current = taskCommands(useOffice.getState().tasks, async () => undefined)
      .find((c) => c.id === `task.${taskId}.${action}`);
    if (!current || current.disabledReason) return;
    const confirmed = await confirmAction({
      title: `${ACTION_LABELS[action]}?`,
      body: action === "execute"
        ? "This may run tools and use configured model providers."
        : action === "cancel"
          ? "Its history is preserved and the status becomes cancelled."
          : action === "retry"
            ? "A new execution run starts; recorded attempts are preserved."
            : "The workflow applies it at a safe checkpoint.",
      confirmLabel: ACTION_LABELS[action],
      danger: action === "cancel",
    });
    if (!confirmed) return;
    inFlight.current = true;
    setPending(current.id);
    setControlError(null);
    setFeedback(null);
    try {
      if (action === "cancel") {
        await cancelTask(taskId);
      } else if (action === "retry") {
        await controlTask(taskId, "execute");
      } else {
        await controlTask(taskId, action);
      }
      setFeedback(action === "execute" ? "Execution request accepted. Refreshing task state."
        : action === "cancel" ? "Cancellation recorded. Refreshing task state."
        : action === "retry" ? "Retry dispatched. A new execution run starts; follow its recorded state in Office."
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
      <OfficeAttention />
      <section aria-label="Agents">
        <div className="row spread">
          <h4 className="office-section-title muted">{glue("Agents")}</h4>
          <button className="btn btn-small" onClick={() => setOffice({ spawnDialog: true, tab: "team" })}>
            New agent
          </button>
        </div>
        <div className="row wrap gap4">
          <input
            className="text-input small roster-search"
            aria-label="Search agents or tasks"
            placeholder="Search agents or tasks…"
            value={rosterQuery}
            onChange={(e) => setRosterQuery(e.target.value)}
          />
        </div>
        <div className="row wrap gap4" role="group" aria-label="Filter agents by state">
          {(["all", "working", "waiting", "attention", "failed", "completed"] as RosterFilter[]).map((filter) => (
            <button
              key={filter}
              className={`chip ${rosterFilter === filter ? "active" : ""}`}
              aria-pressed={rosterFilter === filter}
              onClick={() => setRosterFilter(filter)}
            >
              {filter === "attention" ? "Needs you" : filter[0].toUpperCase() + filter.slice(1)}
            </button>
          ))}
        </div>
        {agents.length === 0 && (
          <div className="muted small pad-h">
            {glue("No agents yet — run a task to spawn one.")}
            <div className="row gap4">
              <button className="btn btn-small" onClick={() => {
                setOffice({ tab: "team" });
                useStore.getState().set({ view: "command", sidebarOpen: true });
              }}>
                Open Command Center
              </button>
            </div>
          </div>
        )}
        {agents.length > 0 && roster.length === 0 && (
          <div className="muted small pad-h" role="status">No agents match this filter.</div>
        )}
        {roster.length > 0 && (
          <ul
            className="plain-list agent-roster"
            aria-label={`${roster.length} agents`}
            ref={rosterRef}
            onKeyDown={(e) => {
              if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
              e.preventDefault();
              moveRosterFocus(e.key === "ArrowDown" ? 1 : -1);
            }}
          >
            {roster.map((agent) => (
              <AgentRow key={agent.id} agent={agent} tasks={tasks} events={events} hitl={hitl} worktrees={worktrees} />
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Tasks">
        <div className="row spread">
          <h4 className="office-section-title muted">{glue("Task board")}</h4>
          <button className="btn btn-small" onClick={() => setOffice({ taskDialog: true, tab: "team" })}>
            New task
          </button>
        </div>
        {tasks.length > 1 && (
          <details className="small" open>
            <summary>Dependency map</summary>
            <DepMap tasks={tasks} />
          </details>
        )}
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
                  <button
                    className="btn btn-small"
                    title="Open the execution graph focused on this task"
                    aria-label={`Open graph: ${task.title}`}
                    onClick={() => {
                      setOffice({ selectedTaskId: task.id });
                      useStore.getState().set({ view: "graph", sidebarOpen: true });
                    }}
                  >
                    Graph
                  </button>
                </span>
              </div>
            </div>
          );
        })}
      </section>
      {spawnOpen && <SpawnAgentDialog onClose={() => setOffice({ spawnDialog: false })} />}
      {createOpen && <NewTaskDialog onClose={() => setOffice({ taskDialog: false })} />}
    </div>
  );
}

// Agent roster row (UI3): one scannable row per agent — who, role, state,
// current task, latest activity, worktree, attention. Keyboard: the row's
// Open button is a normal tab stop; the parent list adds ArrowUp/Down
// roving focus. No hover-only controls.

import { activitySummary, agentAttention, agentStatus } from "./agentStates";
import { bulkEligible, currentTaskForAgent, elapsedSince, firstAgentEvent, tasksForAgent } from "./selectors";
import { useBulkAction } from "./useBulkAction";
import type { AgentInfo, EventEntry, HitlRequestInfo, TaskInfo, WorktreeInfo } from "../types";
import { useOffice } from "../state/officeStore";

export default function AgentRow({ agent, tasks, events, hitl, worktrees }: {
  agent: AgentInfo;
  tasks: TaskInfo[];
  events: EventEntry[];
  hitl: HitlRequestInfo[];
  worktrees: WorktreeInfo[];
}) {
  const setOffice = useOffice((s) => s.set);
  const { runBulk, bulkBusy } = useBulkAction();
  const status = agentStatus(agent.state);
  const current = currentTaskForAgent(tasks, agent.id);
  const owned = tasksForAgent(tasks, agent.id);
  const ownedIds = new Set(owned.map((t) => t.id));
  const attention = agentAttention(agent.id, tasks, hitl);
  const activity = activitySummary(agent.id, tasks, events);
  const since = firstAgentEvent(events, agent.id);
  const branches = [...new Set(
    worktrees.filter((w) => w.task_id !== null && ownedIds.has(w.task_id)).map((w) => w.branch),
  )];
  const pauseEligible = bulkEligible(owned, "pause");
  const resumeEligible = bulkEligible(owned, "resume");

  const open = (): void => setOffice({ selectedAgentId: agent.id, selectedTaskId: null });
  const message = (): void => setOffice({ tab: "comms", commsRecipient: agent.id });

  return (
    <li className="agent-row" data-agent-id={agent.id} data-state={agent.state}>
      <div className="agent-row-main">
        <div className="row spread">
          <button className="link strong agent-row-name" onClick={open}
            aria-label={`Open agent ${agent.name}, ${status.label}`}>
            {agent.name}
          </button>
          <span className={`state-pill ${status.tone}`} title={`Agent state: ${agent.state}`}>
            <span aria-hidden="true">{status.glyph} </span>
            {status.label}
          </span>
        </div>
        <div className="small muted">
          {agent.role}{agent.model ? ` · ${agent.model}` : ""}
          {current ? <> · <button className="link" onClick={() => setOffice({ selectedTaskId: current.id, selectedAgentId: null, tab: "team" })}>{current.title}</button></> : " · no task recorded"}
        </div>
        {attention ? (
          <div className="small warn" role="note">⚠ {attention.detail}</div>
        ) : (
          activity && <div className="small muted truncate" title={activity}>{activity}</div>
        )}
        <div className="small muted row wrap gap4">
          {since && elapsedSince(since.occurred_at) && <span>active {elapsedSince(since.occurred_at)}</span>}
          {branches.length > 0 && <span className="mono" title={branches.join(", ")}>⎇ {branches[0]}{branches.length > 1 ? ` +${branches.length - 1}` : ""}</span>}
        </div>
      </div>
      <div className="agent-row-actions">
        {pauseEligible.length > 0 ? (
          <button className="btn btn-small" disabled={bulkBusy}
            title={`Pause: ${pauseEligible.slice(0, 3).map((t) => t.title).join(", ")}`}
            aria-label={`Pause ${agent.name}'s ${pauseEligible.length} running tasks`}
            onClick={() => void runBulk("pause", owned, `Agent ${agent.name}`)}>
            Pause
          </button>
        ) : resumeEligible.length > 0 ? (
          <button className="btn btn-small" disabled={bulkBusy}
            aria-label={`Resume ${agent.name}'s ${resumeEligible.length} paused tasks`}
            onClick={() => void runBulk("resume", owned, `Agent ${agent.name}`)}>
            Resume
          </button>
        ) : null}
        <button className="btn btn-small" title={`Message ${agent.name}`} onClick={message}>
          Message
        </button>
        <button className="btn btn-small" onClick={open}>Open</button>
      </div>
    </li>
  );
}

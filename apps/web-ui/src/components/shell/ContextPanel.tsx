// Contextual right panel, foundation (UI1): selection-driven inspector shell.
// Content in UI1 is summary-only, projected from existing store state (no new
// fetches). Per-object rich content lands in later phases. Empty selection
// shows the project overview (never a chatbot).

import { currentTaskForAgent, elapsedSince, firstAgentEvent, formatTokens, validCosts } from "../../office/selectors";
import { useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";
import { StatusLabel } from "../shell/UiState";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="ctx-row">
      <span className="ctx-label">{label}</span>
      <span className="ctx-value">{children}</span>
    </div>
  );
}

function AgentContext({ agentId }: { agentId: string }) {
  const agents = useOffice((s) => s.agents);
  const tasks = useOffice((s) => s.tasks);
  const events = useOffice((s) => s.events);
  const setOffice = useOffice((s) => s.set);
  const setFn = useStore((s) => s.set);
  const agent = agents.find((a) => a.id === agentId);
  if (!agent) return <p className="muted">Agent no longer recorded.</p>;
  const current = currentTaskForAgent(tasks, agent.id);
  const since = firstAgentEvent(events, agent.id);
  const openOffice = (): void => {
    setFn({ view: "office", sidebarOpen: true });
    setOffice({ tab: "team", selectedAgentId: agent.id });
  };
  return (
    <div className="stack">
      <div className="text-heading wrap-break">{agent.name}</div>
      <StatusLabel state={agent.state} />
      <Row label="Role">{agent.role}</Row>
      {agent.model && <Row label="Model"><span className="mono">{agent.model}</span></Row>}
      <Row label="Current task">{current ? current.title : "—"}</Row>
      <Row label="Active for">{since ? elapsedSince(since.occurred_at) : "—"}</Row>
      <div className="row">
        <button className="btn btn-small" onClick={openOffice}>Open in Agents</button>
      </div>
    </div>
  );
}

function TaskContext({ taskId }: { taskId: string }) {
  const tasks = useOffice((s) => s.tasks);
  const setOffice = useOffice((s) => s.set);
  const setFn = useStore((s) => s.set);
  const task = tasks.find((t) => t.id === taskId);
  if (!task) return <p className="muted">Task no longer recorded.</p>;
  const openOffice = (): void => {
    setFn({ view: "office", sidebarOpen: true });
    setOffice({ tab: "team", selectedTaskId: task.id, selectedAgentId: null });
  };
  return (
    <div className="stack">
      <div className="text-heading wrap-break">{task.title}</div>
      <StatusLabel state={task.status} />
      <Row label="Priority">{task.priority}</Row>
      <Row label="Requirement">{task.requirement_id ? <span className="mono">{task.requirement_id.slice(0, 8)}</span> : "—"}</Row>
      <Row label="Attempts">{task.attempts.length}</Row>
      <div className="row">
        <button className="btn btn-small" onClick={openOffice}>Open in Agents</button>
      </div>
    </div>
  );
}

function RequirementContext({ requirementId }: { requirementId: string }) {
  const traceability = useOffice((s) => s.traceability);
  const setOffice = useOffice((s) => s.set);
  const setFn = useStore((s) => s.set);
  const entry = traceability?.requirements.find((r) => r.id === requirementId);
  if (!entry) return <p className="muted">Requirement not in the latest traceability snapshot.</p>;
  return (
    <div className="stack">
      <div className="text-heading wrap-break">{entry.title}</div>
      <StatusLabel state={entry.status.toLowerCase()} />
      <Row label="Priority">{entry.priority}</Row>
      <Row label="Implemented">{entry.implemented ? "Yes" : "No"}</Row>
      <Row label="Tasks">{entry.task_ids.length}</Row>
      <div className="row">
        <button className="btn btn-small" onClick={() => {
          setFn({ view: "office", sidebarOpen: true });
          setOffice({ tab: "oversight" });
        }}>Open in Requirements</button>
      </div>
    </div>
  );
}

function ProjectOverview() {
  const project = useStore((s) => s.project);
  const setFn = useStore((s) => s.set);
  const agents = useOffice((s) => s.agents);
  const tasks = useOffice((s) => s.tasks);
  const hitl = useOffice((s) => s.hitl);
  const costs = useOffice((s) => s.costs);
  if (!project) return <p className="muted">Open a project to see workspace context.</p>;
  return (
    <div className="stack">
      <div className="text-heading wrap-break">{project.name}</div>
      <div className="text-caption wrap-break mono">{project.root_path}</div>
      <Row label="Agents">{agents.length}</Row>
      <Row label="Tasks">{tasks.length}</Row>
      <Row label="Approvals">{hitl.length}</Row>
      <Row label="Tokens">{validCosts(costs) ? <span className="numeric">{formatTokens(costs.total_tokens)}</span> : "—"}</Row>
      <div className="text-section">Suggested</div>
      <div className="stack">
        <button className="btn btn-small" onClick={() => setFn({ view: "command", sidebarOpen: true })}>New AI task</button>
        <button className="btn btn-small" onClick={() => setFn({ view: "office", sidebarOpen: true })}>Open Agents</button>
        <button className="btn btn-small" onClick={() => setFn({ view: "graph", sidebarOpen: true })}>Open Execution graph</button>
      </div>
    </div>
  );
}

export default function ContextPanel({ width, onWidth, onClose }: {
  width: number; onWidth: (width: number) => void; onClose: () => void;
}) {
  const agentId = useOffice((s) => s.selectedAgentId);
  const taskId = useOffice((s) => s.selectedTaskId);
  const requirementId = useOffice((s) => s.selectedRequirementId);
  const kind = agentId ? "Agent" : taskId ? "Task" : requirementId ? "Requirement" : "Workspace";

  return (
    <aside
      className="context-panel anim-enter"
      style={{ width }}
      aria-label={kind === "Workspace" ? "Workspace context" : `${kind} context`}
    >
      <div
        role="separator"
        tabIndex={0}
        aria-label="Resize context panel"
        aria-orientation="vertical"
        aria-valuemin={240}
        aria-valuemax={560}
        aria-valuenow={width}
        className="panel-resize resize-context"
        onPointerDown={(e) => {
          const startX = e.clientX;
          const startW = width;
          e.currentTarget.setPointerCapture(e.pointerId);
          e.preventDefault();
          const move = (ev: PointerEvent): void => {
            onWidth(Math.max(240, Math.min(560, Math.round(startW - (ev.clientX - startX)))));
          };
          const up = (): void => {
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", up);
          };
          window.addEventListener("pointermove", move);
          window.addEventListener("pointerup", up);
        }}
        onKeyDown={(e) => {
          if (e.key !== "ArrowLeft" && e.key !== "ArrowRight" && e.key !== "Home" && e.key !== "End") return;
          e.preventDefault();
          onWidth(e.key === "Home" ? 240 : e.key === "End" ? 560 : width + (e.key === "ArrowRight" ? 20 : -20));
        }}
      />
      <header className="context-header">
        <div>
          <div className="text-section">{kind} context</div>
        </div>
        <button className="tree-action" title="Close context panel" aria-label="Close context panel" onClick={onClose}>×</button>
      </header>
      <div className="context-body">
        {agentId ? <AgentContext agentId={agentId} />
          : taskId ? <TaskContext taskId={taskId} />
          : requirementId ? <RequirementContext requirementId={requirementId} />
          : <ProjectOverview />}
      </div>
    </aside>
  );
}

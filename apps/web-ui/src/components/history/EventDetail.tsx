// Event detail panel (Wave 9 §10): overview, context, related resources,
// evidence, correlation, and sanitized raw payload. Every jump reuses an
// existing surface (office, graph, editor, artifact metadata).

import { useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";
import type { AgentInfo, TaskInfo, TraceabilityRequirement } from "../../types";
import ArtifactMetaView from "../shared/ArtifactMeta";
import { relatedEvents, type TimelineEvent } from "../../timeline/model";

function Jump({ label, title, onJump }: { label: string; title: string; onJump: () => void }) {
  return (
    <button className="link small" title={title} onClick={onJump}>
      {label}
    </button>
  );
}

/** Evidence recorded on the task's attempts (current snapshot) — shown
 * alongside event-carried refs so task failures surface their proof. */
function TaskAttemptEvidence({ task }: { task: TaskInfo }) {
  const ids = [...new Set(task.attempts.flatMap((a) => a.evidence_artifact_ids))];
  if (ids.length === 0) return null;
  return (
    <>
      <div className="strong small">Task attempt evidence ({ids.length})</div>
      <div className="small stack">
        <span className="muted">Recorded on the task's attempts (current snapshot).</span>
        {ids.slice(0, 10).map((id) => (
          <ArtifactMetaView key={id} artifactId={id} />
        ))}
      </div>
    </>
  );
}

export default function EventDetail({ event, all, tasks, agents, requirements, onSelectEvent }: {
  event: TimelineEvent;
  all: TimelineEvent[];
  tasks: TaskInfo[];
  agents: AgentInfo[];
  requirements: TraceabilityRequirement[];
  onSelectEvent: (id: string) => void;
}) {
  const setWorkspace = useStore((s) => s.set);
  const openFile = useStore((s) => s.openFile);
  const setOffice = useOffice((s) => s.set);
  const hitl = useOffice((s) => s.hitl);
  const related = relatedEvents(event, all);
  const task = tasks.find((t) => t.id === event.taskId) ?? null;
  const agent = agents.find((a) => a.id === event.agentId) ?? null;
  const requirement = requirements.find((r) =>
    r.id === (task?.requirement_id ?? null),
  ) ?? null;
  const approvalId = typeof event.raw === "object" && event.raw !== null
    ? (event.raw as Record<string, unknown>).request_id
    : null;
  const approval = typeof approvalId === "string"
    ? hitl.find((h) => h.id === approvalId) ?? null
    : null;

  const openGraph = (partial: { rid?: string | null; tid?: string | null; aid?: string | null }): void => {
    setOffice({
      selectedRequirementId: partial.rid ?? null,
      selectedTaskId: partial.tid ?? null,
      selectedAgentId: partial.aid ?? null,
    });
    setWorkspace({ view: "graph", sidebarOpen: true });
  };

  return (
    <aside className="history-detail" aria-label="Event details">
      <div className="row spread">
        <span className={`state-pill ${event.tone}`}>{event.status.replaceAll("_", " ")}</span>
        <span className="small muted mono">{event.type}</span>
      </div>
      <div className="small muted">{new Date(event.timestamp).toLocaleString()}</div>
      <div>{event.summary}</div>

      <div className="strong small">Context</div>
      <div className="small stack">
        <span>Actor: {event.actor.label} <span className="muted">({event.actor.type})</span></span>
        {event.executionId && <span className="mono muted">execution {event.executionId.slice(0, 8)}</span>}
        {task && (
          <Jump label={`Task: ${task.title}`} title="Inspect the live task" onJump={() => {
            setOffice({ selectedTaskId: task.id, tab: "team" });
            setWorkspace({ view: "office", sidebarOpen: true });
          }} />
        )}
        {agent && (
          <Jump label={`Agent: ${agent.name}`} title="Inspect the live agent" onJump={() => {
            setOffice({ selectedAgentId: agent.id, selectedTaskId: null });
            setWorkspace({ view: "office", sidebarOpen: true });
          }} />
        )}
        {requirement && (
          <Jump label={`Requirement: ${requirement.title}`} title="Open live requirement graph" onJump={() => openGraph({ rid: requirement.id })} />
        )}
        {event.correlationId && (
          <span className="mono muted" title="Correlation ID">corr {event.correlationId.slice(0, 8)}</span>
        )}
      </div>

      {event.resources.length > 0 && (
        <>
          <div className="strong small">Related resources</div>
          <div className="small stack">
            {event.resources.filter((r) => r.type === "file").map((r) => (
              <button key={`f${r.id}`} className="link mono file-path" title={r.id} onClick={() => void openFile(r.id).catch(() => undefined)}>
                {r.label ?? r.id}
              </button>
            ))}
            {event.resources.filter((r) => r.type === "tool").map((r) => (
              <span key={`t${r.id}`} className="mono muted">tool {r.label ?? r.id}</span>
            ))}
          </div>
        </>
      )}

      {event.evidenceRefs.length > 0 && (
        <>
          <div className="strong small">Evidence ({event.evidenceRefs.length})</div>
          <div className="small stack">
            {event.evidenceRefs.slice(0, 10).map((id) => (
              <ArtifactMetaView key={id} artifactId={id} />
            ))}
            {event.evidenceRefs.length > 10 && (
              <span className="muted">+{event.evidenceRefs.length - 10} more (bounded display)</span>
            )}
          </div>
        </>
      )}

      {task && <TaskAttemptEvidence task={task} />}

      {approval && (
        <button
          className="btn btn-small"
          onClick={() => setWorkspace({ view: "office", sidebarOpen: true })}
        >
          Open approval: {approval.question.slice(0, 60)}
        </button>
      )}

      <div className="strong small">Correlation</div>
      {related.byCorrelation.length === 0 && related.byTask.length === 0 && (
        <span className="muted small">No related events in the loaded set.</span>
      )}
      {related.byCorrelation.length > 0 && (
        <div className="small stack">
          <span className="muted">Same correlation chain:</span>
          {related.byCorrelation.map((e) => (
            <Jump key={e.id} label={`${new Date(e.timestamp).toLocaleTimeString()} ${e.summary}`} title={e.type} onJump={() => onSelectEvent(e.id)} />
          ))}
        </div>
      )}
      {related.byTask.length > 0 && (
        <details className="small">
          <summary>Same task ({related.byTask.length})</summary>
          {related.byTask.map((e) => (
            <div key={e.id}>
              <Jump label={`${new Date(e.timestamp).toLocaleTimeString()} ${e.summary}`} title={e.type} onJump={() => onSelectEvent(e.id)} />
            </div>
          ))}
        </details>
      )}

      <details className="small">
        <summary>Raw payload (sanitized)</summary>
        <p className="muted">Secrets redacted, long values truncated. Large outputs stay in artifact storage.</p>
        <pre className="raw-payload mono">{JSON.stringify(event.raw, null, 2)}</pre>
      </details>
    </aside>
  );
}

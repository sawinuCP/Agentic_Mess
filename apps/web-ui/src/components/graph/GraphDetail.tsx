// Graph detail panel (Wave 8): contextual inspection per node type.
//
// Requirement nodes get the full §8 treatment (description, criteria with
// requirement-scope tasks/evidence labeled as such, coverage,
// implementation, validation, evidence with on-demand artifact metadata,
// and the overseer verdict with its reason). All other nodes stay compact
// with jumps into the Office, timeline, editor, and diff views — never
// duplicate viewers.

import { glue } from "@typehug/en";

import { errorMessage } from "../../api/errors";
import {
  failureTrace,
  type BuiltGraph,
  type GraphNode,
} from "../../graph/build";
import { recoveryState } from "../../office/selectors";
import { useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";
import type {
  AgentInfo,
  EventEntry,
  RequirementInfo,
  TaskInfo,
  TraceabilityReport,
} from "../../types";
import ArtifactMetaView from "../shared/ArtifactMeta";

function Jump({ label, title, onJump }: { label: string; title: string; onJump: () => void }) {
  return (
    <button className="link small" title={title} onClick={onJump}>
      {label}
    </button>
  );
}

const EvidenceMeta = ArtifactMetaView;

export default function GraphDetail({ node, graph, tasks, agents, events, rawRequirements, traceability, onSelect, onCenter }: {
  node: GraphNode | null;
  graph: BuiltGraph;
  tasks: TaskInfo[];
  agents: AgentInfo[];
  events: EventEntry[];
  rawRequirements: RequirementInfo[];
  traceability: TraceabilityReport;
  onSelect: (node: GraphNode | null) => void;
  onCenter: (id: string) => void;
}) {
  const setWorkspace = useStore((s) => s.set);
  const openFile = useStore((s) => s.openFile);
  const setOffice = useOffice((s) => s.set);
  if (!node) {
    return (
      <aside className="graph-detail muted small" aria-label="Node details">
        {glue("Select a node to inspect its details, evidence, and verification.")}
      </aside>
    );
  }

  const find = (id: string): GraphNode | null => graph.nodes.find((n) => n.id === id) ?? null;
  const outgoing = (type: string): GraphNode[] =>
    graph.edges.filter((e) => e.source === node.id && e.type === type)
      .map((e) => find(e.target)).filter((n): n is GraphNode => !!n);
  const incoming = (type: string): GraphNode[] =>
    graph.edges.filter((e) => e.target === node.id && e.type === type)
      .map((e) => find(e.source)).filter((n): n is GraphNode => !!n);
  const openInOffice = (partial: { selectedTaskId?: string | null; selectedAgentId?: string | null; selectedRequirementId?: string | null; tab?: "team" | "timeline" | "comms" | "oversight" }): void => {
    setOffice({ selectedTaskId: null, selectedAgentId: null, ...partial });
    setWorkspace({ view: "office", sidebarOpen: true });
  };
  const viewActivity = (agentId: string | null, taskId: string | null): void => {
    setOffice({ tab: "timeline", activityFilter: { agentId, taskId } });
    setWorkspace({ view: "office", sidebarOpen: true });
  };

  return (
    <aside className="graph-detail" aria-label={`${node.type} details`}>
      <div className="row spread">
        <span className={`state-pill ${node.tone}`}>{node.status.replaceAll("_", " ")}</span>
        <span className="small muted mono">{node.type}</span>
      </div>
      <div className="strong">{node.label}</div>
      <div className="row wrap gap4">
        <button className="btn btn-small" onClick={() => onCenter(node.id)}>Center</button>
        <button className="btn btn-small" onClick={() => onSelect(null)}>Clear</button>
      </div>
      {node.type === "requirement" && (
        <RequirementDetail
          node={node}
          tasks={tasks}
          rawRequirements={rawRequirements}
          outgoing={outgoing}
          onSelect={onSelect}
          openInOffice={openInOffice}
        />
      )}
      {node.type === "task" && (
        <TaskDetail node={node} tasks={tasks} agents={agents} traceability={traceability} graph={graph} outgoing={outgoing} incoming={incoming} events={events} onSelect={onSelect} openInOffice={openInOffice} viewActivity={viewActivity} />
      )}
      {node.type === "agent" && (
        <div className="stack small">
          <span className="muted">Role: {String(node.metadata.role ?? "—")}{node.metadata.model ? ` · ${String(node.metadata.model)}` : ""}</span>
          <Jump label="Inspect in Office" title="Open the agent detail panel" onJump={() => openInOffice({ selectedAgentId: node.agentId, tab: "team" })} />
          <Jump label="View activity" title="Open the timeline for this agent" onJump={() => viewActivity(node.agentId, null)} />
          <Jump label="Open in graph" title="Focus the graph on this agent" onJump={() => onSelect(node)} />
        </div>
      )}
      {node.type === "file" && (
        <div className="stack small">
          <span className="mono file-path" title={String(node.metadata.path ?? node.label)}>{String(node.metadata.path ?? node.label)}</span>
          <span className="muted">No task attribution exists server-side for touched files; files attach to the commits and test runs that recorded them.</span>
          <button
            className="btn btn-small"
            onClick={() => void openFile(String(node.metadata.path ?? node.label)).catch((err: unknown) => setWorkspace({ notice: errorMessage(err) }))}
          >
            Open in editor
          </button>
          {outgoing("verifies").length > 0 && <span className="muted">Referenced by evidence below.</span>}
          {incoming("changed").map((c) => (
            <Jump key={c.id} label={`Commit: ${c.label}`} title="Inspect the commit" onJump={() => onSelect(c)} />
          ))}
          {incoming("targeted").map((t) => (
            <Jump key={t.id} label={`Test run: ${t.label}`} title="Inspect the test run" onJump={() => onSelect(t)} />
          ))}
        </div>
      )}
      {node.type === "commit" && (
        <div className="stack small">
          <span className="muted">{new Date(String(node.metadata.occurredAt)).toLocaleString()}</span>
          <span>{String(node.metadata.message ?? node.label)}</span>
          {node.metadata.mergeBranch ? (
            <span className="muted">
              Integration merge of <span className="mono">{String(node.metadata.mergeBranch)}</span>
              {node.metadata.derivedTaskLink ? " — task link derived from the merge message" : ""}
            </span>
          ) : null}
          {asPaths(node.metadata.paths).map((p) => (
            <button key={p} className="link mono small file-path" title={p} onClick={() => void openFile(p).catch((err: unknown) => setWorkspace({ notice: errorMessage(err) }))}>
              {p}
            </button>
          ))}
        </div>
      )}
      {node.type === "test" && (
        <div className="stack small">
          <span>Tool <span className="mono">{String(node.metadata.tool)}</span> · exit {String(node.metadata.exitCode ?? "?")} · {String(node.metadata.durationMs ?? "?")}ms</span>
          <span className="muted">{new Date(String(node.metadata.occurredAt)).toLocaleString()}</span>
          <span className="muted">Project test activity is unattributed server-side; task links appear only where recorded.</span>
          {outgoing("produced").map((e) => (
            <Jump key={e.id} label={`Evidence: ${e.label}`} title="Inspect the evidence" onJump={() => onSelect(e)} />
          ))}
        </div>
      )}
      {node.type === "evidence" && (
        <div className="stack small">
          <span className="mono muted" title={String(node.metadata.artifactId)}>artifact {String(node.metadata.artifactId).slice(0, 8)}…</span>
          <EvidenceMeta artifactId={String(node.metadata.artifactId)} />
          {outgoing("verifies").map((r) => (
            <Jump key={r.id} label={`Verifies: ${r.label}`} title="Inspect the requirement" onJump={() => onSelect(r)} />
          ))}
        </div>
      )}
    </aside>
  );
}

function asPaths(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

function RequirementDetail({ node, tasks, rawRequirements, outgoing, onSelect, openInOffice }: {
  node: GraphNode;
  tasks: TaskInfo[];
  rawRequirements: RequirementInfo[];
  outgoing: (type: string) => GraphNode[];
  onSelect: (node: GraphNode | null) => void;
  openInOffice: (partial: { selectedTaskId?: string | null; selectedAgentId?: string | null; selectedRequirementId?: string | null; tab?: "team" | "timeline" | "comms" | "oversight" }) => void;
}) {
  const raw = rawRequirements.find((r) => r.id === node.requirementId);
  const criteria = (node.metadata.criteria ?? []) as { id: string; description: string; kind: string; mandatory: boolean; state: string }[];
  const linkedTasks = outgoing("planned for");
  const agentSet = new Map<string, GraphNode>();
  for (const t of linkedTasks) {
    for (const a of outgoing("executed by").filter((x) => x.agentId && tasks.find((task) => task.id === t.taskId)?.attempts.some((att) => att.agent_id === x.agentId))) {
      agentSet.set(a.id, a);
    }
  }
  return (
    <div className="stack small">
      {raw && (
        <>
          <p>{raw.description}</p>
          <span className="muted">
            Priority {raw.priority}{raw.desired_outcome ? ` · desired: ${raw.desired_outcome}` : ""}
          </span>
        </>
      )}
      <div className="strong">Acceptance criteria ({criteria.length})</div>
      {criteria.length === 0 && <span className="muted">No criteria recorded.</span>}
      {criteria.map((c) => (
        <details key={c.id}>
          <summary>
            <span className={`state-pill tiny ${c.state === "verified" ? "ok" : c.state === "failed" ? "down" : "warn"}`}>
              {c.state}
            </span>{" "}
            {c.description}
          </summary>
          <div className="muted">
            {c.kind}
            {c.mandatory ? " · mandatory" : " · optional"}
          </div>
          <div className="muted">
            Tasks and evidence are associated at requirement level — the
            backend records no criterion-level mapping, so none is invented here.
          </div>
        </details>
      ))}
      <div className="strong">Tasks ({linkedTasks.length})</div>
      {linkedTasks.map((t) => (
        <button key={t.id} className="link" onClick={() => onSelect(t)}>
          {t.label} ({t.status.replaceAll("_", " ")})
        </button>
      ))}
      <div className="strong">Agents ({agentSet.size})</div>
      {[...agentSet.values()].map((a) => (
        <button key={a.id} className="link" onClick={() => onSelect(a)}>
          {a.label} ({a.status.replaceAll("_", " ")})
        </button>
      ))}
      <div className="strong">Evidence</div>
      <RequirementEvidence requirementId={node.requirementId} tasks={tasks} />
      <div className="strong">Verification: {node.status}</div>
      <span className="muted">
        {node.status === "VERIFIED"
          ? "All mandatory criteria verified with tasks implemented — from the overseer, never from task completion alone."
          : node.status === "FAILED"
            ? "A mandatory criterion failed. See the failure path in the Tasks section."
            : "Incomplete evidence: task completion without validated criteria stays UNKNOWN."}
      </span>
      <Jump label="Open in Office oversight" title="Open requirement coverage" onJump={() => openInOffice({ selectedRequirementId: node.requirementId, tab: "oversight" })} />
    </div>
  );
}

function RequirementEvidence({ requirementId, tasks }: {
  requirementId: string | null;
  tasks: TaskInfo[];
}) {
  const owned = tasks.filter((t) => t.requirement_id === requirementId);
  const evidenceIds = [...new Set(owned.flatMap((t) => t.attempts.flatMap((a) => a.evidence_artifact_ids)))];
  if (evidenceIds.length === 0) {
    return <span className="muted">No evidence recorded for this requirement's tasks.</span>;
  }
  return (
    <span>
      {evidenceIds.length} artifact(s):{" "}
      <span className="mono muted">{evidenceIds.slice(0, 8).map((id) => id.slice(0, 8)).join(", ")}{evidenceIds.length > 8 ? "…" : ""}</span>
    </span>
  );
}

function TaskDetail({ node, tasks, agents, traceability, graph, outgoing, incoming, events, onSelect, openInOffice, viewActivity }: {
  node: GraphNode;
  tasks: TaskInfo[];
  agents: AgentInfo[];
  traceability: TraceabilityReport;
  graph: BuiltGraph;
  outgoing: (type: string) => GraphNode[];
  incoming: (type: string) => GraphNode[];
  events: EventEntry[];
  onSelect: (node: GraphNode | null) => void;
  openInOffice: (partial: { selectedTaskId?: string | null; selectedAgentId?: string | null; selectedRequirementId?: string | null; tab?: "team" | "timeline" | "comms" | "oversight" }) => void;
  viewActivity: (agentId: string | null, taskId: string | null) => void;
}) {
  const task = tasks.find((t) => t.id === node.taskId);
  const taskAgents = outgoing("executed by");
  const evidence = outgoing("evidence recorded");
  const deps = incoming("depends on");
  const blockedBy = outgoing("depends on");
  const commits = outgoing("integrated as");
  const recovery = task ? recoveryState(task, events) : null;
  return (
    <div className="stack small">
      {node.metadata.requirementLinked === false && (
        <span className="warn">Unlinked task — no requirement edge.</span>
      )}
      <span className="muted">
        Priority {String(node.metadata.priority ?? "?")} · {String(node.metadata.attemptCount ?? 0)} attempt(s)
        {typeof node.metadata.failureClasses === "object" && (node.metadata.failureClasses as string[]).length > 0
          ? ` · failures: ${(node.metadata.failureClasses as string[]).join(", ")}`
          : ""}
      </span>
      {node.metadata.worktreeBranch ? (
        <span className="mono muted" title="Isolated worktree branch">
          ⎇ {String(node.metadata.worktreeBranch)} ({String(node.metadata.worktreeStatus ?? "?")})
        </span>
      ) : null}
      {recovery && <span className={`state-pill tiny ${recovery.tone}`}>{recovery.label}</span>}
      {deps.length > 0 && (
        <span>
          Depended on by:{" "}
          {deps.map((d, i) => (
            <span key={d.id}>
              {i > 0 && ", "}
              <button className="link" onClick={() => onSelect(d)}>{d.label}</button>
            </span>
          ))}
        </span>
      )}
      {blockedBy.length > 0 && (
        <span>
          Depends on:{" "}
          {blockedBy.map((d, i) => (
            <span key={d.id}>
              {i > 0 && ", "}
              <button className="link" onClick={() => onSelect(d)}>{d.label}</button>
            </span>
          ))}
        </span>
      )}
      {taskAgents.length > 0 && (
        <span>
          Agents:{" "}
          {taskAgents.map((a, i) => (
            <span key={a.id}>
              {i > 0 && ", "}
              <button className="link" onClick={() => onSelect(a)}>{a.label}</button>
            </span>
          ))}
        </span>
      )}
      {commits.map((c) => (
        <Jump key={c.id} label={`Integrated as: ${c.label}`} title="Inspect the commit (derived link)" onJump={() => onSelect(c)} />
      ))}
      {evidence.length > 0 && (
        <span className="muted">{evidence.length} evidence artifact(s) — select below.</span>
      )}
      {evidence.map((e) => (
        <Jump key={e.id} label={`Evidence: ${e.label}`} title="Inspect the evidence" onJump={() => onSelect(e)} />
      ))}
      <div className="row wrap gap4">
        <button className="btn btn-small" onClick={() => openInOffice({ selectedTaskId: node.taskId, selectedRequirementId: node.requirementId, tab: "team" })}>
          Open in Office
        </button>
        <button className="btn btn-small" onClick={() => viewActivity(null, node.taskId)}>
          View activity
        </button>
      </div>
      {task && task.status === "failed" && (
        <FailurePath task={task} agents={agents} events={events} traceabilityRequirements={traceability.requirements} onSelect={onSelect} graph={graph} />
      )}
    </div>
  );
}

export function FailurePath({ task, agents, events, traceabilityRequirements, onSelect, graph }: {
  task: TaskInfo;
  agents: AgentInfo[];
  events: EventEntry[];
  traceabilityRequirements: TraceabilityReport["requirements"];
  onSelect: (node: GraphNode | null) => void;
  graph: BuiltGraph;
}) {
  const { steps, requirementBlocked } = failureTrace(task, agents, events, traceabilityRequirements);
  return (
    <div className="stack">
      <strong className="small">Failure path</strong>
      <ol className="recovery-chain small">
        {steps.map((step, i) => (
          <li key={i}>
            <button
              className="link"
              onClick={() => onSelect(graph.nodes.find((n) => n.id === step.nodeId) ?? null)}
            >
              {step.label}
            </button>
            {step.detail && <span className="muted small"> — {step.detail}</span>}
          </li>
        ))}
      </ol>
      <span className={`state-pill tiny ${requirementBlocked ? "down" : "ok"}`}>
        {requirementBlocked ? "Requirement still blocked" : "Requirement verified"}
      </span>
    </div>
  );
}

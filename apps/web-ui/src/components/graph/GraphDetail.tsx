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
  AUTHORITY_LABEL,
  failureTrace,
  type BuiltGraph,
  type GraphAuthority,
  type GraphNode,
} from "../../graph/build";
import { agentAttempts, agentToolRuns, attemptRows, evidenceCriteria, evidenceSources } from "../../graph/explain";
import { currentTaskForAgent, recoveryState, waitingReason } from "../../office/selectors";
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
import WhyPanel from "./WhyPanel";

function Jump({ label, title, onJump }: { label: string; title: string; onJump: () => void }) {
  return (
    <button className="link small" title={title} onClick={onJump}>
      {label}
    </button>
  );
}

/** Authority chip for relationship rows (§24: text label, never color alone). */
export function AuthorityTag({ authority, reason }: { authority: GraphAuthority; reason: string }) {
  return (
    <span className={`authority-tag authority-${authority}`} title={reason}>
      {AUTHORITY_LABEL[authority]}
    </span>
  );
}

const EvidenceMeta = ArtifactMetaView;

export default function GraphDetail({ node, graph, tasks, agents, events, rawRequirements, traceability, onSelect, onCenter, onInvestigate }: {
  node: GraphNode | null;
  graph: BuiltGraph;
  tasks: TaskInfo[];
  agents: AgentInfo[];
  events: EventEntry[];
  rawRequirements: RequirementInfo[];
  traceability: TraceabilityReport;
  onSelect: (node: GraphNode | null) => void;
  onCenter: (id: string) => void;
  onInvestigate: () => void;
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
  const openInOffice = (partial: { selectedTaskId?: string | null; selectedAgentId?: string | null; selectedRequirementId?: string | null; tab?: "team" | "timeline" | "comms" | "oversight"; commsRecipient?: string | null }): void => {
    setOffice({ selectedTaskId: null, selectedAgentId: null, ...partial });
    setWorkspace({ view: "office", sidebarOpen: true });
  };
  const followNode = (id: string): void => {
    const target = find(id);
    if (target) onSelect(target);
  };
  const viewActivity = (agentId: string | null, taskId: string | null): void => {
    setOffice({ tab: "timeline", activityFilter: { agentId, taskId } });
    setWorkspace({ view: "office", sidebarOpen: true });
  };
  const openRequirements = (requirementId: string | null): void => {
    if (!requirementId) return;
    setOffice({ selectedRequirementId: requirementId, selectedTaskId: null, selectedAgentId: null });
    setWorkspace({ view: "requirements" });
  };
  const openHistory = (): void => {
    setWorkspace({ view: "history" });
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
        <button
          className="btn btn-small"
          title="Scope the graph to this object and its causal neighborhood"
          onClick={onInvestigate}
        >
          Investigate
        </button>
      </div>
      {node.type === "requirement" && (
        <RequirementDetail
          node={node}
          tasks={tasks}
          agents={agents}
          rawRequirements={rawRequirements}
          traceability={traceability}
          outgoing={outgoing}
          onSelect={onSelect}
          onFollowNode={followNode}
          openInOffice={openInOffice}
          openRequirements={openRequirements}
          analyze={(title) => {
            setOffice({ selectedRequirementId: node.requirementId, selectedTaskId: null, selectedAgentId: null });
            setWorkspace({ view: "command", sidebarOpen: true, centerPrefill: `Analyze coverage for ${title}` });
          }}
        />
      )}
      {node.type === "task" && (
        <TaskDetail node={node} tasks={tasks} agents={agents} traceability={traceability} graph={graph} outgoing={outgoing} incoming={incoming} events={events} onSelect={onSelect} openInOffice={openInOffice} viewActivity={viewActivity} openRequirements={openRequirements} openHistory={openHistory} />
      )}
      {node.type === "agent" && (
        <AgentInvestigation
          node={node}
          tasks={tasks}
          events={events}
          graph={graph}
          onSelect={onSelect}
          openInOffice={openInOffice}
          viewActivity={viewActivity}
        />
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
            <span key={c.id}>
              <Jump label={`Commit: ${c.label}`} title="Inspect the commit" onJump={() => onSelect(c)} />{" "}
              <AuthorityTag authority="event-derived" reason="File path appeared in the commit's recorded event payload." />
            </span>
          ))}
          {incoming("targeted").map((t) => (
            <span key={t.id}>
              <Jump label={`Test run: ${t.label}`} title="Inspect the test run" onJump={() => onSelect(t)} />{" "}
              <AuthorityTag authority="event-derived" reason="File path appeared in the test run's recorded event payload." />
            </span>
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
            <span key={e.id}>
              <Jump label={`Evidence: ${e.label}`} title="Inspect the evidence" onJump={() => onSelect(e)} />{" "}
              <AuthorityTag authority="event-derived" reason="Artifact id appeared in the tool run's recorded event payload." />
            </span>
          ))}
        </div>
      )}
      {node.type === "evidence" && (
        <EvidenceInvestigation
          node={node}
          tasks={tasks}
          traceability={traceability}
          graph={graph}
          onSelect={onSelect}
        />
      )}
    </aside>
  );
}

function asPaths(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

/** Evidence backward chain (§15/F): attempts that recorded it, criteria that bound it. */
function EvidenceInvestigation({ node, tasks, traceability, graph, onSelect }: {
  node: GraphNode;
  tasks: TaskInfo[];
  traceability: TraceabilityReport;
  graph: BuiltGraph;
  onSelect: (node: GraphNode | null) => void;
}) {
  const artifactId = String(node.metadata.artifactId);
  const sources = evidenceSources(artifactId, tasks);
  const criteria = evidenceCriteria(artifactId, traceability.requirements);
  const find = (id: string): GraphNode | null => graph.nodes.find((n) => n.id === id) ?? null;
  return (
    <div className="stack small">
      <span className="mono muted" title={artifactId}>artifact {artifactId.slice(0, 8)}…</span>
      <EvidenceMeta artifactId={artifactId} />
      <span className="muted">Claim ≠ result ≠ evidence ≠ verification: this artifact is evidence only.</span>
      {sources.length > 0 ? (
        <span>
          Recorded by:{" "}
          {sources.map((s, i) => {
            const target = find(`task:${s.taskId}`);
            return (
              <span key={`${s.taskId}-${s.attemptNumber}`}>
                {i > 0 && ", "}
                {target ? (
                  <button
                    className="link"
                    title={`Attempt #${s.attemptNumber} on ${s.taskTitle} (${s.taskStatus})`}
                    onClick={() => onSelect(target)}
                  >
                    {s.taskTitle} #{s.attemptNumber}
                  </button>
                ) : (
                  `${s.taskTitle} #${s.attemptNumber}`
                )}
              </span>
            );
          })}{" "}
          <AuthorityTag authority="persisted" reason="Artifact id listed on durable attempt rows." />
        </span>
      ) : (
        <span className="muted">No recording attempt found in the loaded tasks — see Timeline for older events.</span>
      )}
      {criteria.map((c) => {
        const target = find(`req:${c.requirementId}`);
        return (
          <span key={`${c.requirementId}-${c.criterion}`}>
            Bound at verify time to criterion “{c.criterion}” (
            {target ? (
              <button className="link" title={`Inspect ${c.requirementTitle}`} onClick={() => onSelect(target)}>
                {c.requirementTitle}
              </button>
            ) : (
              c.requirementTitle
            )}
            {c.verifiedAt ? `, verified ${new Date(c.verifiedAt).toLocaleString()}` : ""}){" "}
            <AuthorityTag authority="persisted" reason="Validation row binds this artifact at verify time." />
          </span>
        );
      })}
      {criteria.length === 0 && (
        <span className="muted">Not bound to any verified criterion — recorded evidence, not verification.</span>
      )}
    </div>
  );
}

/** Agent causal investigation (§11): connections only, detail stays in the Office. */
function AgentInvestigation({ node, tasks, events, graph, onSelect, openInOffice, viewActivity }: {
  node: GraphNode;
  tasks: TaskInfo[];
  events: EventEntry[];
  graph: BuiltGraph;
  onSelect: (node: GraphNode | null) => void;
  openInOffice: (partial: { selectedTaskId?: string | null; selectedAgentId?: string | null; selectedRequirementId?: string | null; tab?: "team" | "timeline" | "comms" | "oversight"; commsRecipient?: string | null }) => void;
  viewActivity: (agentId: string | null, taskId: string | null) => void;
}) {
  const current = node.agentId ? currentTaskForAgent(tasks, node.agentId) : null;
  const attempts = node.agentId ? agentAttempts(tasks, node.agentId) : [];
  const runs = node.agentId ? agentToolRuns(events, node.agentId) : [];
  const failures = attempts.filter((a) => a.failure !== null);
  const recoveries = tasks
    .map((t) => ({ task: t, recovery: recoveryState(t, events) }))
    .filter((r) => r.recovery !== null && r.task.attempts.some((a) => a.agent_id === node.agentId));
  const taskNode = (id: string): GraphNode | null => graph.nodes.find((n) => n.id === `task:${id}`) ?? null;
  return (
    <div className="stack small">
      <span className="muted">
        Role: {String(node.metadata.role ?? "—")}{node.metadata.model ? ` · ${String(node.metadata.model)}` : ""} · state {node.status.replaceAll("_", " ")}
      </span>
      {current ? (
        <span>
          Current task:{" "}
          {taskNode(current.id) ? (
            <button className="link" title="Inspect the current task" onClick={() => onSelect(taskNode(current.id))}>{current.title}</button>
          ) : (
            current.title
          )}{" "}
          ({current.status.replaceAll("_", " ")}) <AuthorityTag authority="persisted" reason="Attempt rows record this agent on the task." />
        </span>
      ) : (
        <span className="muted">{attempts.length > 0 ? "No active task — past attempts below." : "No recorded attempts on any task."}</span>
      )}
      {attempts.length > 0 && (
        <span>
          Attempts ({attempts.length}):{" "}
          {attempts.slice(0, 8).map((a, i) => (
            <span key={`${a.taskId}-${a.attemptNumber}`}>
              {i > 0 && ", "}
              {taskNode(a.taskId) ? (
                <button className="link" title={`${a.taskTitle} — attempt #${a.attemptNumber} ${a.outcome}`} onClick={() => onSelect(taskNode(a.taskId))}>
                  {a.taskTitle} #{a.attemptNumber}
                </button>
              ) : (
                `${a.taskTitle} #${a.attemptNumber}`
              )}{" "}
              ({a.outcome}{a.failure ? ` · ${a.failure}` : ""})
            </span>
          ))}
          {attempts.length > 8 && <span className="muted"> +{attempts.length - 8} more</span>}
        </span>
      )}
      {failures.length > 0 && (
        <span className="muted">Failures: {failures.map((f) => `${f.taskTitle} #${f.attemptNumber} (${f.failure})`).join("; ")}</span>
      )}
      {recoveries.map(({ task, recovery }) => (
        <span key={task.id} className={`state-pill tiny ${recovery?.tone}`}>
          {task.title}: {recovery?.label}
        </span>
      ))}
      {runs.length > 0 && (
        <span className="muted">
          Tool runs: {runs.map((r) => `${r.tool}${r.path ? ` ${r.path.split("/").pop()}` : ""}${r.exitCode === null ? "" : ` (exit ${r.exitCode})`}`).join("; ")}
        </span>
      )}
      {runs.length === 0 && attempts.length > 0 && (
        <span className="muted">No tool runs recorded for this agent in the event feed.</span>
      )}
      <div className="row wrap gap4">
        <button className="btn btn-small" onClick={() => openInOffice({ selectedAgentId: node.agentId, tab: "team" })}>
          Inspect in Office
        </button>
        <button className="btn btn-small" onClick={() => viewActivity(node.agentId, null)}>
          View activity
        </button>
        <button className="btn btn-small" onClick={() => openInOffice({ tab: "comms", commsRecipient: node.agentId })}>
          Message
        </button>
      </div>
    </div>
  );
}

function RequirementDetail({ node, tasks, agents, rawRequirements, traceability, outgoing, onSelect, onFollowNode, openInOffice, openRequirements, analyze }: {
  node: GraphNode;
  tasks: TaskInfo[];
  agents: AgentInfo[];
  rawRequirements: RequirementInfo[];
  traceability: TraceabilityReport;
  outgoing: (type: string) => GraphNode[];
  onSelect: (node: GraphNode | null) => void;
  onFollowNode: (nodeId: string) => void;
  openInOffice: (partial: { selectedTaskId?: string | null; selectedAgentId?: string | null; selectedRequirementId?: string | null; tab?: "team" | "timeline" | "comms" | "oversight" }) => void;
  openRequirements: (requirementId: string | null) => void;
  analyze: (title: string) => void;
}) {
  const raw = rawRequirements.find((r) => r.id === node.requirementId);
  const entry = traceability.requirements.find((r) => r.id === node.requirementId) ?? null;
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
      <div className="strong">Tasks ({linkedTasks.length}) <AuthorityTag authority="persisted" reason="Task rows carry this requirement's id (durable foreign key)." /></div>
      {linkedTasks.map((t) => (
        <button key={t.id} className="link" onClick={() => onSelect(t)}>
          {t.label} ({t.status.replaceAll("_", " ")})
        </button>
      ))}
      <div className="strong">Agents ({agentSet.size}) <AuthorityTag authority="persisted" reason="Agents recorded on the tasks' durable attempt rows." /></div>
      {[...agentSet.values()].map((a) => (
        <button key={a.id} className="link" onClick={() => onSelect(a)}>
          {a.label} ({a.status.replaceAll("_", " ")})
        </button>
      ))}
      <div className="strong">Evidence</div>
      <RequirementEvidence requirementId={node.requirementId} tasks={tasks} />
      <div className="strong">Verification: {node.status}</div>
      {entry && <WhyPanel entry={entry} tasks={tasks} agents={agents} onFollowNode={onFollowNode} />}
      <span className="muted">
        {node.status === "VERIFIED"
          ? "All mandatory criteria verified with tasks implemented — from the overseer, never from task completion alone."
          : node.status === "FAILED"
            ? "A mandatory criterion failed. See the failure path in the Tasks section."
            : "Incomplete evidence: task completion without validated criteria stays UNKNOWN."}
      </span>
      <Jump label="Open in Office oversight" title="Open requirement coverage" onJump={() => openInOffice({ selectedRequirementId: node.requirementId, tab: "oversight" })} />
      <Jump label="Open in Requirements" title="Open the verification narrative" onJump={() => openRequirements(node.requirementId)} />
      <Jump
        label="Analyze in Command Center"
        title="Open the Command Center scoped to this requirement"
        onJump={() => analyze(node.label)}
      />
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

function TaskDetail({ node, tasks, agents, traceability, graph, outgoing, incoming, events, onSelect, openInOffice, viewActivity, openRequirements, openHistory }: {
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
  openRequirements: (requirementId: string | null) => void;
  openHistory: () => void;
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
      {task && (task.status === "blocked" || task.status === "waiting") && waitingReason(task, tasks) && (
        <span className="warn">{waitingReason(task, tasks)}</span>
      )}
      {task && task.attempts.length > 0 && (
        <>
          <div className="strong">Attempts ({task.attempts.length})</div>
          <span className="muted">
            Task: durable work unit · attempt: one durable try · execution: Temporal workflow run ·
            tool call: recorded event.
          </span>
          {attemptRows(task, agents).map((row) => {
            const agentNode = row.agentId ? graph.nodes.find((n) => n.id === `agent:${row.agentId}`) ?? null : null;
            return (
              <span key={row.attemptNumber}>
                Attempt #{row.attemptNumber} · {agentNode ? (
                  <button className="link" title={`Inspect ${row.agent}`} onClick={() => onSelect(agentNode)}>{row.agent}</button>
                ) : (
                  row.agent
                )} · {row.outcome}
                {row.failure ? ` · ${row.failure}` : ""}
                {row.evidenceCount > 0 ? ` · ${row.evidenceCount} evidence` : ""}
              </span>
            );
          })}
        </>
      )}
      {deps.length > 0 && (
        <span>
          Depended on by:{" "}
          {deps.map((d, i) => (
            <span key={d.id}>
              {i > 0 && ", "}
              <button className="link" onClick={() => onSelect(d)}>{d.label}</button>
            </span>
          ))}{" "}
          <AuthorityTag authority="persisted" reason="Dependency recorded in the task dependency table." />
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
          ))}{" "}
          <AuthorityTag authority="persisted" reason="Dependency recorded in the task dependency table." />
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
          ))}{" "}
          <AuthorityTag authority="persisted" reason="Agent recorded on the task's durable attempt rows." />
        </span>
      )}
      {commits.map((c) => (
        <span key={c.id}>
          <Jump label={`Integrated as: ${c.label}`} title="Inspect the commit (derived link)" onJump={() => onSelect(c)} />{" "}
          <AuthorityTag authority="inferred" reason="Commit association was derived from the recorded commit/worktree association (merge-message parse)." />
        </span>
      ))}
      {evidence.length > 0 && (
        <span className="muted">{evidence.length} evidence artifact(s) — select below.</span>
      )}
      {evidence.map((e) => (
        <span key={e.id}>
          <Jump label={`Evidence: ${e.label}`} title="Inspect the evidence" onJump={() => onSelect(e)} />{" "}
          <AuthorityTag authority="persisted" reason="Artifact id listed on the task's durable attempt rows." />
        </span>
      ))}
      <div className="row wrap gap4">
        <button className="btn btn-small" onClick={() => openInOffice({ selectedTaskId: node.taskId, selectedRequirementId: node.requirementId, tab: "team" })}>
          Open in Office
        </button>
        <button className="btn btn-small" onClick={() => viewActivity(null, node.taskId)}>
          View activity
        </button>
        <button className="btn btn-small" title="Open the full event history" onClick={openHistory}>
          Full history
        </button>
        {node.metadata.requirementLinked !== false && node.requirementId && (
          <button className="btn btn-small" title="Open the verification narrative" onClick={() => openRequirements(node.requirementId)}>
            View requirement
          </button>
        )}
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

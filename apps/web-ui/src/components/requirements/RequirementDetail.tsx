// Requirement detail (UI4): verification receipt first, then the full
// chain — criteria (with verify actions), tasks, agents, changes, tests,
// evidence, approvals. Every level navigates; nothing renders without
// recorded state behind it.

import { useState } from "react";

import type { RequirementInfo, TaskInfo, TraceabilityRequirement } from "../../types";
import { useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";
import ArtifactMetaView from "../shared/ArtifactMeta";
import ApprovalCard from "../office/ApprovalCard";
import { StatusLabel } from "../shell/UiState";
import {
  attemptSummary,
  evidenceCandidates,
  involvedAgents,
  touchedFiles,
  workState,
} from "../../requirements/requirementModel";
import VerificationReceipt from "./VerificationReceipt";
import VerifyCriterion from "./VerifyCriterion";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h4 className="office-section-title muted">{title}</h4>
      {children}
    </section>
  );
}

export default function RequirementDetail({ requirement, info }: {
  requirement: TraceabilityRequirement;
  info: RequirementInfo | undefined;
}) {
  const tasks = useOffice((s) => s.tasks);
  const agents = useOffice((s) => s.agents);
  const events = useOffice((s) => s.events);
  const setOffice = useOffice((s) => s.set);
  const setFn = useStore((s) => s.set);
  const openFile = useStore((s) => s.openFile);
  const [verifyFor, setVerifyFor] = useState<string | null>(null);

  const linked: TaskInfo[] = tasks.filter((t) => requirement.task_ids.includes(t.id));
  const work = workState(linked);
  const attempts = attemptSummary(linked);
  const people: { id: string; name: string; state: string }[] = involvedAgents(requirement, linked, agents);
  const files = touchedFiles(requirement, events);
  const evidence = evidenceCandidates(requirement, linked);
  const openTask = (taskId: string): void => {
    setOffice({ selectedTaskId: taskId, selectedAgentId: null, tab: "team" });
    setFn({ view: "office", sidebarOpen: true });
  };
  const openAgent = (agentId: string): void => {
    setOffice({ selectedAgentId: agentId, selectedTaskId: null });
    setFn({ view: "office", sidebarOpen: true });
  };
  const openGraph = (): void => {
    setOffice({ selectedRequirementId: requirement.id, selectedTaskId: null, selectedAgentId: null });
    setFn({ view: "graph", sidebarOpen: true });
  };

  return (
    <div className="stack req-detail">
      <div>
        <div className="text-heading wrap-break">{requirement.title}</div>
        {info && <p className="small muted wrap-break">{info.description}</p>}
        {info?.desired_outcome && (
          <p className="small">Outcome: <span className="muted">{info.desired_outcome}</span></p>
        )}
        <div className="small muted">
          Priority: {requirement.priority} · {linked.length} linked task{linked.length === 1 ? "" : "s"}
        </div>
      </div>

      <VerificationReceipt requirement={requirement} tasks={tasks} agents={agents} />

      <Section title="Acceptance criteria">
        {requirement.criteria.length === 0 && (
          <div className="muted small">No criteria recorded — nothing machine-checkable to verify against.</div>
        )}
        {requirement.criteria.map((criterion) => (
          <div key={criterion.id} className="criterion-block">
            <div className="row spread">
              <span className="small"><span className="strong">{criterion.description}</span></span>
              <StatusLabel state={criterion.state} />
            </div>
            <div className="small muted">
              {criterion.kind}{criterion.mandatory ? " · mandatory" : " · optional"}
            </div>
            {criterion.state !== "verified" && criterion.mandatory && (
              verifyFor === criterion.id ? (
                <VerifyCriterion
                  requirementId={requirement.id}
                  criterionId={criterion.id}
                  candidates={evidence}
                  taskId={linked[0]?.id ?? null}
                />
              ) : (
                <button className="btn btn-small" onClick={() => setVerifyFor(criterion.id)}>
                  Verify with evidence
                </button>
              )
            )}
          </div>
        ))}
      </Section>

      <Section title={`Work (${linked.length})`}>
        {linked.length === 0 && (
          <div className="muted small">No tasks linked yet — create tasks from this requirement to begin.</div>
        )}
        <div className="small muted">{work.label}</div>
        {linked.map((task) => {
          const owners = [...new Set(task.attempts.map((a) => a.agent_id).filter((id): id is string => !!id))];
          return (
            <div key={task.id} className="row spread small">
              <button className="link" onClick={() => openTask(task.id)}>{task.title}</button>
              <span className="muted">
                {task.status.replaceAll("_", " ")}
                {owners.length > 0 ? ` · ${owners.map((id) => agents.find((a) => a.id === id)?.name ?? id.slice(0, 8)).join(", ")}` : ""}
              </span>
            </div>
          );
        })}
      </Section>

      {people.length > 0 && (
        <Section title="Agents">
          {people.map((person) => (
            <div key={person.id} className="row spread small">
              <button className="link" onClick={() => openAgent(person.id)}>{person.name}</button>
              <span className="muted">{person.state.replaceAll("_", " ")}</span>
            </div>
          ))}
        </Section>
      )}

      {files.length > 0 && (
        <Section title={`Changes (${files.length} recorded files)`}>
          {files.map((path) => (
            <div key={path} className="row spread small mono">
              <span className="file-path">{path}</span>
              <button className="btn btn-small" onClick={() => void openFile(path).catch(() => undefined)}>
                Open
              </button>
            </div>
          ))}
          <button className="btn btn-small" onClick={openGraph}>View causal graph</button>
        </Section>
      )}

      <Section title="Tests">
        {attempts.total === 0 ? (
          <div className="muted small">No recorded validation tests on linked tasks.</div>
        ) : (
          <div className="small">
            {attempts.success} succeeded · {attempts.failed} failed · {attempts.total} attempts
          </div>
        )}
      </Section>

      {evidence.length > 0 && (
        <Section title={`Evidence (${evidence.length})`}>
          {evidence.slice(0, 8).map((candidate) => (
            <ArtifactMetaView key={candidate.artifactId} artifactId={candidate.artifactId} />
          ))}
          {evidence.length > 8 && <div className="muted small">+{evidence.length - 8} more</div>}
        </Section>
      )}

      <Section title="Approvals">
        <ApprovalCard taskIds={requirement.task_ids} />
      </Section>

      <div className="row wrap gap4">
        <button className="btn btn-small" onClick={openGraph}>View causal graph</button>
        <button
          className="btn btn-small"
          onClick={() => {
            setFn({ view: "command", sidebarOpen: true, centerPrefill: `Analyze coverage for ${requirement.title}` });
          }}
        >
          Analyze in Command Center
        </button>
      </div>
    </div>
  );
}

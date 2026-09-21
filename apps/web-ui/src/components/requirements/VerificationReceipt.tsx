// Verification receipt (UI4): durable engineering verification record in
// the CompletionReceipt visual language (no second system). Claim, test
// signal, evidence, verification, and approval stay visually distinct.
// Only recorded state renders — VERIFIED shows why, FAILED shows what,
// UNKNOWN shows what's missing.

import type { TraceabilityRequirement } from "../../types";
import {
  attemptSummary,
  evidenceCandidates,
  involvedAgents,
  missingForVerification,
  normalizeStatus,
  workState,
  type EvidenceCandidate,
} from "../../requirements/requirementModel";
import type { AgentInfo, TaskInfo } from "../../types";
import ArtifactMetaView from "../shared/ArtifactMeta";

const STATUS_TONE: Record<string, string> = {
  VERIFIED: "ok",
  FAILED: "down",
  UNKNOWN: "warn",
};

export function VerificationPill({ status }: { status: string }) {
  const normalized = normalizeStatus(status);
  return (
    <span className={`state-pill ${STATUS_TONE[normalized]}`} title="Backend verification state">
      <span aria-hidden="true">{normalized === "VERIFIED" ? "✓ " : normalized === "FAILED" ? "✗ " : "! "}</span>
      {normalized}
    </span>
  );
}

export default function VerificationReceipt({ requirement, tasks, agents }: {
  requirement: TraceabilityRequirement;
  tasks: TaskInfo[];
  agents: AgentInfo[];
}) {
  const status = normalizeStatus(requirement.status);
  const linked = tasks.filter((t) => requirement.task_ids.includes(t.id));
  const work = workState(linked);
  const attempts = attemptSummary(linked);
  const missing = missingForVerification(requirement, linked);
  const people = involvedAgents(requirement, linked, agents);
  const evidence: EvidenceCandidate[] = evidenceCandidates(requirement, linked);

  return (
    <div className="cc-receipt" aria-label={`Verification receipt: ${requirement.title}`}>
      <div className="row spread">
        <span className="text-section">Verification receipt</span>
        <VerificationPill status={requirement.status} />
      </div>
      {status === "VERIFIED" && (
        <div className="small stack">
          <span>All {requirement.criteria.filter((c) => c.mandatory).length} mandatory criteria verified with evidence.</span>
          <span className="muted">Work: {work.label} · Attempts: {attempts.success} succeeded / {attempts.total} total</span>
          {people.length > 0 && (
            <span className="muted">Agents: {people.map((p) => p.name).join(", ")}</span>
          )}
        </div>
      )}
      {status === "FAILED" && (
        <div className="small stack">
          {requirement.criteria.filter((c) => c.state === "failed").map((c) => (
            <span key={c.id}>✗ <span className="strong">{c.description}</span> <span className="muted">({c.kind})</span></span>
          ))}
          <span className="muted">Follow the failure backwards: criterion → task → agent → evidence.</span>
        </div>
      )}
      {status === "UNKNOWN" && (
        <div className="small stack">
          <span>The system cannot currently prove this requirement.</span>
          {missing.map((line) => (
            <span key={line} className="muted">· {line}</span>
          ))}
        </div>
      )}
      {evidence.length > 0 && (
        <div className="small stack">
          <span className="muted">Evidence ({evidence.length} recorded artifacts):</span>
          {evidence.slice(0, 6).map((c) => (
            <ArtifactMetaView key={c.artifactId} artifactId={c.artifactId} />
          ))}
          {evidence.length > 6 && <span className="muted small">+{evidence.length - 6} more</span>}
        </div>
      )}
    </div>
  );
}

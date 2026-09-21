// Why-panel (UI-5 §8): deterministic "why" chains for a requirement.
// Verification language is historical ("recorded verification point") —
// never current-validity (§16). Every line names its record.

import { whyRequirement } from "../../graph/explain";
import type {
  AgentInfo,
  TaskInfo,
  TraceabilityRequirement,
} from "../../types";

function Follow({ label, title, onFollow }: { label: string; title: string; onFollow: () => void }) {
  return (
    <button className="link" title={title} onClick={onFollow}>
      {label}
    </button>
  );
}

export default function WhyPanel({ entry, tasks, agents, onFollowNode }: {
  entry: TraceabilityRequirement;
  tasks: TaskInfo[];
  agents: AgentInfo[];
  onFollowNode: (nodeId: string) => void;
}) {
  const why = whyRequirement(entry, tasks, agents);
  return (
    <div className="stack small" aria-label={`Why ${why.verdict.toLowerCase()}`}>
      <span className="strong">Why {why.verdict}</span>
      {why.verdict === "VERIFIED" && (
        <>
          {why.chains.map((chain) => (
            <div key={chain.criterion} className="stack">
              <span>
                ✓ Criterion: {chain.criterion}
                {chain.verifiedAt ? ` — verified ${new Date(chain.verifiedAt).toLocaleString()}` : " — verification time not recorded"}
              </span>
              {chain.links.map((link, i) => (
                <span key={`${link.kind}-${i}`}>
                  ✓{" "}
                  {link.nodeId ? (
                    <Follow label={link.label} title={link.detail ?? link.kind} onFollow={() => onFollowNode(link.nodeId as string)} />
                  ) : (
                    link.label
                  )}
                  {link.detail && <span className="muted"> — {link.detail}</span>}
                </span>
              ))}
              {chain.provenance && (
                <span className="muted">
                  Verified at the recorded verification point
                  {chain.provenance.source_head_sha ? ` (source ${chain.provenance.source_head_sha.slice(0, 8)}${chain.provenance.source_branch ? ` on ${chain.provenance.source_branch}` : ""}${chain.provenance.source_dirty ? ", dirty tree" : ""})` : " (source binding not recorded)"}.
                  No invalidation model exists: later changes do not alter this record.
                </span>
              )}
            </div>
          ))}
          {why.chains.length === 0 && (
            <span className="muted">Verified by the overseer, but no criterion chains were recorded.</span>
          )}
        </>
      )}
      {why.verdict === "UNKNOWN" && (
        <>
          {why.missing.map((m) => (
            <span key={m}>• {m}</span>
          ))}
          <span className="muted">No supporting edges are manufactured: unverified criteria stay unlinked.</span>
        </>
      )}
      {why.verdict === "FAILED" && (
        <>
          {why.failedCriteria.map((c) => (
            <span key={c}>✗ Mandatory criterion failed: {c}</span>
          ))}
          {why.failedCriteria.length === 0 && (
            <span className="muted">Marked failed with no failed mandatory criterion recorded.</span>
          )}
          <span className="muted">Follow a failed task below for its failure path and recovery.</span>
        </>
      )}
    </div>
  );
}

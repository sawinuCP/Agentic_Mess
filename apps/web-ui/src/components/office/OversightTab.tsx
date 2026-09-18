// Oversight tab (Phase 9, FR-026/027): traceability, completion gate, review pipeline.

import { TextMorph } from "torph/react";
import { glue } from "@typehug/en";

import { useOffice } from "../../state/officeStore";

const STATE_CLASS: Record<string, string> = {
  VERIFIED: "ok",
  verified: "ok",
  FAILED: "down",
  failed: "down",
  UNKNOWN: "warn",
  unknown: "warn",
};

const VERDICT_CLASS: Record<string, string> = {
  approve: "ok",
  approved: "ok",
  reject: "down",
  changes_requested: "down",
  needs_evidence: "warn",
  error: "down",
};

const STAGES = ["reviewers", "critic", "evidence verifier", "adjudicator"];

export default function OversightTab() {
  const traceability = useOffice((s) => s.traceability);
  const completionBusy = useOffice((s) => s.completionBusy);
  const lastReview = useOffice((s) => s.lastReview);
  const generateCompletion = useOffice((s) => s.generateCompletion);

  if (!traceability) {
    return <div className="muted small pad-h">{glue("Waiting for oversight data…")}</div>;
  }

  const coverage = traceability.coverage;
  const allowed = traceability.completion_allowed;
  const requirements = traceability.requirements ?? [];

  return (
    <div className="stack">
      <section className="gate-card">
        <div className="row spread">
          <span className="strong">{glue("Completion gate")}</span>
          <span className={`state-pill ${allowed ? "ok" : "warn"}`}>
            <TextMorph>{allowed ? "allowed" : "blocked"}</TextMorph>
          </span>
        </div>
        {coverage ? (
          <div className="coverage-row">
            <span className="coverage-num ok">{coverage.verified}</span>
            <span className="muted">verified ·</span>
            <span className="coverage-num warn">{coverage.unknown}</span>
            <span className="muted">unknown ·</span>
            <span className="coverage-num down">{coverage.failed}</span>
            <span className="muted">failed · {coverage.total} total</span>
          </div>
        ) : (
          <div className="muted small">{glue("Coverage not reported yet.")}</div>
        )}
        {(traceability.blockers ?? []).map((blocker) => (
          <div key={blocker} className="gate-blocker">
            ⛔ {blocker}
          </div>
        ))}
        {(traceability.warnings ?? []).map((warning) => (
          <div key={warning} className="gate-warning">
            ⚠ {warning}
          </div>
        ))}
        <button className="btn wide" disabled={completionBusy} onClick={() => void generateCompletion()}>
          {completionBusy ? "generating…" : glue("Generate completion report")}
        </button>
        {traceability.artifact_id && (
          <div className="small muted">
            {glue("Report artifact")} <span className="mono">{traceability.artifact_id.slice(0, 8)}…</span>
          </div>
        )}
      </section>

      <section>
        <h4 className="office-section-title muted">{glue("Requirements traceability")}</h4>
        {requirements.length === 0 && (
          <div className="muted small">{glue("No requirements recorded.")}</div>
        )}
        {requirements.map((requirement) => (
          <div key={requirement.id} className="requirement-card">
            <div className="row spread">
              <span className="strong">{requirement.title}</span>
              <span className={`state-pill ${STATE_CLASS[requirement.status] ?? "muted"}`}>
                <TextMorph>{requirement.status}</TextMorph>
              </span>
            </div>
            {(requirement.criteria ?? []).map((criterion) => (
              <div key={criterion.id} className="criterion-row small">
                <span className={`state-pill tiny ${STATE_CLASS[criterion.state] ?? "muted"}`}>
                  {criterion.state}
                </span>
                <span className="criterion-text">
                  {criterion.description}
                  {criterion.mandatory ? "" : " (optional)"}
                </span>
              </div>
            ))}
          </div>
        ))}
      </section>

      {lastReview && (
        <section>
          <h4 className="office-section-title muted">{glue("Latest review pipeline")}</h4>
          <div className="pipeline">
            {STAGES.map((stage, index) => {
              const entries = lastReview.reviews.filter((review) =>
                stage === "reviewers" ? review.role.startsWith("reviewer") : review.role === stage.replace(" ", "_"),
              );
              const verdict = entries[0]?.verdict ?? "pending";
              return (
                <div key={stage} className="pipeline-stage">
                  <span className="pipeline-name muted small">{stage}</span>
                  <span className={`state-pill ${VERDICT_CLASS[verdict] ?? "muted"}`}>
                    <TextMorph>{verdict}</TextMorph>
                  </span>
                  {index < STAGES.length - 1 && <span className="pipeline-arrow muted">→</span>}
                </div>
              );
            })}
          </div>
          {lastReview.findings.map((finding, index) => (
            <div key={`${finding.reviewer}-${index}`} className="finding-row">
              <span className={`severity sev-${finding.severity}`}>{finding.severity}</span>
              <span>{finding.claim}</span>
            </div>
          ))}
          <div className="small muted">
            {glue("Decision")} <span className="mono">{lastReview.decision_id.slice(0, 8)}…</span>
          </div>
        </section>
      )}
    </div>
  );
}

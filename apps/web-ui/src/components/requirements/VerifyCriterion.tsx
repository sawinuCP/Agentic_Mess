// Per-criterion verification (UI4): record evidence-backed verification
// against the existing endpoint. Evidence candidates come from recorded
// task artifacts only — no invented evidence. Missing evidence is a 404
// surfaced honestly; the gate can never be satisfied by a claim alone.

import { useState } from "react";

import { verifyCriterion } from "../../api/client";
import { errorMessage } from "../../api/errors";
import type { EvidenceCandidate } from "../../requirements/requirementModel";
import { useOffice } from "../../state/officeStore";

export default function VerifyCriterion({ requirementId, criterionId, candidates, taskId }: {
  requirementId: string;
  criterionId: string;
  candidates: EvidenceCandidate[];
  taskId: string | null;
}) {
  const refresh = useOffice((s) => s.refresh);
  const [artifactId, setArtifactId] = useState(candidates[0]?.artifactId ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  if (candidates.length === 0) {
    return (
      <div className="small muted">
        No recorded evidence on linked tasks — run work that produces artifacts first.
      </div>
    );
  }

  const submit = async (): Promise<void> => {
    if (!artifactId || busy) return;
    setBusy(true);
    setError(null);
    try {
      await verifyCriterion(requirementId, criterionId, {
        evidence_artifact_id: artifactId,
        task_id: taskId,
      });
      setDone(true);
      await refresh().catch(() => undefined);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return <div className="small ok">Verified — recorded with evidence. Refreshing traceability…</div>;
  }

  return (
    <div className="stack">
      {error && <p className="error-text small" role="alert">{error}</p>}
      <label className="small row gap4">
        Evidence
        <select
          className="text-input small"
          aria-label="Evidence artifact for verification"
          value={artifactId}
          onChange={(e) => setArtifactId(e.target.value)}
        >
          {candidates.map((c) => (
            <option key={c.artifactId} value={c.artifactId}>
              {c.artifactId.slice(0, 8)}… · {c.taskTitle}
            </option>
          ))}
        </select>
      </label>
      <div>
        <button className="btn btn-small btn-primary" disabled={!artifactId || busy} onClick={() => void submit()}>
          {busy ? "Recording…" : "Verify with this evidence"}
        </button>
      </div>
    </div>
  );
}

// HITL approval card (Phase 9, spec §25): aicss-style decision card.
//
// Pending human-decision requests render as interactive approval cards with a
// risk badge, the question, optional choices and approve/reject with a note.

import { useRef, useState } from "react";
import { glue } from "@typehug/en";

import { useOffice } from "../../state/officeStore";
import { errorMessage } from "../../api/errors";

const RISK_CLASS: Record<string, string> = {
  high: "down",
  medium: "warn",
  low: "muted",
};

export default function ApprovalCard() {
  const hitl = useOffice((s) => s.hitl);
  const decideHitl = useOffice((s) => s.decideHitl);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const pending = useRef(new Set<string>());
  const [busy, setBusy] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const decide = async (id: string, decision: "approved" | "rejected") => {
    if (pending.current.has(id)) return;
    pending.current.add(id);
    setBusy([...pending.current]);
    setError(null);
    try { await decideHitl(id, decision, notes[id]); }
    catch (err) { setError(errorMessage(err)); }
    finally { pending.current.delete(id); setBusy([...pending.current]); }
  };

  if (hitl.length === 0) return null;

  return (
    <div className="stack">
      {error && <p className="error-text" role="alert">{error}</p>}
      {hitl.map((request) => (
        <div key={request.id} className="approval-card">
          <div className="row spread">
            <span className={`risk-badge ${RISK_CLASS[request.risk] ?? "muted"}`}>
              {glue(`${request.risk} risk`)}
            </span>
            <span className="small muted mono">{request.kind}</span>
          </div>
          <div className="approval-question strong">{request.question}</div>
          {request.choices.length > 0 && (
            <ul className="approval-choices small">
              {request.choices.map((choice) => (
                <li key={choice}>{choice}</li>
              ))}
            </ul>
          )}
          <input
            className="input small"
            placeholder="note (optional)"
            aria-label={`Approval note: ${request.question}`}
            value={notes[request.id] ?? ""}
            onChange={(event) =>
              setNotes((prev) => ({ ...prev, [request.id]: event.target.value }))
            }
          />
          <div className="row">
            <button
              className="btn approve"
              disabled={busy.includes(request.id)}
              onClick={() => void decide(request.id, "approved")}
            >
              Approve
            </button>
            <button
              className="btn reject"
              disabled={busy.includes(request.id)}
              onClick={() => void decide(request.id, "rejected")}
            >
              Reject
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

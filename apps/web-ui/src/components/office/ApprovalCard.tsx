// HITL approval card (Phase 9, spec §25): aicss-style decision card.
//
// Pending human-decision requests render as interactive approval cards with a
// risk badge, the question, optional choices and approve/reject with a note.

import { useState } from "react";
import { glue } from "@typehug/en";

import { useOffice } from "../../state/officeStore";

const RISK_CLASS: Record<string, string> = {
  high: "down",
  medium: "warn",
  low: "muted",
};

export default function ApprovalCard() {
  const hitl = useOffice((s) => s.hitl);
  const decideHitl = useOffice((s) => s.decideHitl);
  const [notes, setNotes] = useState<Record<string, string>>({});

  if (hitl.length === 0) return null;

  return (
    <div className="stack">
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
            value={notes[request.id] ?? ""}
            onChange={(event) =>
              setNotes((prev) => ({ ...prev, [request.id]: event.target.value }))
            }
          />
          <div className="row">
            <button
              className="btn approve"
              onClick={() => void decideHitl(request.id, "approved", notes[request.id])}
            >
              Approve
            </button>
            <button
              className="btn reject"
              onClick={() => void decideHitl(request.id, "rejected", notes[request.id])}
            >
              Reject
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

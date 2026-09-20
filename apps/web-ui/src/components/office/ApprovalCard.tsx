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

export default function ApprovalCard({ taskIds }: { taskIds?: string[] | null }) {
  const hitl = useOffice((s) => s.hitl);
  const tasks = useOffice((s) => s.tasks);
  const setOffice = useOffice((s) => s.set);
  const decideHitl = useOffice((s) => s.decideHitl);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const pending = useRef(new Set<string>());
  const [busy, setBusy] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const scoped = taskIds ? new Set(taskIds) : null;
  const requests = scoped ? hitl.filter((h) => h.task_id !== null && scoped.has(h.task_id)) : hitl;
  const decide = async (id: string, decision: "approved" | "rejected") => {
    if (pending.current.has(id)) return;
    pending.current.add(id);
    setBusy([...pending.current]);
    setError(null);
    try { await decideHitl(id, decision, notes[id]); }
    catch (err) { setError(errorMessage(err)); }
    finally { pending.current.delete(id); setBusy([...pending.current]); }
  };

  if (requests.length === 0) {
    return scoped ? (
      <div className="muted small">No pending approvals for this agent's tasks.</div>
    ) : null;
  }

  return (
    <div className="stack">
      {error && <p className="error-text" role="alert">{error}</p>}
      {requests.map((request) => (
        <div key={request.id} className="approval-card">
          <div className="row spread">
            <span className={`risk-badge ${RISK_CLASS[request.risk] ?? "muted"}`}>
              {glue(`${request.risk} risk`)}
            </span>
            <span className="small muted mono">{request.kind}</span>
          </div>
          <div className="approval-question strong">{request.question}</div>
          {request.task_id && (
            <button
              className="link small muted"
              title="Inspect the affected task"
              onClick={() => {
                setOffice({ selectedTaskId: request.task_id, tab: "team" });
              }}
            >
              for task: {tasks.find((t) => t.id === request.task_id)?.title ?? request.task_id.slice(0, 8)}
            </button>
          )}
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

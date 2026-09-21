// New requirement dialog (UI4): title, description, outcome, priority, and
// acceptance criteria, posted to the existing create endpoint. No invented
// fields — one criterion row per condition, kind + mandatory recorded.

import { useState } from "react";

import { createRequirement } from "../../api/client";
import { errorMessage } from "../../api/errors";
import { useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";
import { useDialogFocus } from "../shell/useDialogFocus";

interface DraftCriterion {
  description: string;
  kind: string;
  mandatory: boolean;
}

export default function NewRequirementDialog({ onClose }: { onClose: () => void }) {
  const project = useStore((s) => s.project);
  const refresh = useOffice((s) => s.refresh);
  const dialogRef = useDialogFocus(onClose);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [outcome, setOutcome] = useState("");
  const [priority, setPriority] = useState("must");
  const [criteria, setCriteria] = useState<DraftCriterion[]>([{ description: "", kind: "automated_test", mandatory: true }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const patch = (index: number, patch: Partial<DraftCriterion>): void => {
    setCriteria((prev) => prev.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  };

  const submit = async (): Promise<void> => {
    if (!project || !title.trim() || !description.trim() || busy) return;
    const rows = criteria.filter((c) => c.description.trim().length > 0);
    if (rows.length === 0) {
      setError("Add at least one acceptance criterion — verification needs something to check.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await createRequirement(project.id, {
        title: title.trim(),
        description: description.trim(),
        desired_outcome: outcome.trim() || null,
        priority,
        criteria: rows.map((c) => ({ description: c.description.trim(), kind: c.kind, mandatory: c.mandatory })),
      });
      await refresh().catch(() => undefined);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="overlay">
      <div ref={dialogRef} className="dialog anim-enter" role="dialog" aria-modal="true" aria-label="New requirement">
        <h2 className="text-heading">New requirement</h2>
        {error && <p className="error-text small" role="alert">{error}</p>}
        <div className="stack">
          <label className="small stack">
            Title
            <input className="text-input" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Payroll summary endpoint" />
          </label>
          <label className="small stack">
            Description
            <textarea className="text-input" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What must the system do?" />
          </label>
          <label className="small stack">
            Desired outcome (optional)
            <input className="text-input" value={outcome} onChange={(e) => setOutcome(e.target.value)} placeholder="Working endpoint with tests" />
          </label>
          <label className="small row gap4">
            Priority
            <select className="text-input small" aria-label="Requirement priority" value={priority} onChange={(e) => setPriority(e.target.value)}>
              <option value="must">must — blocks completion until verified</option>
              <option value="should">should</option>
              <option value="could">could</option>
            </select>
          </label>
          <div className="text-section">Acceptance criteria</div>
          {criteria.map((criterion, i) => (
            <div key={i} className="row wrap gap4">
              <input
                className="text-input small"
                aria-label={`Criterion ${i + 1} description`}
                placeholder="Condition to verify"
                value={criterion.description}
                onChange={(e) => patch(i, { description: e.target.value })}
              />
              <select
                className="text-input small"
                aria-label={`Criterion ${i + 1} kind`}
                value={criterion.kind}
                onChange={(e) => patch(i, { kind: e.target.value })}
              >
                <option value="automated_test">automated test</option>
                <option value="command">command</option>
                <option value="manual">manual</option>
              </select>
              <label className="small row gap4">
                <input
                  type="checkbox"
                  aria-label={`Criterion ${i + 1} mandatory`}
                  checked={criterion.mandatory}
                  onChange={(e) => patch(i, { mandatory: e.target.checked })}
                />
                mandatory
              </label>
            </div>
          ))}
          <div>
            <button className="btn btn-small" onClick={() => setCriteria((prev) => [...prev, { description: "", kind: "manual", mandatory: true }])}>
              Add criterion
            </button>
          </div>
        </div>
        <div className="row dialog-actions">
          <button className="btn btn-small" onClick={onClose}>Cancel</button>
          <button className="btn btn-small btn-primary" disabled={!title.trim() || !description.trim() || busy} onClick={() => void submit()}>
            {busy ? "Creating…" : "Create requirement"}
          </button>
        </div>
      </div>
    </div>
  );
}

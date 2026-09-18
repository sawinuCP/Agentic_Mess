// New-task dialog (Wave 7 completion): human task creation via the
// POST /api/projects/{id}/tasks endpoint. Links (requirement, dependencies)
// are validated server-side against the same project; the dialog surfaces
// those errors contextually. Created tasks start `pending` and appear after
// a resync.

import { useEffect, useState } from "react";
import { createTask, listRequirements } from "../../api/client";
import { errorMessage } from "../../api/errors";
import type { RequirementInfo } from "../../types";
import { useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";
import { useDialogFocus } from "../shell/useDialogFocus";

export default function NewTaskDialog({ onClose }: { onClose: () => void }) {
  const project = useStore((s) => s.project);
  const tasks = useOffice((s) => s.tasks);
  const refresh = useOffice((s) => s.refresh);
  const dialogRef = useDialogFocus(onClose);
  const [title, setTitle] = useState("");
  const [request, setRequest] = useState("");
  const [requirementId, setRequirementId] = useState("");
  const [requirements, setRequirements] = useState<RequirementInfo[]>([]);
  const [dependsOn, setDependsOn] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!project) return;
    let active = true;
    listRequirements(project.id)
      .then((rows) => { if (active) setRequirements(rows); })
      .catch(() => { if (active) setRequirements([]); });
    return () => { active = false; };
  }, [project]);

  const toggleDep = (id: string): void => {
    setDependsOn((prev) => (prev.includes(id) ? prev.filter((d) => d !== id) : [...prev, id]));
  };

  const submit = async (): Promise<void> => {
    if (!project || !title.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await createTask(project.id, {
        title: title.trim(),
        request: request.trim(),
        requirement_id: requirementId || null,
        depends_on: dependsOn,
      });
      await refresh();
      onClose();
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div
        className="dialog"
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Create task"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <h2>Create task</h2>
        <p className="muted small">
          Starts <span className="mono">pending</span>. Dependencies must be tasks of this
          project; the scheduler picks the task up when they complete.
        </p>
        {error && <p role="alert" className="error-text">{error}</p>}
        <label className="small stack">
          Title
          <input
            className="text-input"
            aria-label="Task title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
        </label>
        <label className="small stack">
          Request
          <textarea
            className="text-input"
            aria-label="Task request"
            rows={3}
            value={request}
            onChange={(e) => setRequest(e.target.value)}
          />
        </label>
        {requirements.length > 0 && (
          <label className="small stack">
            Requirement (optional)
            <select
              className="text-input"
              aria-label="Linked requirement"
              value={requirementId}
              onChange={(e) => setRequirementId(e.target.value)}
            >
              <option value="">none</option>
              {requirements.map((r) => (
                <option key={r.id} value={r.id}>{r.title}</option>
              ))}
            </select>
          </label>
        )}
        {tasks.length > 0 && (
          <fieldset className="small stack">
            <legend>Depends on</legend>
            {tasks
              .filter((t) => !["completed", "cancelled"].includes(t.status))
              .map((t) => (
                <label key={t.id} className="row gap4">
                  <input
                    type="checkbox"
                    checked={dependsOn.includes(t.id)}
                    onChange={() => toggleDep(t.id)}
                  />
                  {t.title} <span className="muted">({t.status.replaceAll("_", " ")})</span>
                </label>
              ))}
          </fieldset>
        )}
        <div className="dialog-actions">
          <button className="button" disabled={!title.trim() || busy} onClick={() => void submit()}>
            {busy ? "Creating…" : "Create task"}
          </button>
          <button className="button secondary" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

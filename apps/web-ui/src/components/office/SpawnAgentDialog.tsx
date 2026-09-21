// New-agent dialog (Wave 7 completion): creates a registry entry via the
// existing POST /api/projects/{id}/agents endpoint (verified side-effect
// free: pure insert, no session, nothing scheduled). The dialog says so
// plainly — agents do real work when tasks execute; a fresh entry waits in
// `created` until then.

import { useState } from "react";
import { createAgent } from "../../api/client";
import { errorMessage } from "../../api/errors";
import { useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";
import { useDialogFocus } from "../shell/useDialogFocus";

export default function SpawnAgentDialog({ onClose }: { onClose: () => void }) {
  const project = useStore((s) => s.project);
  const refresh = useOffice((s) => s.refresh);
  const dialogRef = useDialogFocus(onClose);
  const [name, setName] = useState("");
  const [role, setRole] = useState("worker");
  const [model, setModel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (): Promise<void> => {
    if (!project || !name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await createAgent(project.id, {
        name: name.trim(),
        role: role.trim() || "worker",
        model: model.trim() || null,
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
        aria-label="New agent"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <h2>New agent</h2>
        <p className="muted small">
          Creates a registry entry (state <span className="mono">created</span>). No session
          starts and nothing is scheduled — the agent does real work when a task executes.
        </p>
        {error && <p role="alert" className="error-text">{error}</p>}
        <label className="small stack">
          Name
          <input
            className="text-input"
            aria-label="Agent name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void submit(); }}
          />
        </label>
        <label className="small stack">
          Role
          <input
            className="text-input"
            aria-label="Agent role"
            value={role}
            onChange={(e) => setRole(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void submit(); }}
          />
        </label>
        <label className="small stack">
          Model (optional)
          <input
            className="text-input"
            aria-label="Agent model"
            placeholder="leave empty for project default"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void submit(); }}
          />
        </label>
        <div className="dialog-actions">
          <button className="button" disabled={!name.trim() || busy} onClick={() => void submit()}>
            {busy ? "Creating…" : "Create agent"}
          </button>
          <button className="button secondary" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import * as api from "../../api/client";
import type { ProjectInfo } from "../../types";
import { useStore } from "../../state/store";
import { useDialogFocus } from "./useDialogFocus";
import { errorMessage } from "../../api/errors";

export default function OpenProjectDialog({ onClose }: { onClose?: () => void }) {
  const openProject = useStore((s) => s.openProject);
  const [rootPath, setRootPath] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [projects, setProjects] = useState<ProjectInfo[]>([]);
  const dialogRef = useDialogFocus(busy ? undefined : onClose);

  useEffect(() => {
    api
      .listProjects()
      .then(setProjects)
      .catch(() => setProjects([]));
  }, []);

  const submit = async (path = rootPath) => {
    if (!path.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      await openProject(path.trim());
      onClose?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="overlay">
      <div className="dialog" ref={dialogRef} role="dialog" aria-modal="true" aria-label="Open project" tabIndex={-1}>
        <h2>Open project</h2>
        <p className="muted">Absolute path of a local project directory.</p>
        <input
          aria-label="Project directory"
          className="text-input"
          placeholder="e.g. C:\\dev\\my-project"
          value={rootPath}
          onChange={(e) => setRootPath(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void submit()}
        />
        {error && <p className="error-text">{error}</p>}
        <div className="dialog-actions">
          <button className="button" disabled={busy} onClick={() => void submit()}>
            {busy ? "Opening…" : "Open"}
          </button>
          {onClose && (
            <button className="button secondary" disabled={busy} onClick={onClose}>
              Cancel
            </button>
          )}
        </div>
        {projects.length > 0 && (
          <>
            <h3 className="dialog-sub">Previously opened</h3>
            <ul className="project-list">
              {projects.map((p) => (
                <li key={p.id}>
                  <button
                    className="link"
                    disabled={busy}
                    onClick={() => {
                      setRootPath(p.root_path);
                      void submit(p.root_path);
                    }}
                  >
                    {p.name} <span className="muted">— {p.root_path}</span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}

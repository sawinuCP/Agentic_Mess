import { useEffect, useState } from "react";
import * as api from "../api/client";
import type { GitCommit, GitStatusEntry } from "../types";
import { useStore } from "../state/store";

export default function GitView() {
  const project = useStore((s) => s.project);
  const git = useStore((s) => s.git);
  const refreshGit = useStore((s) => s.refreshGit);
  const openDiff = useStore((s) => s.openDiff);
  const [message, setMessage] = useState("");
  const [log, setLog] = useState<GitCommit[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const loadAll = async () => {
    if (!project) return;
    setError(null);
    try {
      await refreshGit();
      setLog(await api.gitLog(project.id, 20));
    } catch (err) {
      if (err instanceof api.ApiError && err.status === 409) {
        setLog([]);
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    }
  };

  useEffect(() => {
    void loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id]);

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      await loadAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  if (!project) {
    return <aside className="sidebar"><p className="muted pad">Open a project first.</p></aside>;
  }

  const entries = git?.entries ?? [];
  const staged = entries.filter((e) => e.index_status !== " " && e.index_status !== "?");
  const unstaged = entries.filter(
    (e) => e.worktree_status !== " " && !(e.index_status !== " " && e.index_status !== "?"),
  );
  const untracked = entries.filter((e) => e.index_status === "?" && e.worktree_status === "?");

  const Row = ({ entry, actions }: { entry: GitStatusEntry; actions: React.ReactNode }) => (
    <div className="tree-row file">
      <span className="git-status">{(entry.index_status + entry.worktree_status).trim()}</span>
      <button
        className="tree-name link"
        title="Open diff"
        onClick={() =>
          void act(async () => {
            const head = await api.gitFileAt(project.id, entry.path, "HEAD").catch(() => ({
              content: "",
            }));
            const work = await fetch(
              `/api/projects/${project.id}/file?path=${encodeURIComponent(entry.path)}`,
            ).then((r) => r.json() as Promise<{ content: string }>);
            openDiff(entry.path, head.content, work.content);
          })
        }
      >
        {entry.path}
      </button>
      <span className="tree-actions">{actions}</span>
    </div>
  );

  return (
    <aside className="sidebar">
      <header className="sidebar-header">SOURCE CONTROL {git?.branch ? `· ${git.branch}` : ""}</header>
      {error && <p className="error-text pad">{error}</p>}
      {git === null && !error && (
        <div className="pad">
          <p className="muted">This project has no git repository.</p>
          <button className="button" disabled={busy} onClick={() => void act(() => api.gitInit(project.id))}>
            Initialize Repository
          </button>
        </div>
      )}
      {git !== null && (
        <div className="pad stack">
          <textarea
            className="text-input commit-message"
            placeholder="Commit message"
            value={message}
            onChange={(e) => setMessage(e.target.value)}
          />
          <button
            className="button"
            disabled={busy || !message.trim() || staged.length === 0}
            onClick={() => void act(() => api.gitCommit(project.id, message).then(() => setMessage("")))}
          >
            Commit staged ({staged.length})
          </button>
        </div>
      )}
      {staged.length > 0 && <h3 className="git-section">Staged</h3>}
      {staged.map((entry) => (
        <Row
          key={entry.path}
          entry={entry}
          actions={
            <button className="tree-action" title="Unstage" onClick={() => void act(() => api.gitUnstage(project.id, [entry.path]))}>
              −
            </button>
          }
        />
      ))}
      {unstaged.length > 0 && <h3 className="git-section">Changes</h3>}
      {unstaged.map((entry) => (
        <Row
          key={entry.path}
          entry={entry}
          actions={
            <button className="tree-action" title="Stage" onClick={() => void act(() => api.gitStage(project.id, [entry.path]))}>
              ＋
            </button>
          }
        />
      ))}
      {untracked.length > 0 && <h3 className="git-section">Untracked</h3>}
      {untracked.map((entry) => (
        <Row
          key={entry.path}
          entry={entry}
          actions={
            <button className="tree-action" title="Stage" onClick={() => void act(() => api.gitStage(project.id, [entry.path]))}>
              ＋
            </button>
          }
        />
      ))}
      {log.length > 0 && <h3 className="git-section">History</h3>}
      {log.map((commit) => (
        <div key={commit.hash} className="tree-row file commit" title={commit.hash}>
          <span className="mono hash">{commit.hash.slice(0, 7)}</span>
          <span className="commit-msg">{commit.message}</span>
        </div>
      ))}
    </aside>
  );
}

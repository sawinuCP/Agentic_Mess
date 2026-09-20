import { useEffect, useState } from "react";
import { getLiveness, type Liveness } from "../../health";
import { useStore } from "../../state/store";

// Status bar (UI1): thin status line. Live telemetry (connection, agents,
// approvals, costs) moved to the top bar; this keeps dirty state, last tool
// run, languages, API version and diagnostics entry.

export default function StatusBar() {
  const project = useStore((s) => s.project);
  const toolchains = useStore((s) => s.toolchains);
  const git = useStore((s) => s.git);
  const setFn = useStore((s) => s.set);
  const [liveness, setLiveness] = useState<Liveness | null>(null);
  const [apiUp, setApiUp] = useState(false);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const l = await getLiveness();
        if (alive) {
          setLiveness(l);
          setApiUp(true);
        }
      } catch {
        if (alive) setApiUp(false);
      }
    };
    void poll();
    const timer = window.setInterval(poll, 15000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  const dirtyCount = useStore((s) => s.tabs.filter((t) => t.kind === "file" && t.content !== t.savedContent).length);
  const output = useStore((s) => s.output);
  const languages = toolchains?.languages.map((l) => l.name).slice(0, 3) ?? [];

  return (
    <footer className="status-bar">
      <span className="status-item strong">{project ? project.name : "no project open"}</span>
      {git?.branch && (
        <button className="status-item clickable" onClick={() => setFn({ view: "git" })}>
          ⎇ {git.branch}
          {git.ahead > 0 ? ` ↑${git.ahead}` : ""}
          {git.behind > 0 ? ` ↓${git.behind}` : ""}
        </button>
      )}
      {dirtyCount > 0 && <span className="status-item warn">{dirtyCount} unsaved</span>}
      {output && (
        <button
          className="status-item clickable"
          title={output.command.length > 0 ? `$ ${output.command.join(" ")}` : "Show tool output"}
          aria-label={`Last ${output.tool} run: exit ${output.exit_code ?? "unknown"}. Show tool output.`}
          onClick={() => setFn({ panelOpen: true, panelTab: "output" })}
        >
          <span
            className={`status-dot ${output.exit_code === 0 ? "ok" : "down"}`}
            aria-hidden="true"
          />{" "}
          {output.tool} {output.exit_code === 0 ? "✓" : `✗ ${output.exit_code ?? "—"}`}
        </button>
      )}
      <div className="status-spacer" />
      {languages.map((name) => (
        <span key={name} className="status-item muted">
          {name}
        </span>
      ))}
      <span className="status-item muted">{liveness ? `api v${liveness.version}` : "api"}</span>
      <button
        className="status-item clickable muted"
        title="Diagnostics"
        onClick={() => setFn({ diagnosticsOpen: true })}
      >
        diagnostics
      </button>
      <span className={`status-dot ${apiUp ? "ok" : "down"}`} title={apiUp ? "API reachable" : "API unreachable"} />
    </footer>
  );
}

import { useStore } from "../../state/store";

export default function RunView() {
  const project = useStore((s) => s.project);
  const toolchains = useStore((s) => s.toolchains);
  const tabs = useStore((s) => s.tabs);
  const activePath = useStore((s) => s.activePath);
  const runTool = useStore((s) => s.runTool);
  const output = useStore((s) => s.output);

  if (!project || !toolchains) {
    return <aside className="sidebar"><p className="muted pad">Open a project first.</p></aside>;
  }

  const activeFile =
    tabs.find((t) => t.kind === "file" && t.path === activePath && !t.isBinary)?.path ?? null;
  const testLanguages = toolchains.languages.filter((l) => l.tools.includes("test"));

  const runFor = (tool: string, path?: string) => {
    void runTool(tool, path).catch((err: unknown) =>
      // Missing tools surface as 422 with an actionable message — show it in output.
      useStore.getState().set({
        output: {
          language: "unknown",
          tool,
          command: [],
          exit_code: null,
          timed_out: false,
          truncated: false,
          duration_ms: 0,
          stdout: "",
          stderr: err instanceof Error ? err.message : String(err),
          diagnostics: [],
          file_content: null,
        },
        panelTab: "output",
        panelOpen: true,
      }),
    );
  };

  return (
    <aside className="sidebar">
      <header className="sidebar-header">RUN &amp; TOOLCHAINS</header>
      <div className="pad stack">
        <p className="muted">
          Active file: <span className="mono">{activeFile ?? "none (open a file to format/run)"}</span>
        </p>
        <div className="row">
          <button className="button" disabled={!activeFile} onClick={() => activeFile && runFor("format", activeFile)}>
            Format file
          </button>
          <button className="button" disabled={!activeFile} onClick={() => activeFile && runFor("run", activeFile)}>
            Run file
          </button>
        </div>
        {testLanguages.map((lang) => (
          <button key={lang.id} className="button" onClick={() => runFor("test")}>
            Test ({lang.name})
          </button>
        ))}
        {toolchains.diagnostics.length > 0 && (
          <div className="diag">
            {toolchains.diagnostics.map((d) => (
              <p key={d} className="error-text">{d}</p>
            ))}
          </div>
        )}
      </div>
      <h3 className="git-section">Detected languages</h3>
      <div className="pad">
        {toolchains.languages.length === 0 && <p className="muted">No languages detected.</p>}
        {toolchains.languages.map((lang) => (
          <div key={lang.id} className="lang-card">
            <div className="strong">{lang.name}</div>
            <div className="muted mono small">
              {lang.manifests.length > 0 ? lang.manifests.join(", ") : `${lang.file_count} file(s)`}
            </div>
            <ul className="tool-list">
              {Object.entries(lang.availability).map(([tool, info]) => (
                <li key={tool}>
                  <span className={`status-dot ${info.available ? "ok" : "down"}`} />
                  <span className="mono small">{tool}</span>
                  <span className="muted small">({info.executable})</span>
                  {!info.available && (
                    <button className="tree-action" title="Try anyway" onClick={() => runFor(tool, activeFile ?? undefined)}>
                      ▶
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      {output && (
        <>
          <h3 className="git-section">Last run</h3>
          <div className="pad mono small run-summary">
            {output.command.length > 0 && <div>$ {output.command.join(" ")}</div>}
            <div>
              exit={output.exit_code ?? "—"} · {output.duration_ms}ms
              {output.timed_out ? " · TIMED OUT" : ""}
              {output.truncated ? " · truncated" : ""}
            </div>
          </div>
        </>
      )}
    </aside>
  );
}

import { useStore } from "../../state/store";
import TerminalPane from "./TerminalPane";
import PanelResize from "../shell/PanelResize";

export default function BottomPanel() {
  const panelOpen = useStore((s) => s.panelOpen);
  const panelTab = useStore((s) => s.panelTab);
  const terminalIds = useStore((s) => s.terminalIds);
  const activeTerminal = useStore((s) => s.activeTerminal);
  const output = useStore((s) => s.output);
  const setFn = useStore((s) => s.set);
  const createTerminal = useStore((s) => s.createTerminal);
  const closeTerminal = useStore((s) => s.closeTerminal);

  const panelHeight = useStore((s) => s.panelHeight);

  return (
    <section className="bottom-panel" hidden={!panelOpen} style={{ height: panelHeight }} aria-label="Utility panel">
      <PanelResize axis="bottom" />
      <div className="panel-tabs">
        <button
          className={`panel-tab ${panelTab === "terminal" ? "active" : ""}`}
          onClick={() => setFn({ panelTab: "terminal" })}
        >
          TERMINAL
        </button>
        <button
          className={`panel-tab ${panelTab === "output" ? "active" : ""}`}
          onClick={() => setFn({ panelTab: "output" })}
        >
          OUTPUT
        </button>
        {panelTab === "terminal" && (
          <>
            <span className="panel-terms">
              {terminalIds.map((id, index) => (
                <span key={id} className={`term-chip ${id === activeTerminal ? "active" : ""}`}>
                  <button className="link" onClick={() => setFn({ activeTerminal: id })}>
                    {index + 1}
                  </button>
                  <button className="tree-action" title="Close terminal" onClick={() => closeTerminal(id)}>
                    ×
                  </button>
                </span>
              ))}
            </span>
            <button className="tree-action" title="New terminal" onClick={() => void createTerminal()}>
              ＋
            </button>
          </>
        )}
        <div className="status-spacer" />
        <button className="tree-action" title="Hide panel" onClick={() => setFn({ panelOpen: false })}>
          ▾
        </button>
      </div>
      <div className="panel-body">
        {terminalIds.map((id) => (
          <div key={id} className="terminal-session" hidden={panelTab !== "terminal" || id !== activeTerminal}>
            <TerminalPane sessionId={id} />
          </div>
        ))}
        {panelTab === "terminal" && !activeTerminal && (
          <p className="muted pad">No terminal. Open a project, then press ＋.</p>
        )}
        {panelTab === "output" && (
          <div className="output-view mono">
            {!output && <p className="muted">No tool runs yet.</p>}
            {output && (
              <>
                {output.command.length > 0 && <div className="cmd">$ {output.command.join(" ")}</div>}
                <div className="muted">
                  language={output.language} · tool={output.tool} · exit={output.exit_code ?? "—"} ·{" "}
                  {output.duration_ms}ms{output.timed_out ? " · TIMED OUT" : ""}
                  {output.truncated ? " · truncated" : ""}
                </div>
                {output.diagnostics.map((d) => (
                  <div key={d} className="error-text">{d}</div>
                ))}
                {output.stdout && <pre>{output.stdout}</pre>}
                {output.stderr && <pre className="err">{output.stderr}</pre>}
              </>
            )}
          </div>
        )}
      </div>
    </section>
  );
}

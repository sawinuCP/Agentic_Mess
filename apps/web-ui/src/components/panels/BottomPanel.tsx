import { useStore } from "../../state/store";
import { describeEvent } from "../../office/selectors";
import { useOffice } from "../../state/officeStore";
import { confirmAction } from "../shell/confirm";
import ProblemsView from "./ProblemsView";
import TerminalPane from "./TerminalPane";
import PanelResize from "../shell/PanelResize";

const TABS = [
  { id: "terminal", label: "TERMINAL" },
  { id: "output", label: "OUTPUT" },
  { id: "problems", label: "PROBLEMS" },
  { id: "activity", label: "ACTIVITY" },
] as const;

function LiveActivity() {
  const events = useOffice((s) => s.events);
  const setOffice = useOffice((s) => s.set);
  const setFn = useStore((s) => s.set);
  if (events.length === 0) {
    return <p className="muted pad">No live events yet. Open a project to start monitoring.</p>;
  }
  const jumpTask = (taskId: string | null): void => {
    if (!taskId) return;
    setOffice({ selectedTaskId: taskId, selectedAgentId: null, tab: "team" });
    setFn({ view: "office", sidebarOpen: true });
  };
  return (
    <ul className="plain-list activity-list">
      {events.slice(0, 30).map((event) => (
        <li key={event.id} className="activity-row">
          <button
            className="link small activity-summary"
            title={event.event_type}
            onClick={() => jumpTask(event.task_id)}
            disabled={!event.task_id}
          >
            {describeEvent(event)}
          </button>
          <span className="muted small mono">{event.event_type}</span>
        </li>
      ))}
    </ul>
  );
}

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
      <div className="panel-tabs" role="tablist" aria-label="Utility panel tabs">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={panelTab === tab.id}
            className={`panel-tab ${panelTab === tab.id ? "active" : ""}`}
            onClick={() => setFn({ panelTab: tab.id })}
          >
            {tab.label}
          </button>
        ))}
        {panelTab === "terminal" && (
          <>
            <span className="panel-terms">
              {terminalIds.map((id, index) => (
                <span key={id} className={`term-chip ${id === activeTerminal ? "active" : ""}`}>
                  <button className="link" aria-label={`Terminal ${index + 1}`} onClick={() => setFn({ activeTerminal: id })}>
                    {index + 1}
                  </button>
                  <button
                    className="tree-action"
                    title="Close terminal"
                    aria-label={`Close terminal ${index + 1}`}
                    onClick={() => {
                      void confirmAction({
                        title: `Close terminal ${index + 1}?`,
                        body: "The PTY session ends. Output in the scrollback is discarded.",
                        confirmLabel: "Close terminal",
                      }).then((ok) => { if (ok) closeTerminal(id); });
                    }}
                  >
                    ×
                  </button>
                </span>
              ))}
            </span>
            <button className="tree-action" title="New terminal" aria-label="New terminal" onClick={() => void createTerminal()}>
              ＋
            </button>
          </>
        )}
        <div className="status-spacer" />
        <button className="tree-action" title="Hide panel" aria-label="Hide utility panel" onClick={() => setFn({ panelOpen: false })}>
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
                {(output.exit_code !== null && output.exit_code !== 0) || output.diagnostics.length > 0 ? (
                  <button
                    className="btn btn-small"
                    title="Investigate this failure in the Command Center"
                    onClick={() => setFn({ view: "command", sidebarOpen: true, centerPrefill: "Investigate this failure" })}
                  >
                    Investigate failure
                  </button>
                ) : null}
              </>
            )}
          </div>
        )}
        {panelTab === "problems" && (
          <div className="bottom-embed">
            <ProblemsView />
          </div>
        )}
        {panelTab === "activity" && <LiveActivity />}
      </div>
    </section>
  );
}

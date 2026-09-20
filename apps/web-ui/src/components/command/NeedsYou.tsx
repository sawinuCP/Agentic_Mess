// Needs-you strip (UI3): globally visible, non-intrusive attention summary
// for the workspace. Backend items come from collectAttention() (recorded
// failures: failed/blocked tasks, failed tool runs, pending approvals) so
// backend-side failures are visible here — the UI-2.5 F1 gap. The operator's
// own last tool run (client store) stays as its own row. Every row jumps
// somewhere real.

import { collectAttention } from "../../office/selectors";
import { useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";

export default function NeedsYou() {
  const tasks = useOffice((s) => s.tasks);
  const events = useOffice((s) => s.events);
  const hitl = useOffice((s) => s.hitl);
  const output = useStore((s) => s.output);
  const setWorkspace = useStore((s) => s.set);
  const setOffice = useOffice((s) => s.set);

  const items = collectAttention(events, tasks, hitl);
  const failedRun = output && output.exit_code !== 0 && output.exit_code !== null ? output : null;
  if (items.length === 0 && !failedRun) return null;

  const openAgents = (taskId?: string | null, agentId?: string | null): void => {
    setWorkspace({ view: "office", sidebarOpen: true });
    setOffice({
      tab: "team",
      selectedAgentId: agentId ?? null,
      ...(taskId ? { selectedTaskId: taskId } : {}),
    });
  };

  return (
    <section className="cc-needsyou" aria-label="Needs your attention">
      <span className="text-section">Needs you</span>
      <div className="stack">
        {items.slice(0, 5).map((item, i) => (
          <div key={`${item.kind}-${item.taskId ?? item.title}-${i}`} className="row spread">
            <span className="small">{item.title}{item.detail ? <span className="muted"> — {item.detail}</span> : null}</span>
            <span className="row gap4">
              {item.taskId && (
                <button className="btn btn-small" onClick={() => openAgents(item.taskId, null)}>
                  Inspect
                </button>
              )}
              {item.agentId && (
                <button className="btn btn-small" onClick={() => openAgents(null, item.agentId)}>
                  Open agent
                </button>
              )}
            </span>
          </div>
        ))}
        {failedRun && (
          <div className="row spread">
            <span className="small">Tool failed: {failedRun.tool} (exit {failedRun.exit_code})</span>
            <button
              className="btn btn-small"
              onClick={() => setWorkspace({ panelOpen: true, panelTab: "output" })}
            >
              Output
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

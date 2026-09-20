// Needs-you strip (UI2): globally visible, non-intrusive attention summary
// for the workspace. Real state only: pending HITL approvals + failed tasks
// + failed tool output. Every row jumps somewhere real and returns.

import { useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";

export default function NeedsYou() {
  const tasks = useOffice((s) => s.tasks);
  const hitl = useOffice((s) => s.hitl);
  const output = useStore((s) => s.output);
  const setWorkspace = useStore((s) => s.set);
  const setOffice = useOffice((s) => s.set);

  const approvals = hitl.filter((h) => h.status === "pending");
  const failed = tasks.filter((t) => t.status === "failed");
  const failedRun = output && output.exit_code !== 0 && output.exit_code !== null ? output : null;
  if (approvals.length === 0 && failed.length === 0 && !failedRun) return null;

  const openAgents = (taskId?: string): void => {
    setWorkspace({ view: "office", sidebarOpen: true });
    setOffice({ tab: "team", selectedAgentId: null, ...(taskId ? { selectedTaskId: taskId } : {}) });
  };

  return (
    <section className="cc-needsyou" aria-label="Needs your attention">
      <span className="text-section">Needs you</span>
      <div className="stack">
        {approvals.slice(0, 3).map((h) => (
          <div key={h.id} className="row spread">
            <span className="small">Approval: {h.kind ?? "decision"} — {(h.question ?? "").slice(0, 90)}</span>
            <button className="btn btn-small" onClick={() => openAgents(h.task_id ?? undefined)}>
              Review
            </button>
          </div>
        ))}
        {failed.slice(0, 3).map((t) => (
          <div key={t.id} className="row spread">
            <span className="small">Task failed: {t.title}</span>
            <button className="btn btn-small" onClick={() => openAgents(t.id)}>
              Inspect
            </button>
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

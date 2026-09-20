// Office attention strip (UI3): approvals + failed/blocked tasks + failed
// tool runs, all from recorded state. Every row jumps somewhere real.
// Shares collectAttention() with the Center NeedsYou strip.

import { collectAttention } from "./selectors";
import { useOffice } from "../state/officeStore";

export default function OfficeAttention() {
  const events = useOffice((s) => s.events);
  const tasks = useOffice((s) => s.tasks);
  const hitl = useOffice((s) => s.hitl);
  const setOffice = useOffice((s) => s.set);

  const items = collectAttention(events, tasks, hitl);
  if (items.length === 0) return null;

  const inspectTask = (taskId: string | null): void => {
    setOffice({ selectedAgentId: null, ...(taskId ? { selectedTaskId: taskId } : {}), tab: "team" });
  };
  const inspectAgent = (agentId: string | null): void => {
    if (!agentId) return;
    setOffice({ selectedAgentId: agentId, selectedTaskId: null });
  };

  return (
    <section className="office-attention" aria-label="Needs your attention">
      <h4 className="office-section-title warn">Needs you ({items.length})</h4>
      <ul className="plain-list stack">
        {items.slice(0, 5).map((item, i) => (
          <li key={`${item.kind}-${item.taskId ?? item.title}-${i}`} className="attention-row">
            <div className="small">
              <span className="strong">{item.title}</span>
              {item.detail && <span className="muted"> — {item.detail}</span>}
            </div>
            <div className="row gap4">
              {item.taskId && (
                <button className="btn btn-small" onClick={() => inspectTask(item.taskId)}>
                  Inspect
                </button>
              )}
              {item.agentId && (
                <button className="btn btn-small" onClick={() => inspectAgent(item.agentId)}>
                  Open agent
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

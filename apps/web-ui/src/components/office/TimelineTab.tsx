// Activity tab (Wave 7): the durable event stream as an intelligible live
// feed. Bursts of the same event type merge into counted groups ("3 ×
// AGENT_STARTED"); category + agent + failure filters keep dense executions
// readable. Rows navigate to the recorded agent/task via office selection.

import { useMemo, useState } from "react";
import { glue } from "@typehug/en";

import { categories, describeEvent, eventCategory, groupTimeline } from "../../office/selectors";
import { useOffice } from "../../state/officeStore";

const KIND_CLASS: Record<string, string> = {
  AGENT_: "kind-agent",
  TASK_: "kind-task",
  REVIEW_: "kind-review",
  DECISION_: "kind-review",
  HITL_: "kind-hitl",
  SECURITY_: "kind-security",
  SCOPE_: "kind-security",
  BROWSER_: "kind-tool",
  MCP_: "kind-tool",
  TOOL_: "kind-tool",
  RECOVERY_: "kind-review",
  RETRY_: "kind-review",
  MODEL_: "kind-review",
  DEPENDENCY_: "kind-task",
};

function kindClass(eventType: string): string {
  for (const prefix of Object.keys(KIND_CLASS)) {
    if (eventType.startsWith(prefix)) return KIND_CLASS[prefix];
  }
  return "kind-other";
}

function isFailure(eventType: string, payload: Record<string, unknown>): boolean {
  if (eventType.includes("FAIL") || eventType === "TASK_TERMINALLY_FAILED") return true;
  const outcome = payload.outcome;
  return outcome === "failed" || outcome === "timeout";
}

export default function TimelineTab() {
  const events = useOffice((s) => s.events);
  const agents = useOffice((s) => s.agents);
  const tasks = useOffice((s) => s.tasks);
  const setOffice = useOffice((s) => s.set);
  const [category, setCategory] = useState("all");
  const [agentFilter, setAgentFilter] = useState("all");
  const [taskFilter, setTaskFilter] = useState("all");
  const [failuresOnly, setFailuresOnly] = useState(false);

  const filtered = useMemo(() => {
    return events.filter((e) => {
      if (category !== "all" && eventCategory(e.event_type) !== category) return false;
      if (agentFilter !== "all" && e.agent_id !== agentFilter) return false;
      if (taskFilter !== "all" && e.task_id !== taskFilter) return false;
      if (failuresOnly && !isFailure(e.event_type, e.payload)) return false;
      return true;
    });
  }, [events, category, agentFilter, taskFilter, failuresOnly]);

  const groups = useMemo(() => groupTimeline(filtered), [filtered]);
  const agentName = (id: string | null): string =>
    id ? (agents.find((a) => a.id === id)?.name ?? id.slice(0, 8)) : "?";

  return (
    <div className="stack">
      <div className="row wrap" role="group" aria-label="Filter activity by category">
        <button
          className={`chip ${category === "all" && !failuresOnly ? "active" : ""}`}
          aria-pressed={category === "all" && !failuresOnly}
          onClick={() => { setCategory("all"); setFailuresOnly(false); setAgentFilter("all"); setTaskFilter("all"); }}
        >
          all
        </button>
        {categories().map(({ category: value, label }) => (
          <button
            key={value}
            className={`chip ${category === value && !failuresOnly ? "active" : ""}`}
            aria-pressed={category === value && !failuresOnly}
            onClick={() => { setCategory(value); setFailuresOnly(false); }}
          >
            {label.toLowerCase()}
          </button>
        ))}
        <button
          className={`chip ${failuresOnly ? "active" : ""}`}
          aria-pressed={failuresOnly}
          onClick={() => setFailuresOnly((v) => !v)}
        >
          failures
        </button>
      </div>
      {agents.length > 0 && (
        <label className="small muted row gap4">
          Agent
          <select
            className="text-input small"
            value={agentFilter}
            aria-label="Filter activity by agent"
            onChange={(e) => setAgentFilter(e.target.value)}
          >
            <option value="all">all agents</option>
            {agents.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        </label>
      )}
      {tasks.length > 0 && (
        <label className="small muted row gap4">
          Task
          <select
            className="text-input small"
            value={taskFilter}
            aria-label="Filter activity by task"
            onChange={(e) => setTaskFilter(e.target.value)}
          >
            <option value="all">all tasks</option>
            {tasks.map((t) => (
              <option key={t.id} value={t.id}>{t.title}</option>
            ))}
          </select>
        </label>
      )}
      <div className="timeline" role="list" aria-label="Execution activity">
        {groups.length === 0 && (
          <div className="muted small pad-h">{glue("No events yet.")}</div>
        )}
        {groups.map((group) => (
          <div key={group.key} className={`event-row ${kindClass(group.event_type)}`} role="listitem">
            <span className="event-dot" aria-hidden="true" />
            <span className="event-type mono">
              {group.count > 1 ? `${group.count} × ` : ""}{group.event_type}
            </span>
            <span className="event-detail">
              {group.details.length > 0 ? group.details[0] : describeEvent(group.newest)}
              {group.newest.agent_id && (
                <>
                  {" · "}
                  <button
                    className="link mono"
                    title="Inspect this agent"
                    onClick={() => setOffice({ selectedAgentId: group.newest.agent_id, selectedTaskId: null })}
                  >
                    {agentName(group.newest.agent_id)}
                  </button>
                </>
              )}
              {group.newest.task_id && (
                <>
                  {" · "}
                  <button
                    className="link mono"
                    title="Inspect this task"
                    onClick={() => setOffice({ selectedAgentId: null, selectedTaskId: group.newest.task_id, tab: "team" })}
                  >
                    task
                  </button>
                </>
              )}
            </span>
            <span className="event-time muted small mono" title={new Date(group.oldest.occurred_at).toLocaleString()}>
              {new Date(group.newest.occurred_at).toLocaleTimeString()}
            </span>
          </div>
        ))}
      </div>
      <div className="small muted pad-h">
        {glue(`${filtered.length} of ${events.length} recent events shown. Bursts merge within 90s. This bounded feed is not complete execution history.`)}
      </div>
    </div>
  );
}

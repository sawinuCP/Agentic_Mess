// Timeline tab (Phase 9): the durable event stream as a live feed (AC-014).

import { useMemo, useState } from "react";
import { glue } from "@typehug/en";

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
};

function kindClass(eventType: string): string {
  for (const prefix of Object.keys(KIND_CLASS)) {
    if (eventType.startsWith(prefix)) return KIND_CLASS[prefix];
  }
  return "kind-other";
}

function brief(eventType: string, payload: Record<string, unknown>): string {
  const detail = payload.detail ?? payload.verdict ?? payload.status ?? payload.title ?? "";
  return detail ? `${eventType} — ${String(detail)}` : eventType;
}

export default function TimelineTab() {
  const events = useOffice((s) => s.events);
  const [filter, setFilter] = useState<string>("all");

  const filtered = useMemo(() => {
    if (filter === "all") return events;
    return events.filter((e) => e.event_type.startsWith(filter));
  }, [events, filter]);

  return (
    <div className="stack">
      <div className="row wrap">
        {["all", "AGENT_", "TASK_", "REVIEW_", "HITL_", "SECURITY_"].map((value) => (
          <button
            key={value}
            className={`chip ${filter === value ? "active" : ""}`}
            onClick={() => setFilter(value)}
          >
            {value === "all" ? "all" : value.replace("_", "")}
          </button>
        ))}
      </div>
      <div className="timeline">
        {filtered.length === 0 && (
          <div className="muted small pad-h">{glue("No events yet.")}</div>
        )}
        {filtered.map((event) => (
          <div key={event.id} className={`event-row ${kindClass(event.event_type)}`}>
            <span className="event-dot" />
            <span className="event-type mono">{event.event_type}</span>
            <span className="event-detail" title={brief(event.event_type, event.payload)}>{brief(event.event_type, event.payload)}</span>
            <span className="event-time muted small mono">
              {new Date(event.occurred_at).toLocaleTimeString()}
            </span>
          </div>
        ))}
      </div>
      <div className="small muted pad-h">
        {glue(`${filtered.length} of ${events.length} recent events shown. This bounded feed is not complete execution history.`)}
      </div>
    </div>
  );
}

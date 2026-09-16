// Office view (Phase 9, FR-025, AC-014): the engineering-office sidebar.
//
// Three live tabs — Team (agents + tasks), Timeline (durable event stream) and
// Oversight (traceability + completion gate + review pipeline) — plus HITL
// approval cards. Typography polish comes from Typehug (glue), text-state
// transitions morph via Torph.

import { useEffect, useReducer } from "react";
import { TextMorph } from "torph/react";
import { glue } from "@typehug/en";

import { POLL_MS, runningAgents, useOffice, type OfficeTab } from "../../state/officeStore";
import { useStore } from "../../state/store";
import ApprovalCard from "./ApprovalCard";
import OversightTab from "./OversightTab";
import TeamTab from "./TeamTab";
import TimelineTab from "./TimelineTab";

const TABS: { id: OfficeTab; label: string }[] = [
  { id: "team", label: "Team" },
  { id: "timeline", label: "Timeline" },
  { id: "oversight", label: "Oversight" },
];

export default function OfficeView() {
  const project = useStore((s) => s.project);
  const officeProjectId = useOffice((s) => s.projectId);
  const tab = useOffice((s) => s.tab);
  const live = useOffice((s) => s.live);
  const lastPolledAt = useOffice((s) => s.lastPolledAt);
  const agents = useOffice((s) => s.agents);
  const setOffice = useOffice((s) => s.set);
  const [, tick] = useReducer((n: number) => n + 1, 0);

  // (Re)start live polling whenever the open project changes or the view mounts.
  useEffect(() => {
    if (!project) return;
    if (officeProjectId !== project.id) {
      useOffice.getState().start(project.id);
    }
    const timer = window.setInterval(() => {
      void useOffice.getState().poll();
    }, POLL_MS);
    const clock = window.setInterval(tick, 1000); // keep the relative-time label fresh
    return () => {
      window.clearInterval(timer);
      window.clearInterval(clock);
    };
  }, [project, officeProjectId]);

  if (!project) {
    return <div className="office-empty muted">Open a project to see the office.</div>;
  }

  const running = runningAgents(agents).length;

  return (
    <div className="office">
      <div className="office-header">
        <span className="office-title strong">{glue("Engineering office")}</span>
        <span className={`live-dot ${live ? "on" : ""}`} title={live ? "live" : "paused"} />
      </div>
      <div className="office-tabs">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            className={`office-tab ${tab === id ? "active" : ""}`}
            onClick={() => setOffice({ tab: id })}
          >
            {label}
            {id === "team" && running > 0 && <span className="badge-live">{running}</span>}
          </button>
        ))}
      </div>
      <ApprovalCard />
      <div className="office-body">
        {tab === "team" && <TeamTab />}
        {tab === "timeline" && <TimelineTab />}
        {tab === "oversight" && <OversightTab />}
      </div>
      <div className="office-footer muted small">
        <TextMorph>{glue(`synced ${relativeTime(lastPolledAt)}`)}</TextMorph>
      </div>
    </div>
  );
}

function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const seconds = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  return `${Math.round(seconds / 60)}m ago`;
}

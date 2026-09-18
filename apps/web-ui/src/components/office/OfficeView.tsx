// Office view (Wave 7): the AI engineering control room sidebar.
//
// Header carries the derived execution summary (state + live counts), project
// identity, cost snapshot, and the actual connection condition — all from
// durable state, never simulated. Tabs: Team, Activity, Comms, Oversight.
// Selecting an agent swaps the body to the detail panel with context
// preserved (back button, no route change). Approvals stay prominent above
// the body with a header count badge.

import { useEffect, useReducer } from "react";
import { TextMorph } from "torph/react";
import { glue } from "@typehug/en";

import {
  BULK_LABEL,
  bulkEligible,
  formatTokens,
  summarizeExecution,
  topEntries,
  validCosts,
} from "../../office/selectors";
import { useBulkAction } from "../../office/useBulkAction";
import { runningAgents, useOffice, type OfficeTab } from "../../state/officeStore";
import { useStore } from "../../state/store";
import AgentDetail from "./AgentDetail";
import ApprovalCard from "./ApprovalCard";
import CommsTab from "./CommsTab";
import OversightTab from "./OversightTab";
import TeamTab from "./TeamTab";
import TimelineTab from "./TimelineTab";

const TABS: { id: OfficeTab; label: string }[] = [
  { id: "team", label: "Team" },
  { id: "timeline", label: "Activity" },
  { id: "comms", label: "Comms" },
  { id: "oversight", label: "Oversight" },
];

const CONNECTION_LABEL: Record<string, string> = {
  live: "live",
  connecting: "connecting",
  reconnecting: "reconnecting",
  offline: "offline",
  degraded: "degraded",
  resyncing: "resyncing",
};

const CONNECTION_CLASS: Record<string, string> = {
  live: "on",
  connecting: "warn",
  reconnecting: "warn",
  offline: "down",
  degraded: "warn",
  resyncing: "warn",
};

export default function OfficeView() {
  const project = useStore((s) => s.project);
  const lastRun = useStore((s) => s.output);
  const setWorkspace = useStore((s) => s.set);
  const officeProjectId = useOffice((s) => s.projectId);
  const tab = useOffice((s) => s.tab);
  const connectionState = useOffice((s) => s.connectionState);
  const resyncRequired = useOffice((s) => s.resyncRequired);
  const notice = useOffice((s) => s.notice);
  const lastEventTimestamp = useOffice((s) => s.lastEventTimestamp);
  const agents = useOffice((s) => s.agents);
  const tasks = useOffice((s) => s.tasks);
  const hitl = useOffice((s) => s.hitl);
  const costs = useOffice((s) => s.costs);
  const selectedAgentId = useOffice((s) => s.selectedAgentId);
  const loadCosts = useOffice((s) => s.loadCosts);
  const setOffice = useOffice((s) => s.set);
  const [, tick] = useReducer((n: number) => n + 1, 0);
  const { bulkBusy, runBulk } = useBulkAction();

  // Start the realtime stream for the open project (authoritative load first).
  useEffect(() => {
    if (!project) return;
    if (officeProjectId !== project.id) {
      useOffice.getState().start(project.id);
    }
    const clock = window.setInterval(tick, 1000); // keep the relative-time label fresh
    return () => {
      window.clearInterval(clock);
    };
  }, [project, officeProjectId]);

  // Cost snapshot loads once per project; the header shows it when present.
  useEffect(() => {
    if (officeProjectId) void loadCosts().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [officeProjectId]);

  // Stop the stream when unmounting (project closed / sidebar hidden).
  useEffect(() => {
    return () => {
      if (!useStore.getState().project) useOffice.getState().stop();
    };
  }, []);

  if (!project) {
    return <div className="office-empty muted">Open a project to see the office.</div>;
  }

  const running = runningAgents(agents).length;
  const summary = summarizeExecution(agents.map((a) => a.state), tasks);
  const pendingHitl = hitl.filter((h) => h.status === "pending").length;
  const costData = validCosts(costs) ? costs : null;
  const displayState = connectionState === "offline" ? "offline"
    : resyncRequired ? "resyncing" : connectionState;
  const label = CONNECTION_LABEL[displayState] ?? displayState;
  const needsRecovery = connectionState === "offline" || resyncRequired;
  const topRole = costData ? topEntries(costData.by_role, 1)[0] : undefined;
  const bulk = {
    pause: bulkEligible(tasks, "pause"),
    resume: bulkEligible(tasks, "resume"),
    cancel: bulkEligible(tasks, "cancel"),
  } as const;

  const bulkTitle = (action: "pause" | "resume" | "cancel"): string => {
    const names = bulk[action].slice(0, 3).map((t) => t.title);
    const rest = bulk[action].length > 3 ? ` +${bulk[action].length - 3} more` : "";
    return `Eligible: ${names.join(", ")}${rest}`;
  };

  return (
    <div className="sidebar office">
      <div className="office-header">
        <span className="office-title strong">{glue("Engineering office")}</span>
        <span
          className={`live-dot ${CONNECTION_CLASS[displayState] ?? "warn"}`}
          title={`stream ${label}`}
        />
        <span className="small muted">{glue(label)}</span>
        {needsRecovery && (
          <button
            className="btn btn-small"
            onClick={() => void useOffice.getState().resync().catch(() => undefined)}
            title="Reload the event snapshot from the control plane"
          >
            resync
          </button>
        )}
      </div>
      <div className="office-summary" role="status" aria-label="Execution summary">
        <span className="strong small" title={project.root_path}>{project.name}</span>
        <span className={`state-pill ${summary.tone}`} title={`${summary.running} running · ${summary.waiting} waiting · ${summary.failed} failed · ${summary.total} total`}>
          {summary.label}
        </span>
        <span className="small muted">
          {agents.length} agent{agents.length === 1 ? "" : "s"} · {tasks.length} task{tasks.length === 1 ? "" : "s"}
        </span>
        {pendingHitl > 0 && (
          <span className="small warn" aria-label={`${pendingHitl} approvals needed`}>
            {pendingHitl} approval{pendingHitl === 1 ? "" : "s"}
          </span>
        )}
        {costData && costData.total_tokens > 0 && (
          <span className="small muted" title={topRole ? `top role ${topRole[0]}: ${topRole[1]} tokens` : "model token usage"}>
            {formatTokens(costData.total_tokens)} tokens
          </span>
        )}
        {lastRun && (
          <button
            className="status-item clickable small"
            title={lastRun.command.length > 0 ? `$ ${lastRun.command.join(" ")}` : "Show tool output"}
            aria-label={`Last ${lastRun.tool} run: exit ${lastRun.exit_code ?? "unknown"}. Show tool output.`}
            onClick={() => setWorkspace({ panelOpen: true, panelTab: "output" })}
          >
            <span className={`status-dot ${lastRun.exit_code === 0 ? "ok" : "down"}`} aria-hidden="true" />{" "}
            {lastRun.tool} {lastRun.exit_code === 0 ? "✓" : `✗ ${lastRun.exit_code ?? "—"}`}
          </button>
        )}
      </div>
      {(bulk.pause.length > 0 || bulk.resume.length > 0 || bulk.cancel.length > 0) && (
        <div className="office-actions" role="group" aria-label="Execution actions">
          {(["pause", "resume", "cancel"] as const).map((action) =>
            bulk[action].length > 0 ? (
              <button
                key={action}
                className="btn btn-small"
                disabled={bulkBusy}
                title={bulkTitle(action)}
                aria-label={`${BULK_LABEL[action]} ${bulk[action].length} tasks`}
                onClick={() => void runBulk(action, tasks)}
              >
                {bulkBusy ? "Sending…" : `${BULK_LABEL[action]} ${bulk[action].length}`}
              </button>
            ) : null,
          )}
        </div>
      )}
      {notice && (
        <div className="office-notice" role="status">
          {notice}
        </div>
      )}
      <div className="office-tabs">
        {TABS.map(({ id, label: tabLabel }) => (
          <button
            key={id}
            className={`office-tab ${tab === id && !selectedAgentId ? "active" : ""}`}
            onClick={() => setOffice({ tab: id, selectedAgentId: null })}
          >
            {tabLabel}
            {id === "team" && running > 0 && <span className="badge-live">{running}</span>}
          </button>
        ))}
      </div>
      <ApprovalCard />
      <div className="office-body">
        {selectedAgentId ? (
          <AgentDetail agentId={selectedAgentId} />
        ) : (
          <>
            {tab === "team" && <TeamTab />}
            {tab === "timeline" && <TimelineTab />}
            {tab === "comms" && <CommsTab />}
            {tab === "oversight" && <OversightTab />}
          </>
        )}
      </div>
      <div className="office-footer muted small">
        <TextMorph>
          {glue(
            connectionState === "live" || connectionState === "degraded"
              ? `event ${relativeTime(lastEventTimestamp)}`
              : label,
          )}
        </TextMorph>
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

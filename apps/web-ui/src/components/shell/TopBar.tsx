// Top bar (UI1): persistent answers to WHERE AM I / WHAT IS RUNNING / DOES
// ANYTHING NEED ME. Telemetry only — every figure projects existing store
// state (project, git, office roster/HITL/costs/connection). No new data,
// no new fetches beyond the existing loadCosts guard.

import { useEffect } from "react";

import { getApiToken } from "../../api/client";
import { formatTokens, validCosts } from "../../office/selectors";
import { runningAgents, useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";

function ConnDot({ state }: { state: string }) {
  const cls = state === "live" ? "ok" : state === "degraded" || state === "reconnecting" ? "warn" : "down";
  const label = state === "live" ? "Live" : state === "degraded" ? "Degraded" : state === "reconnecting" ? "Reconnecting" : state === "offline" ? "Offline" : state;
  return (
    <span className="topbar-item" title={`Realtime connection: ${label}`}>
      <span className={`status-dot ${cls}`} aria-hidden="true" /> {label}
    </span>
  );
}

export default function TopBar({ onMenu }: { onMenu: () => void }) {
  const project = useStore((s) => s.project);
  const git = useStore((s) => s.git);
  const setFn = useStore((s) => s.set);
  const agents = useOffice((s) => s.agents);
  const hitl = useOffice((s) => s.hitl);
  const costs = useOffice((s) => s.costs);
  const connectionState = useOffice((s) => s.connectionState);
  const resyncRequired = useOffice((s) => s.resyncRequired);
  const loadCosts = useOffice((s) => s.loadCosts);
  const resync = useOffice((s) => s.resync);
  const setOffice = useOffice((s) => s.set);

  const running = runningAgents(agents).length;
  const approvals = hitl.length;

  useEffect(() => {
    if (project && !validCosts(costs)) void loadCosts().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id]);

  const openOffice = (tab: "team" | "timeline" | "comms" | "oversight"): void => {
    setFn({ view: "office", sidebarOpen: true });
    setOffice({ tab, selectedAgentId: null });
  };

  return (
    <header className="top-bar" aria-label="Workspace status">
      <button className="topbar-menu" aria-label="Open navigation" onClick={onMenu}>☰</button>
      <button
        className="topbar-item strong truncate"
        title={project ? `Project: ${project.name} — ${project.root_path}` : "No project open"}
        onClick={() => setFn({ projectDialog: true })}
      >
        {project ? project.name : "No project"}
      </button>
      {git?.branch && (
        <span className="topbar-item muted truncate" title={`Branch: ${git.branch}`}>
          ⎇ {git.branch}
        </span>
      )}
      <div className="status-spacer" />
      {running > 0 && (
        <button className="topbar-item" title="Open agents" onClick={() => openOffice("team")}
          aria-label={`${running} agents working. Open agents.`}>
          <span className="live-dot on" aria-hidden="true" /> {running} working
        </button>
      )}
      {approvals > 0 && (
        <button className="topbar-item warn" title="Open approvals" onClick={() => openOffice("team")}
          aria-label={`${approvals} approvals needed. Open approvals.`}>
          ! {approvals} to review
        </button>
      )}
      <button className="topbar-item numeric" title="Open costs"
        onClick={() => openOffice("team")}
        aria-label={validCosts(costs) ? `Total tokens ${costs.total_tokens}. Open agents.` : "Token usage unavailable. Open agents."}>
        {validCosts(costs) ? `${formatTokens(costs.total_tokens)} tok` : "—"}
      </button>
      {project && (resyncRequired || connectionState === "offline" ? (
        <button className="topbar-item warn" title="Reconnect and resync" onClick={() => void resync()}>
          ⟳ resync
        </button>
      ) : (
        <ConnDot state={connectionState} />
      ))}
      <span className="topbar-item muted" title={getApiToken() ? "API token configured" : "Loopback mode, no token"}>
        {getApiToken() ? "token" : "local"}
      </span>
    </header>
  );
}

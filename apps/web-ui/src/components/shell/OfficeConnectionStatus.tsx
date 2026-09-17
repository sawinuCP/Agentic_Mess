// Shell telemetry: realtime connection state, visible app-wide (Phase 3/5).
//
// Distinct concern from execution state: a disconnected stream must never be
// presented as a failed execution. When the stream is stale/offline the shell
// exposes the existing resync action; when live, the label is plain status.

import { useOffice } from "../../state/officeStore";
import { useStore } from "../../state/store";

const LABEL: Record<string, string> = {
  live: "stream live",
  connecting: "connecting…",
  reconnecting: "reconnecting…",
  offline: "stream offline",
  degraded: "degraded · fallback polling",
  resyncing: "resyncing…",
};

const DOT: Record<string, string> = {
  live: "on",
  connecting: "warn",
  reconnecting: "warn",
  offline: "down",
  degraded: "warn",
  resyncing: "warn",
};

export default function OfficeConnectionStatus() {
  const project = useStore((s) => s.project);
  const projectId = useOffice((s) => s.projectId);
  const connectionState = useOffice((s) => s.connectionState);
  const resyncRequired = useOffice((s) => s.resyncRequired);
  const notice = useOffice((s) => s.notice);

  // No telemetry before a project is open and monitoring has started.
  if (!project || projectId !== project.id) return null;

  // Transport loss stays honest: offline wins over the resync flag, and a
  // resync that is merely pending does not disguise a dead connection.
  const state =
    connectionState === "offline"
      ? "offline"
      : resyncRequired
        ? "resyncing"
        : connectionState;
  const label = LABEL[state] ?? state;

  return (
    <span
      className="status-item office-conn"
      aria-live="polite"
      title={notice ?? `event stream: ${label}`}
    >
      <span className={`live-dot ${DOT[state] ?? "warn"}`} aria-hidden="true" />
      {label}
    </span>
  );
}

/** Resync affordance rendered next to the status when the stream needs it. */
export function OfficeResyncAction() {
  const project = useStore((s) => s.project);
  const projectId = useOffice((s) => s.projectId);
  const connectionState = useOffice((s) => s.connectionState);
  const resyncRequired = useOffice((s) => s.resyncRequired);
  if (!project || projectId !== project.id) return null;
  const stalled = connectionState === "offline" || resyncRequired;
  if (!stalled) return null;
  return (
    <button
      className="status-item clickable"
      onClick={() => void useOffice.getState().resync().catch(() => undefined)}
      title="Reload the event snapshot from the control plane"
    >
      resync
    </button>
  );
}

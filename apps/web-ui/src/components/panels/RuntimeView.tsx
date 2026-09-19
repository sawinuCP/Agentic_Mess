import { useCallback, useEffect, useState } from "react";
import { listLeases, listPorts, releasePort } from "../../api/client";
import { errorMessage } from "../../api/errors";
import { useStore } from "../../state/store";
import type { LeaseInfo, PortInfo } from "../../types";
import { StatusLabel, UiState } from "../shell/UiState";
import { summarizeRuntime } from "./runtime";

// Runtime view: ports and leases for the open project (Wave 6).
//
// Reads come from the existing list endpoints; release posts to the existing
// port-release endpoint behind a confirmation. Expired/released rows are
// history, shown muted — never deleted from here.

export default function RuntimeView() {
  const project = useStore((s) => s.project);
  const projectId = project?.id ?? null;
  const [ports, setPorts] = useState<PortInfo[] | null>(null);
  const [leases, setLeases] = useState<LeaseInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    if (!projectId) return;
    setError(null);
    Promise.all([listPorts(projectId), listLeases(projectId)])
      .then(([p, l]) => {
        setPorts(p);
        setLeases(l);
      })
      .catch((err: unknown) => setError(errorMessage(err)));
  }, [projectId]);

  useEffect(() => {
    setPorts(null);
    setLeases(null);
    refresh();
  }, [refresh]);

  if (!projectId) {
    return <aside className="sidebar"><p className="muted pad">Open a project first.</p></aside>;
  }

  const summary = summarizeRuntime(ports ?? [], leases ?? []);

  const release = (allocation: PortInfo) => {
    if (
      !window.confirm(
        `Release port ${allocation.port} (${allocation.purpose})? Holders using it will lose it.`,
      )
    ) {
      return;
    }
    setBusy(true);
    releasePort(allocation.id)
      .then(() => refresh())
      .catch((err: unknown) => setError(errorMessage(err)))
      .finally(() => setBusy(false));
  };

  return (
    <aside className="sidebar">
      <header className="sidebar-header">RUNTIME</header>
      <div className="pad stack">
        {error && (
          <UiState title="Runtime state unavailable" error retry={refresh}>
            <span>{error}</span>
          </UiState>
        )}
        <p className="muted small">
          {summary.portsActive} active ports · {summary.leasesActive} active leases
        </p>
        <section>
          <h3 className="section-title">Ports ({summary.portsTotal})</h3>
          {(ports ?? []).length === 0 && ports !== null && (
            <p className="muted small">No port allocations recorded.</p>
          )}
          <ul className="plain-list stack">
            {(ports ?? []).map((port) => (
              <li key={port.id} className="card">
                <div className="row between">
                  <StatusLabel state={port.status} />
                  <span className="mono">:{port.port}</span>
                </div>
                <p className="muted small">
                  {port.purpose}
                  {port.holder ? ` · ${port.holder}` : " · unheld"} · expires{" "}
                  {new Date(port.expires_at).toLocaleString()}
                </p>
                {port.status === "active" && (
                  <button
                    className="button secondary"
                    disabled={busy}
                    onClick={() => release(port)}
                  >
                    Release port
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
        <section>
          <h3 className="section-title">Leases ({summary.leasesTotal})</h3>
          {(leases ?? []).length === 0 && leases !== null && (
            <p className="muted small">No leases recorded.</p>
          )}
          <ul className="plain-list stack">
            {(leases ?? []).map((lease) => (
              <li key={lease.id} className="card">
                <div className="row between">
                  <StatusLabel state={lease.status} />
                  <span className="mono small">{lease.kind}/{lease.key}</span>
                </div>
                <p className="muted small">
                  expires {new Date(lease.expires_at).toLocaleString()}
                </p>
              </li>
            ))}
          </ul>
        </section>
        <button className="button secondary" onClick={refresh}>
          Refresh
        </button>
      </div>
    </aside>
  );
}

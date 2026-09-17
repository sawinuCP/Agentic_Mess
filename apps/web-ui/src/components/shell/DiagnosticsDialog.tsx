// Diagnostics dialog (Phase 10): the fail-soft support bundle, visualized.

import { useEffect, useState } from "react";
import { glue } from "@typehug/en";

import * as api from "../../api/client";
import type { DiagnosticsReport } from "../../api/client";
import { useDialogFocus } from "./useDialogFocus";
import { UiState } from "./UiState";
import { errorMessage } from "../../api/errors";

function Pill({ status }: { status: string }) {
  return <span className={`state-pill ${status === "ok" ? "ok" : "down"}`}>{status}</span>;
}

export default function DiagnosticsDialog({ onClose }: { onClose: () => void }) {
  const dialogRef = useDialogFocus(onClose);
  const [report, setReport] = useState<DiagnosticsReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setError(null);
    api.getDiagnostics().then((value) => { if (active) setReport(value); })
      .catch((err) => { if (active) setError(errorMessage(err)); });
    return () => { active = false; };
  }, [attempt]);

  return (
    <div className="overlay" onClick={onClose}>
      <div className="dialog diagnostics-dialog" ref={dialogRef} role="dialog" aria-modal="true" aria-label="Diagnostics" tabIndex={-1} onClick={(e) => e.stopPropagation()}>
        <button className="button secondary" onClick={onClose}>Close diagnostics</button>
        <h2>{glue("Diagnostics")}</h2>
        {error && <UiState title="Diagnostics unavailable" error retry={() => setAttempt((n) => n + 1)}>{error}</UiState>}
        {!report && !error && <UiState title="Collecting diagnostics…" />}
        {report && (
          <div className="stack">
            <div className="small muted mono">
              v{report.app.version} · {report.app.environment} · py {report.app.python} · up{" "}
              {Math.round(report.app.uptime_seconds)}s
            </div>
            <div className="diag-row">
              <span>{glue("Database")}</span> <Pill status={report.database.status} />
              <span className="muted small mono">{report.database.alembic_head.slice(0, 24)}</span>
            </div>
            <div className="diag-row">
              <span>{glue("Artifact store")}</span> <Pill status={report.artifact_store.status} />
            </div>
            <div className="diag-row">
              <span>Redis</span> <Pill status={report.redis.status} />
            </div>
            <div className="diag-row">
              <span>NATS</span> <Pill status={report.nats.status} />
            </div>
            <h3 className="dialog-sub">{glue("Entity counts")}</h3>
            <div className="diag-counts mono small">
              {Object.entries(report.counts).map(([table, count]) => (
                <span key={table} className="diag-count">
                  {table}: <strong>{count}</strong>
                </span>
              ))}
            </div>
            <h3 className="dialog-sub">{glue("Configuration")}</h3>
            <div className="diag-counts mono small">
              {Object.entries(report.config).map(([key, value]) => (
                <span key={key} className="diag-count">
                  {key}: <strong>{String(value)}</strong>
                </span>
              ))}
            </div>
            <div className="dialog-actions">
              <button className="button" onClick={onClose}>
                Close
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

import { useCallback, useEffect, useState } from "react";
import { getLiveness, getReadiness } from "./health";

interface LoadState<T> {
  data: T | null;
  error: string | null;
}

function useApi<T>(fetcher: () => Promise<T>): [LoadState<T>, () => void] {
  const [state, setState] = useState<LoadState<T>>({ data: null, error: null });
  const reload = useCallback(() => {
    fetcher()
      .then((data) => setState({ data, error: null }))
      .catch((error: unknown) =>
        setState({ data: null, error: error instanceof Error ? error.message : String(error) }),
      );
  }, [fetcher]);
  useEffect(() => {
    reload();
  }, [reload]);
  return [state, reload];
}

function StatusPill({ ok }: { ok: boolean }) {
  return <span className={`pill ${ok ? "pill-ok" : "pill-down"}`}>{ok ? "ok" : "down"}</span>;
}

export default function App() {
  const [liveness, reloadLiveness] = useApi(getLiveness);
  const [readiness, reloadReadiness] = useApi(getReadiness);
  const reloadAll = useCallback(() => {
    reloadLiveness();
    reloadReadiness();
  }, [reloadLiveness, reloadReadiness]);

  return (
    <main className="shell">
      <header className="header">
        <div>
          <h1>AI Harness</h1>
          <p className="subtitle">Control plane status — Phase 0 foundation</p>
        </div>
        <button className="button" onClick={reloadAll}>
          Refresh
        </button>
      </header>

      {liveness.error && readiness.error && (
        <section className="banner">
          API unreachable — is `uvicorn app.main:app --port 8000` running? ({liveness.error})
        </section>
      )}

      <section className="grid">
        <article className="card">
          <h2>Liveness</h2>
          {liveness.data ? (
            <dl>
              <div>
                <dt>status</dt>
                <dd>
                  <StatusPill ok={liveness.data.status === "ok"} />
                </dd>
              </div>
              <div>
                <dt>version</dt>
                <dd>{liveness.data.version}</dd>
              </div>
              <div>
                <dt>environment</dt>
                <dd>{liveness.data.environment}</dd>
              </div>
            </dl>
          ) : (
            <p className="muted">{liveness.error ?? "loading…"}</p>
          )}
        </article>

        <article className="card">
          <h2>Readiness</h2>
          {readiness.data ? (
            <>
              <p>
                <StatusPill ok={readiness.data.ready} />{" "}
                <span className="muted">ready = {String(readiness.data.ready)}</span>
              </p>
              <ul className="components">
                {Object.entries(readiness.data.checks).map(([name, check]) => (
                  <li key={name}>
                    <span className="name">{name}</span>
                    <StatusPill ok={check.status === "ok"} />
                    {check.detail && <span className="detail">{check.detail}</span>}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <p className="muted">{readiness.error ?? "loading…"}</p>
          )}
        </article>
      </section>

      <footer className="footer">
        Durable AI software-engineering platform — see ARCHITECTURE.md for the phase plan.
      </footer>
    </main>
  );
}

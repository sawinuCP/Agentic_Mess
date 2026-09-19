# Production Configuration (Wave 11 §27)

Every knob below is a `Settings` field overridable via `HARNESS_`-prefixed
environment variables. Defaults are the **local-first desktop posture**:
loopback-only, fail-closed, opt-in networking. A networked deployment MUST set
the marked values — the server refuses a non-loopback bind without a token.

## Must-set for any non-localhost deployment

| Setting | Default | Production value |
|---|---|---|
| `HARNESS_API_TOKEN` | `""` (auth off, loopback-only) | Strong random token; startup refuses non-loopback bind without one |
| `HARNESS_HOST` | `127.0.0.1` | Bind address; anything wider requires the token above |
| `HARNESS_CORS_ORIGINS` | vite dev + Tauri origins, no wildcard | Exact origins of the served UI; never `*` |
| `HARNESS_DATABASE_URL` | local `:15432` harness DB | Managed Postgres with backups (see `disaster-recovery.md`) |

## Must NEVER enable outside test/dev

| Setting | Default | Rule |
|---|---|---|
| `HARNESS_FAILURE_INJECTION` | `false` | Test/dev only. Hooks are no-ops when off |
| `HARNESS_RESEARCH_PRIVATE_HOSTS_ALLOWED` | `false` | Keep false unless the deployment genuinely needs intranet research |
| `HARNESS_MCP_ENABLED` | `false` | Opt-in per deployment; each server allow-listed |
| `HARNESS_TEMPORAL_ENABLED` | `false` | Enable only with the temporal compose profile running |

## Bounds to review per deployment (all have safe defaults)

`SCHEDULER_MAX_CONCURRENCY` (4) · `EXEC_MAX_CONCURRENT_PER_PROJECT` (2) ·
`TEMPORAL_MAX_CONCURRENT_WORKFLOWS` (10) / `_ACTIVITIES` (4) ·
`MODEL_BUDGET_*` (0 = unlimited — set per-task/agent caps for shared use) ·
`MODEL_PROVIDER_MAX_ATTEMPTS` (3) · `RECOVERY_BACKOFF_*` ·
`RATE_LIMIT_*` (600/60 s, per-process) · `REALTIME_MAX_CONNECTIONS` (50) ·
`RETENTION_*` (0 = keep; opt in explicitly) · `HITL_TIMEOUT_SECONDS` (300,
fail-closed) · `EXEC_TIMEOUT_CAP_SECONDS` (900).

## Safe by construction

* No dev secrets bundled (secret scan clean); `.env` never committed.
* Rehearsal provider is the default — real providers need explicit
  `HARNESS_MODELS_CONFIG` + credentials.
* Docker runtime defaults: `--network none`, `--cap-drop ALL`, read-only root
  fs, PID-capped; hardening is settings-only (payloads cannot relax it).
* Logs redact secrets; tokens never logged or returned; no credentials in URLs.
* OpenAPI served without the Prometheus scrape target; docs endpoints are
  loopback-local like everything else.

# Development Guide

Prerequisites: **Python 3.11+**, **Node 22+**, **Docker Desktop**, **Git**. Windows-first; steps
translate directly to macOS/Linux (swap `.venv\Scripts` for `.venv/bin`).

## 1. One-time setup

```powershell
# Local infrastructure (PostgreSQL + Redis + NATS)
docker compose up -d postgres redis nats

# Python control plane
python -m venv .venv
.venv\Scripts\pip install -e "services/api[dev]"

# Web UI
cd apps\web-ui
npm install
cd ..\..
```

## 2. Environment variables

All settings are `HARNESS_`-prefixed (see `services/api/app/core/config.py`); a `.env` in
`services/api` is also read. Defaults work with `docker-compose.yml` as-is.

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `HARNESS_ENVIRONMENT` | `dev` | `dev` / `test` / `prod` |
| `HARNESS_LOG_LEVEL` | `INFO` | Root log level |
| `HARNESS_DATABASE_URL` | `postgresql+psycopg://harness:harness@localhost:15432/harness` | PostgreSQL (source of truth) |
| `HARNESS_REDIS_URL` | `redis://localhost:16379/0` | Redis (leases/cache, Phase 4+) |
| `HARNESS_NATS_URL` | `nats://localhost:14222` | NATS (events/transport, Phase 3+) |
| `HARNESS_READINESS_TIMEOUT_SECONDS` | `2.0` | Probe timeout for readiness checks |
| `HARNESS_REQUIRE_REDIS` / `HARNESS_REQUIRE_NATS` | `false` | Fail readiness when components are down |
| `HARNESS_OTEL_ENABLED` | `false` | Enable OTel tracing |
| `HARNESS_OTEL_EXPORTER_ENDPOINT` | `http://localhost:4318/v1/traces` | OTLP/HTTP endpoint |
| `HARNESS_TEMPORAL_ENABLED` | `false` | Durable task execution via Temporal |
| `HARNESS_TEMPORAL_ADDRESS` | `localhost:7233` | Temporal frontend gRPC address |
| `HARNESS_TEMPORAL_TASK_QUEUE` | `ai-harness-tasks` | Task queue for the durable worker |
| `HARNESS_SCHEDULER_ENABLED` | `true` | Enable the bounded scheduling pass endpoint |
| `HARNESS_SCHEDULER_MAX_CONCURRENCY` | `4` | Global cap on concurrently running tasks |
| `HARNESS_SCHEDULER_ROLE_LIMITS` | *(empty)* | JSON per-role caps, e.g. `{"implementer": 2}` |
| `HARNESS_SPAWN_MAX_DEPTH` | `2` | Bounded recursion depth for spawned agents/tasks |
| `HARNESS_NATS_DELIVERY_ENABLED` | `false` | NATS JetStream fan-out for durable messages |
| `HARNESS_NATS_DELIVERY_STREAM` | `harness-messages` | JetStream stream name |
| `HARNESS_NATS_DELIVERY_SUBJECT_PREFIX` | `harness.msg` | Subject prefix (`.agent.*` / `.broadcast`) |
| `HARNESS_INDEX_MAX_FILES` | `5000` | Cap on files indexed per project |
| `HARNESS_INDEX_MAX_FILE_BYTES` | `524288` | Skip source files larger than this |
| `HARNESS_CONTEXT_RETRIEVAL_ENABLED` | `true` | Hybrid code retrieval in the agent context (T3) |
| `HARNESS_RETRIEVAL_K` | `6` | Code symbols injected into the agent context |
| `HARNESS_MODEL_BUDGET_TOKENS_PER_TASK` | `0` | Per-task token budget; 0 = unlimited (spec §32) |
| `HARNESS_RUNTIME_BACKEND` | `local` | Execution backend: `local` or `docker` (spec §19) |
| `HARNESS_DOCKER_IMAGE` | `python:3.11-slim` | Image for the docker runtime backend |
| `HARNESS_DOCKER_NETWORK` | `none` | Container network policy (SEC-005: none by default) |
| `HARNESS_DOCKER_MEMORY` / `HARNESS_DOCKER_CPUS` | `512m` / `1.0` | Container resource caps |
| `HARNESS_EXEC_TIMEOUT_CAP_SECONDS` | `900` | Wall-clock clamp on agent command timeouts |
| `HARNESS_EXEC_MAX_CONCURRENT_PER_PROJECT` | `2` | Concurrent execution slots per project |
| `HARNESS_PORT_RANGE_LOW` / `HARNESS_PORT_RANGE_HIGH` | `21000` / `21999` | Port allocator range |
| `HARNESS_PORT_TTL_SECONDS` | `3600` | Port allocation TTL (spec §19.1) |
| `HARNESS_BROWSER_ENABLED` | `true` | Playwright browser debugging (FR-020) |
| `HARNESS_BROWSER_MAX_SESSIONS` | `5` | Concurrent headless chromium sessions |
| `HARNESS_MCP_ENABLED` | `false` | MCP gateway (opt-in; servers run commands) |
| `HARNESS_MCP_CONFIG_PATH` | *(empty)* | JSON config: `{"servers": [{name, command, args, env, allowed_tools}]}` |
| `HARNESS_MCP_TIMEOUT_SECONDS` | `60` | Per-request MCP timeout |
| `HARNESS_RESEARCH_ENABLED` | `true` | Web research fetch/search (FR-022) |
| `HARNESS_RESEARCH_PRIVATE_HOSTS_ALLOWED` | `false` | SSRF posture: deny private/loopback fetch destinations by default (Wave 1) |
| `HARNESS_RESEARCH_MAX_BYTES` | `2000000` | Fetch size cap |
| `HARNESS_RESEARCH_TIMEOUT_SECONDS` | `30` | Fetch/search timeout |
| `HARNESS_API_TOKEN` | *(empty)* | API bearer token; empty = auth disabled (loopback-only local mode only) |
| `HARNESS_HOST` | `127.0.0.1` | Server bind host; non-loopback without a token refuses to start |
| `HARNESS_CORS_ORIGINS` | `localhost:5173` + Tauri origins | Explicit CORS allow-list (comma-separated; no wildcard) |
| `HARNESS_AGENT_ENV_ALLOW` | *(empty)* | Extra env var names agent subprocesses may inherit (deny-by-default; sensitive names never) |
| `HARNESS_ARTIFACTS_DIR` | `./data/artifacts` | Content-addressed artifact store root |

## 3. Run

```powershell
# API (from services/api; or use the repo-root venv binaries)
.venv\Scripts\uvicorn app.main:app --reload --port 8000
#   http://localhost:8000/healthz   liveness
#   http://localhost:8000/readyz    readiness (postgres required; redis/nats per policy)
#   http://localhost:8000/docs      OpenAPI UI

# Web UI (from apps/web-ui)
npm run dev          # http://localhost:5173 — proxies /api → localhost:8000

# End-to-end smoke (editor API + git + terminal round-trip) with the server running:
..\.venv\Scripts\python scripts\smoke_editor.py

# Durable execution smoke (Temporal). Requires: --profile temporal up,
# the worker running, and the API started with HARNESS_TEMPORAL_ENABLED=true:
#   .venv\Scripts\python -m app.durable.worker    # cwd: services/api
..\.venv\Scripts\python scripts\smoke_durable.py

# Scheduler smoke (Phase 4): bounded scheduling → live Temporal, leases honored:
..\.venv\Scripts\python scripts\smoke_scheduler.py

# Code-intelligence smoke (Phase 5): index → incremental → retrieval → SCIP export:
..\.venv\Scripts\python scripts\smoke_intelligence.py

# Execution-plane smoke (Phase 6): runtime status → port allocator → quota slots:
..\.venv\Scripts\python scripts\smoke_runtime.py

# Optional heavy infra
docker compose --profile temporal up -d          # Temporal + UI (http://localhost:8088)
docker compose --profile observability up -d     # OTel collector (OTLP 4317/4318)
```

### Durable execution (Phase 2)

Tasks are durable rows; executing one starts the `TaskExecutionWorkflow` in Temporal, which runs
bounded, retryable attempts with backoff timers and stores raw output as evidence artifacts.
Temporal is **opt-in**: with `HARNESS_TEMPORAL_ENABLED=false` (default) the execute endpoint fails
closed with 503 and a clear message. The worker is a separate process (`python -m
app.durable.worker`, cwd `services/api`).

### Editor features (Phase 1)

| Area | Capabilities |
| ---- | ------------ |
| Projects | Open by absolute path (registered in PostgreSQL), list, unregister |
| Explorer | Lazy tree, new/rename/delete, ignored dirs (node_modules, .venv, …) |
| Editor | Monaco (bundled), tabs, dirty tracking, Ctrl+S, Ctrl+P quick-open |
| Search | Text/regex, match-case, grouped results, click-to-line |
| Git | status/stage/unstage/commit/log/branches/checkout/init, HEAD↔worktree diff |
| Run view | Detected languages + tool availability; format/run/test/build actions |
| Terminal | Real PTY (PowerShell on Windows), bounded sessions, resize |

### Toolchain overrides (FR-029, LANG-001..004)

Builtin languages: Python, JavaScript, TypeScript, Go, Rust, C#. Detection uses manifest files and
extensions. Override or add commands per project via `.ai-harness/toolchains.json`:

```json
{
  "languages": {
    "python": {
      "tools": {
        "format": { "argv": ["ruff", "format", "{file}"], "in_place": true },
        "run": { "argv": ["python", "{file}"] }
      }
    }
  }
}
```

Placeholders: `{file}` (project-relative), `{file_abs}`, `{dir}`, `{file_stem}`. Tools whose
command references a file require a file to be selected. Missing executables produce actionable
diagnostics naming the tool, the executable and the override file (LANG-003).

## 4. Database migrations

```powershell
# from services/api (alembic.ini lives there)
..\..\.venv\Scripts\alembic upgrade head
..\..\.venv\Scripts\alembic revision --autogenerate -m "describe change"
..\..\.venv\Scripts\alembic downgrade -1
```

Rules: one logical change per revision; hand-review autogenerated diffs; never edit an applied
revision — add a new one.

## 5. Tests & quality gates

```powershell
powershell -File scripts\check.ps1        # everything below, as CI runs it

.venv\Scripts\ruff check services/api
.venv\Scripts\ruff format --check services/api
.venv\Scripts\mypy                        # cwd: services/api
.venv\Scripts\pytest -q                   # cwd: services/api
.venv\Scripts\pytest -q -m integration    # needs PostgreSQL (skips if unreachable)
```

Integration tests auto-skip when infrastructure is down; CI runs them against a real PostgreSQL.

## 6. Project layout

See `ARCHITECTURE.md` §14 for the annotated tree and the module map (§2).

## 7. Extension guides

- **Add a language adapter (Phase 1 — available now):** add a `LanguageDefinition` to
  `services/api/app/toolchains/registry.py` (extensions, manifests, tool commands) or provide a
  project-level `.ai-harness/toolchains.json` override — no service-logic changes needed
  (LANG-001..004).
- **Add a tool (Phase 3, `services/api/app/tools/`):** declare schema + permissions in the tool
  registry; the gateway enforces policy, timeout, normalization and audit (SEC-001).
- **Add an MCP server (Phase 7, `services/api/app/mcp/`):** add an entry to the
  `HARNESS_MCP_CONFIG_PATH` JSON (`{"servers": [{"name", "command", "args", "env",
  "allowed_tools"}]}` — stdio servers speaking newline-delimited JSON-RPC); discovery,
  authorization (per-server tool allowlists), schema validation and audit all run through
  `app/mcp/registry.py` (FR-021). The gateway is opt-in (`HARNESS_MCP_ENABLED=true`).
- **Add a web-research provider (Phase 7, `services/api/app/research/service.py`):** the
  fetch pipeline (bounds → artifact → T5 provenance context item) is provider-agnostic;
  `search_web` is the only network-dependent piece — swap the DDG HTML adapter for an API
  provider without touching the evidence-packet path (FR-022).
- **Add a model provider (Phase 3, `services/api/app/agents/models/`):** implement the provider
  adapter; map roles → models in routing config. No model names in code (spec §32).

## 8. Troubleshooting

| Symptom | Fix |
| ------- | --- |
| `readyz` shows postgres `down` | `docker compose up -d postgres`; check `HARNESS_DATABASE_URL` |
| Password auth failed on 5432 | A local PostgreSQL owns 127.0.0.1:5432; this project maps Docker to **15432** by default — ensure `HARNESS_DATABASE_URL` uses it |
| Port 15432/16379/14222 busy | Change the host port in `docker-compose.yml` and the matching `HARNESS_*` default |
| `alembic` can't find `app` | Run from `services/api` with the repo-root venv, or `pip install -e services/api` |
| Docker Desktop not running | Start it; `docker compose config -q` validates without the daemon |
| npm install fails behind proxy | Configure npm registry/proxy per your environment |

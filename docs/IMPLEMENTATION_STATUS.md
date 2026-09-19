# Implementation Status

**Generated:** 2026-09-16 · **Spec:** v1.0 (2026-09-14) · **Current phase:** 10 — Hardening & packaging (complete; all 10 spec phases delivered)

## Phase overview

| Phase | Deliverable | Status | Notes |
| ----- | ----------- | ------ | ----- |
| 0 | Architecture foundation | **COMPLETE** | Repo, CI, service scaffold, migrations, tests, compose, observability skeleton, docs |
| 1 | Conventional editor (no AI required) | **COMPLETE** | Projects, explorer, Monaco editor+tabs, search, Git panel, terminals (real PTY), toolchain registry/detection/run, quick-open |
| 2 | Durable core (PostgreSQL entities + artifacts) | **COMPLETE** | Full spec §29 schema (21 entities, migrations 0002-0006), artifacts store, durable Temporal task execution with attempts/evidence |
| 3 | Agent runtime + durable orchestration | **COMPLETE** | Lifecycle, model routing + escalation, tool gateway + HITL gates, context broker, pause/resume, supervision, agent replacement |
| 4 | Multi-agent orchestration | **COMPLETE** | Resource leases, scheduler + spawn policy, NATS message fan-out, worktrees + integration queue |
| 5 | Code intelligence | **COMPLETE** | Symbol index (tree-sitter/ast), incremental reindex, hybrid retrieval, SCIP-JSON export, model cost ledger |
| 6 | Execution plane | **COMPLETE** | Port allocator (TTL/bind-probe), runtime manager (local + docker isolation), execution quotas via leases |
| 7 | Browser / MCP / web research | **COMPLETE** | Playwright browser sessions + evidence artifacts, MCP stdio gateway with permission controls, research evidence packets |
| 8 | Quality & oversight | **COMPLETE** | Requirement overseer (traceability + evidence-backed completion gate), review/debate/adjudication pipeline, credential-scanner security gate |
| 9 | Office UI | **COMPLETE** | Engineering-office sidebar (team, timeline, oversight), HITL approval cards, live polling, AI-agent UI theme (Torph/Typehug) |
| 10 | Hardening & packaging | **COMPLETE** | Failure classification + bounded recovery, restart-recovery proof, log secret redaction, prompt-injection detector, diagnostics endpoint+dialog, project export/import; Tauri shell deferred (ADR-0008) |

## Phase 3 — agent runtime core (implemented 2026-09-14)

The Phase-3 increment delivers the agent execution core inside the durable harness:

- **`app/agents_runtime/`** new package:
  - `lifecycle.py` — spec §12 state machine (14 states), validated transitions, runtime-only control
  - `providers.py` — model provider protocol; **RehearsalProvider** (deterministic offline
    default) and **OpenAICompatibleProvider** (real HTTP adapter for GLM/OpenAI/vLLM endpoints via
    `HARNESS_OPENAI_*`)
  - `models_registry.py` — config-driven role routing (worker/planner/reviewer/adjudicator/…)
    from `HARNESS_MODELS_CONFIG` JSON merged over defaults; no model names in code
  - `observations.py` — RTK-style observation compression (FR-023): status/exit/summary/error
    lines/artifact refs, never raw logs (PERF-004)
  - `gateway.py` — tool gateway (SEC-001/002): task allowlists, global deny patterns,
    approval-required patterns (→ HITL), timeouts, evidence artifacts, normalized observations
  - `context_broker.py` — tiered context assembly (T0 safety … T5 evidence) with token budgets;
    T0 never dropped
- **Durable integration**: workflow now creates a disposable agent per attempt, runs lifecycle
  transitions (created→running→verifying→completed/failed) with `AGENT_*` events, executes through
  the gateway, and supports **pause/resume signals** (safe checkpoints between activities; agent
  reaches `pause_requested→paused→resuming`).
- **New endpoints**: `POST /api/tasks/{id}/pause` / `resume` (Temporal signals), `GET /api/events`
  (filterable durable event replay).
- **Tests**: 87 passing — new unit suites for lifecycle, gateway policy, observation compression,
  context budgeting, registry routing; live `smoke_durable.py` now exercises the full agent path.

### Phase 3 validation log (2026-09-14)

| Gate | Result |
| ---- | ------ |
| ruff / mypy (115 files) | pass |
| pytest — **87 passed** | pass |
| `scripts/smoke_durable.py` — agent-driven execution (rehearsal provider → gateway → evidence) | **PASS** |
| web-ui lint + build | pass |

Phase-3 follow-ups were completed inside the Phase-3 commit: HITL fail-closed approval gates
(polling activity on `hitl_requests`, timeout = rejection), heartbeat-based session supervision
(stale sessions → `lost`, agents → `failed`), agent replacement with `replaces_agent_id` provenance,
and per-route model fallback escalation. Remaining deferrals are tracked in the honesty list below
and in the requirements matrix.

## Phase 6 — execution plane (implemented 2026-09-16)

Per spec §19/§19.1, on top of the Phase-4/5 foundations:

- **Runtime manager (FR-018/SEC-005)** — `app/runtime/runtimes.py`: `RuntimeSpec` +
  `execute()` normalizing two backends behind one `ExecResult` shape. `local` = the
  existing subprocess runner (trusted work); `docker` = untrusted code in a container with
  the workspace as the only bind-mount, **network disabled by default**, memory/CPU caps
  (`--memory/--cpus`), and `no-new-privileges`. Backend is settings-driven
  (`HARNESS_RUNTIME_BACKEND`) with per-task payload overrides; unknown backends fail
  closed; docker daemon absence maps to a 503. **Verified live**: a real
  `docker run` execution returned correct output through the shared contract.
- **Execution quotas (spec §19)** — `app/services/executions.py`: per-project concurrent
  execution slots implemented as `runtime`-kind resource leases (`<project>#exec-slot-n`),
  reusing the Phase-4 TTL/expiry machinery. The execution activity acquires a slot before
  running and releases it in a `finally` — exhaustion yields `QUOTA_EXCEEDED`, never an
  invisible queue. Wall-clock timeouts are clamped to `HARNESS_EXEC_TIMEOUT_CAP_SECONDS`.
- **Port allocator (spec §19.1)** — `app/services/ports.py` + `port_allocations` table
  (migration `0009`): agents request ports in a configured range instead of guessing;
  an allocation requires the port to be free in the ledger **and actually bindable on
  loopback right now** (the Phase-0 lesson made the live bind probe mandatory); TTL expiry,
  holder-checked release/renewal, and `PORT_*` audit events.
- **API** — `routes/execution/`: `GET /runtime/status` (backend posture + limits),
  `POST /projects/{id}/ports`, `GET /projects/{id}/ports`, `POST /ports/{id}/renew|release`,
  `POST /ports/expire-stale`.

### Phase 6 validation log (2026-09-16)

| Gate | Result |
| ---- | ------ |
| ruff / mypy (176 files) | pass |
| pytest — **158 passed** (+15: port allocator, runtime manager, quotas) | pass |
| Docker backend — real `docker run` execution verified (network-none, capped) | PASS |
| Live smokes: durable (quota slots in path) · runtime · intelligence · editor (7/7) | PASS |

## Phase 5 — code intelligence (implemented 2026-09-15)

Layered per ARCHITECTURE §8 — structural first, embeddings as one ranker:

- **Symbol index (tree-sitter + ast)** — `app/codeintel/parser.py`: Python via the
  stdlib `ast` (exact), javascript/typescript/go/rust/c-sharp via tree-sitter grammars
  (walk-based extraction, no query-API churn), and a documented regex fallback when a
  grammar is unavailable. `SymbolSpan`s carry kind (class/function/method/interface/
  struct/enum/trait/impl/type), parent, signature, doc, 1-based line span.
- **Incremental indexer (PERF-008)** — `app/codeintel/indexer.py`: content-hash-driven;
  a file is re-extracted only when it changed, deleted files are pruned, and each file
  commits atomically (crash-safe partial index). Dependency/asset directories and
  oversized files are skipped with configurable caps.
- **Hybrid retrieval** — `app/codeintel/retrieval.py`: lexical scoring (exact/prefix/
  token-overlap/signature hits, kind boosts) combined with pgvector cosine similarity
  over deterministic local embeddings (`app/codeintel/embeddings.py`, dim-256 hashing
  embedder — stable across runs, so unchanged files keep their embeddings). Wired into
  the agent context as the T3 "relevant code" tier (`context_broker.assemble(code_text=…)`,
  never breaking a run on retrieval failure).
- **SCIP-JSON export** — `app/codeintel/scip.py`: metadata + documents + definition
  occurrences built from the durable index (documented harness-scheme subset; full
  binary-protocol interop tracked for Phase 8 tooling).
- **Model cost ledger (spec §32)** — `app/services/costs.py` + `model_invocations` table:
  every model call records provider/model/tokens/latency per task & agent; optional
  `HARNESS_MODEL_BUDGET_TOKENS_PER_TASK` gate fails closed with `BUDGET_EXCEEDED` and a
  `MODEL_BUDGET_EXCEEDED` audit event. The deferred Phase-4 ledger item is now delivered.
- **API** — `routes/intelligence/`: `POST /intelligence/index`, `GET /intelligence/status`
  (engines per language), `GET /symbols?q=&kind=`, `GET /symbols/file?path=`,
  `GET /intelligence/retrieve?q=`, `GET /intelligence/scip`, `GET /intelligence/costs`.

### Phase 5 validation log (2026-09-15)

| Gate | Result |
| ---- | ------ |
| ruff / mypy (165 files) | pass |
| pytest — **143 passed** (+20: parser, embeddings, SCIP, index/retrieval/costs) | pass |
| Live smokes: editor (7/7) · durable (agent loop + evidence) · scheduler (leases) | PASS |
| `scripts/smoke_intelligence.py` — index → retrieve → costs through the live API | PASS |

## Phase 4 — COMPLETE (2026-09-15)

Multi-agent orchestration on top of the durable core:

- **Resource leases (spec §18)** — `app/services/leases.py` + `/api/leases*`: TTL leases with
  computed (never stored) expiry, holder-checked heartbeat renewal and release, deterministic
  all-or-nothing batch acquisition (deadlock avoidance), idempotent stale-expiry pass, and
  `LEASE_*` audit events written in the lease transaction. Expired leases re-acquire cleanly.
- **Scheduler (FR-009/011, PERF-003)** — `app/services/scheduler.py` + `POST /api/projects/{id}/
  scheduler/tick` and `GET .../scheduler/state`: read-only planning pass + durable commit
  (`TASK_SCHEDULED` events); global concurrency cap, per-role caps
  (`HARNESS_SCHEDULER_ROLE_LIMITS` JSON), priority ordering, dependency-aware ready set, and
  honor of task-declared `resource_requirements` against active leases. Fail-closed 503 without
  Temporal — the scheduler never schedules work it cannot durably start.
- **Spawn policy (FR-007)** — `app/agents_runtime/spawn_policy.py`: pure bounded-recursion policy
  (`HARNESS_SPAWN_MAX_DEPTH`), spawning-role gating, non-clamping child depth inheritance
  (bounds are enforced by evaluation, never hidden by clamping).
- **Message delivery (FR-010)** — `app/messaging/broker.py`: `MessageBroker` protocol with a NATS
  JetStream adapter (`Nats-Msg-Id` dedup; direct `harness.msg.agent.*` + broadcast subjects) and a
  fail-loud `NullBroker`; `POST /api/messages/deliver-pending` performs an at-least-once fan-out
  over undelivered durable messages (opt-in `HARNESS_NATS_DELIVERY_ENABLED`); migration `0007`
  adds `delivered_at`/`delivery_attempts` bookkeeping — PG stays the source of truth.
- **Worktrees + integration queue (FR-012, spec §17)** — `app/services/worktrees.py` +
  `app/api/routes/worktrees.py`: isolated `agent/task-*` worktrees (active-branch takeover
  refused; dirty release requires explicit force so failed attempts stay inspectable), FIFO
  integration queue (`integration_status`/`integration_position`), conflict-safe `--no-ff` merge
  that aborts cleanly and records an **explicit conflict task** (parent-linked, role
  `integration`) instead of dirtying the canonical workspace. Harness worktree paths are kept out
  of `git status` via local `.git/info/exclude`.

### Phase 4 validation log (2026-09-15)

| Gate | Result |
| ---- | ------ |
| ruff / mypy (135 files) | pass |
| pytest — **123 passed** (+33: leases, scheduler, messaging, worktrees, spawn policy) | pass |
| `scripts/smoke_scheduler.py` — scheduler → live Temporal; lease-skip → release → re-schedule | **PASS** |
| `scripts/smoke_durable.py` — full agent loop through live Temporal (unchanged) | PASS |

## 2026-09-14 — Industry-standard restructure (v0.3.0, pre-Phase-3)

Codebase audit and restructure before Phase 3, per the layering discipline now documented in
[CONTRIBUTING.md](CONTRIBUTING.md):

- **`app/schemas/`** layer created — all Pydantic request/response DTOs moved out of route files
  into per-domain contract modules (health, projects, files, git, requirements, tasks, agents,
  messages, artifacts, knowledge, toolchains).
- **`app/services/`** layer created — business logic + persistence extracted from routes into
  framework-free, fully-typed sync services (projects, requirements, plans, tasks, agents,
  messages, artifacts, knowledge, toolchains, events). Routes are now thin:
  parse → `asyncio.to_thread(service)` → return.
- **Fixed dependency direction** enforced: routes → schemas → services → db/adapters; services
  import no FastAPI. `core.errors.DomainError` is the single error contract.
- `db/models/event.py` renamed to `events.py` (consistency with sibling domain modules);
  superseded `app/events/` package folded into `app/services/events.py`.
- Tool runs now persist large outputs as **evidence artifacts** automatically
  (`ToolRunOut.artifact_ids`), closing the loop with the Phase-2 artifact store (LANG-005).
- **Frontend ESLint** (flat config, typescript-eslint + react-hooks) added with `npm run lint`
  and a CI gate; zero violations.
- Versions synced to **0.3.0** (api + web-ui); CI web-ui job renamed "lint + build".
- New: [CONTRIBUTING.md](CONTRIBUTING.md) (layering rules, endpoint checklist, commit style).

Validation: ruff ✓ · mypy (104 files) ✓ · pytest **68 passed** ✓ · web-ui lint + build ✓ ·
`smoke_editor.py` PASS (7/7 incl. PTY round-trip) · `smoke_durable.py` PASS (Temporal execution
with evidence artifact) — all after the restructure.

## Phase 2 — completed scope

- [x] **Full durable schema (spec §29)** — migrations `0002_planning`, `0003_tasks_messaging`,
      `0004_knowledge_isolation`, `0005_oversight_infra`, `0006_events_task_uuid`:
      workspaces, requirements, acceptance_criteria, plans, agents, agent_sessions, tasks,
      task_dependencies, task_attempts, messages, artifacts, context_items, memories, worktrees,
      resources (lease columns), decisions, reviews, validations, hitl_requests, runtime_instances,
      toolchains — all with FKs, indexes and JSONB defaults
- [x] **Requirements → plans → tasks** domain APIs with mandatory acceptance criteria (TASK-001),
      dependency edges and up-front cycle rejection (spec §18), traceability columns
      (requirement→plan→task→attempt, FR-013)
- [x] **Task attempts** with bounded retry policy, outcome + failure class (spec §26 classes),
      evidence artifact links (TASK-003, REC-001)
- [x] **Artifacts**: content-addressed on-disk store (dedupe by sha256) + metadata API
      (upload/download); Phase-1-style raw outputs persisted as evidence by workflow activities
- [x] **Agents & sessions**: durable registry with lifecycle state, sessions with heartbeats
- [x] **Messages**: durable, replayable inter-agent envelopes (spec §14) with conversations,
      correlation ids, payload refs, TTL
- [x] **Memories** (FACT/EVIDENCE/DECISION/OPINION/APPROVAL + provenance/freshness) and
      **context items** (T0..T6 tiering) — durable substrates for the Phase 3 context broker
- [x] **Temporal integration**: opt-in (`HARNESS_TEMPORAL_ENABLED`), `TaskExecutionWorkflow`
      with bounded retries and durable backoff timers, six activities (load_task,
      start_attempt, execute_work, finish_attempt, set_task_status, record_event), worker
      entrypoint (`python -m app.durable.worker`), fail-closed 503 execute endpoint when disabled
- [x] `scripts/smoke_durable.py`: live smoke — requirement → plan → task → workflow → completion
      → evidence artifact verified by content

### Phase 2 validation log (all gates executed locally, 2026-09-14)

| Gate | Result |
| ---- | ------ |
| `alembic upgrade head` (0002 → 0006) against Docker PostgreSQL | pass |
| `ruff check` / `ruff format --check` | pass |
| `mypy` (83 source files) | pass |
| `pytest -q` — **68 passed** (incl. new durable-core + activity integration tests) | pass |
| `npm run build` (web-ui) | pass |
| `scripts/smoke_durable.py` — full Temporal execution with live worker | **PASS** |

Issues found and fixed during Phase 2 validation (kept for the record):

1. `events.task_id` was still the Phase-0 correlation string — promoted to a real UUID FK to tasks
   via migration `0006` (USING cast + FK, SET NULL).
2. Exception handlers were registered for the three domain-error subclasses but not the shared
   `DomainError` base, so directly-raised base errors bypassed HTTP mapping — now registered once.
3. Temporal `auto-setup` loops forever without an explicit `DB_PORT` — pinned `DB_PORT: "5432"` in
   compose (documented quirk).
4. `RetryPolicy` uses `initial_interval` (timedelta) and `execute_activity` timeouts are typed
   `timedelta` — corrected to satisfy temporalio's typed API.

## Phase 1 — completed scope

- [x] **Projects**: open (absolute path, validated + registered in PostgreSQL), list, re-open
      idempotent, unregister; `PROJECT_OPENED` events persisted
- [x] **Explorer**: lazy file tree with ignore rules, create/rename/delete (path-confined),
      refresh
- [x] **Editor**: Monaco (bundled locally, no CDN), tabs with dirty tracking, Ctrl+S save,
      binary-file detection, quick-open (Ctrl+P)
- [x] **Search**: full-text search with regex/case options, grouped results, click-to-line
- [x] **Git**: status (porcelain parse incl. renames), stage/unstage, commit, log, branches,
      checkout, init, diff (HEAD↔worktree in Monaco DiffEditor)
- [x] **Toolchains**: data-driven registry (Python, JavaScript, TypeScript, Go, Rust, C#),
      manifest+extension detection, per-project overrides via `.ai-harness/toolchains.json`,
      PATH availability probes with TTL, format/run/test/build actions with actionable
      missing-tool diagnostics (LANG-003); formatter output refreshes the open tab
- [x] **Terminals**: real PTY sessions (pywinpty/ConPTY on Windows; POSIX pty fallback) over
      WebSocket + xterm.js, bounded session count, resize support
- [x] **Events**: PROJECT_OPENED / FILE_WRITTEN / TOOL_RUN_COMPLETED / GIT_COMMIT persisted to
      the durable `events` stream
- [x] Security posture: every client path validated in-both-path-flavors before normalization
      (absolute/UNC/traversal rejected) — one real bug of this class found and fixed by tests
- [x] `scripts/smoke_editor.py`: live end-to-end smoke (project → tree → search → tool run →
      git cycle → PTY terminal round-trip)

### Phase 1 validation log (all gates executed locally, 2026-09-14)

| Gate | Result |
| ---- | ------ |
| `ruff check` / `ruff format --check` (services/api) | pass |
| `mypy` (53 source files) | pass |
| `pytest -q` — **50 passed** (unit + live-DB integration) | pass |
| `npm run build` (tsc --noEmit + vite; Monaco bundled) | pass |
| `scripts/smoke_editor.py` against live uvicorn | **PASS** (all 7 steps incl. PTY round-trip) |

Issues found and fixed during Phase 1 validation (kept for the record):

1. Terminal session route initially took `project_id` from the body while the dependency expected a
   path param → 422; route made project-scoped (`/api/projects/{id}/terminal/sessions`).
2. pywinpty 3.x `read(size)` is a blocking size-read, not a timeout read → backend reworked to
   blocking pump semantics with exception-safe shutdown.
3. Path resolver normalized separators before absoluteness checks, letting UNC paths slip through
   as relative → resolver now rejects absolute paths in both flavors pre-normalization (test-found).
4. Timed-out processes reported a stale exit code → `ExecResult.exit_code` is now `None` on timeout.

## Phase 0 — completed scope

- [x] Git repository initialized; `.gitignore`, `.editorconfig`
- [x] Monorepo skeleton (`apps/web-ui`, `services/api`, `infrastructure`, `docs`, `scripts`)
- [x] FastAPI control plane scaffold: app factory, lifespan-managed DB engine/session factory
- [x] Health endpoints: `GET /healthz` (liveness), `GET /readyz` (readiness with PostgreSQL
      required; Redis/NATS optional-by-policy component probes with timeouts)
- [x] Structured JSON logging with request-ID propagation (`X-Request-ID` middleware + contextvar)
- [x] OpenTelemetry wiring (opt-in via `HARNESS_OTEL_ENABLED`, OTLP/HTTP) + collector config
- [x] SQLAlchemy 2.0 models for first durable entities: `projects`, `events`
- [x] Alembic migration `0001_initial_core` (tables + indexes incl. JSONB payload)
- [x] Docker Compose: PostgreSQL (pgvector image), Redis, NATS (JetStream); profiles for Temporal
      and OTel collector
- [x] Tests: unit (health, readiness fail-closed, request-ID, logging, config) + integration
      (DB round-trip, auto-skips without PostgreSQL)
- [x] Quality gates: ruff (lint+format), mypy, pytest; `scripts/check.ps1` local mirror
- [x] CI: GitHub Actions — python job (lint/types/migrations/tests with PostgreSQL service),
      web-ui build job, compose config validation
- [x] Web UI shell (React+TS+Vite) that renders live liveness/readiness from the API (proves UI↔API path)
- [x] Tracking docs: ARCHITECTURE.md, DEVELOPMENT.md, docs/REQUIREMENTS_MATRIX.md, this file

### Phase 0 validation log (all gates executed locally, 2026-09-14)

| Gate | Result |
| ---- | ------ |
| `ruff check services/api` | pass (clean after fixes) |
| `ruff format --check services/api` | pass |
| `mypy` (21 source files, pydantic plugin) | pass |
| `alembic upgrade head` against Docker PostgreSQL | pass — `0001` applied |
| `pytest -q` — 10 unit tests | pass (4.6s) |
| `pytest tests/integration` (DB round-trip vs live container) | pass |
| `uvicorn app.main:app` smoke: `/healthz` 200, `/readyz` 200 `ready=true` (postgres+redis+nats ok) | pass |
| `npm run build` (web-ui: tsc --noEmit + vite) | pass |
| `docker compose config -q` | pass |
| `docker compose up -d postgres redis nats` (all healthy) | pass |

Issues found and fixed during Phase 0 validation (kept for the record):

1. `readyz` originally returned HTTP 200 even when `ready: false` — the fail-closed contract is now
   enforced with HTTP 503 + full report body (covered by `test_readyz_fails_closed_and_reports_components`).
2. The PostgreSQL readiness probe could orphan a libpq connection thread with no timeout; engine now
   sets a libpq-level `connect_timeout` so unreachable hosts fail fast.
3. Windows port conflicts: a locally installed PostgreSQL owned `127.0.0.1:5432` (loopback binds beat
   Docker's wildcard mapping, causing misleading auth failures). Compose now maps
   **15432/16379/14222** and the defaults match (documented in DEVELOPMENT.md troubleshooting).

## Explicit NOT_IMPLEMENTED register (honesty list)

Everything below is **not implemented**; interfaces/contracts are described in ARCHITECTURE.md and
tracked in the requirements matrix. No placeholder code pretends otherwise.

- Editor features: file explorer, Monaco editing, tabs, search, terminal, Git UI (Phase 1)
- Language/toolchain registry and detection (Phase 1)
- Tauri desktop shell (Phase 1/10)
- Requirements/plan/task/agent/message/context/memory/artifact/tool/review/HITL data model
  (Phase 2; only `projects` + `events` exist now)
- Temporal workflows, checkpoints, pause/resume (Phase 3)
- Agent lifecycle engine, model adapters/routing, tool gateway, observation compression (Phase 3) — **delivered**
- Dynamic spawning, scheduler, leases, worktree integration (Phase 4) — **delivered**
- Model cost/token budget accounting ledger (deferred; tracked for Phase 5+)
- Tree-sitter/LSP/SCIP indexing, pgvector retrieval (Phase 5) — **delivered** (tree-sitter + ast
  symbols, pgvector hybrid retrieval, SCIP-JSON subset; LSP daemon + call/dependency graphs deferred)
- Sandbox runtime manager, quotas, port manager (Phase 6) — **delivered** (local + docker
  runtimes with isolation limits, lease-based execution quotas, TTL port allocator;
  gVisor/Firecracker-class isolation deferred)
- Playwright browser debugging, MCP gateway, web research evidence (Phase 7) — **delivered**
  (headless chromium sessions with console/network capture + screenshot artifacts; MCP stdio
  client + config-driven registry with per-server tool allowlists; fetch/search evidence
  packets. Deferred: video capture, remote/HTTP MCP transports, external search API providers)
- Requirement overseer, review/debate/adjudication (Phase 8) — **delivered** (traceability
  chain with evidence-only verification and fail-closed completion gate; 5-role review
  pipeline over the `decisions`/`reviews` tables; bounded credential-scanner security gate.
  Deferred: overseer as a continuous durable workflow (currently API-invoked), debate
  round concurrency policy per model family, secret-scan allowlist UX)
- Office/graph/timeline/diff UIs (Phase 9) — **delivered** (engineering-office sidebar with
  live team/timeline/oversight tabs, HITL approval cards, morphing state pills + non-breaking
  typography via Torph/Typehug; Playwright-driven UI smoke. Deferred: requirement-graph
  canvas visualization, per-agent chat threads, office websocket push (polled every 2.5 s))
- Packaging, diagnostics screen, export/import (Phase 10) — **delivered** (diagnostics
  endpoint + UI dialog, project export/import bundles with artifact inlining, restart
  recovery proof, secret-redacting log filter, prompt-injection detector, failure
  classifier + bounded recovery plans. Deferred: Tauri desktop shell (ADR-0008 — no Rust
  toolchain in this environment; the web UI ships standalone), full policy engine for
  SEC-007 (detector live), cross-machine bundle signing)

## Phase 7 — browser / MCP / web research (implemented 2026-09-16)

Per spec §20/§21/§22, three integration surfaces with the same fail-closed posture:

- **Browser debugging (FR-020)** — `app/browser/` (`session.py`, `manager.py`): headless
  Playwright chromium sessions with bounded buffers of console messages and failed/error
  network responses (`requestfailed` + status ≥ 400); screenshots and evidence persist as
  durable artifacts (`browser_evidence` kind) with `BROWSER_SCREENSHOT` audit events.
  Sessions are capped (5), manager shuts down with the app; routes fail closed with an
  actionable 503 when Playwright/chromium is missing. **Verified live**: real chromium
  loaded the running API's page, captured the 404 network failure, and produced a valid
  PNG artifact (`scripts/smoke_integrations.py`).
- **MCP gateway (FR-021)** — `app/mcp/` (`protocol.py`, `registry.py`): a minimal,
  auditable MCP stdio client (newline-delimited JSON-RPC 2.0: `initialize` →
  `notifications/initialized` → `tools/list` → `tools/call`, per-request timeouts, clean
  shutdown). Servers are config-driven (`HARNESS_MCP_CONFIG_PATH` JSON) with per-server
  tool allowlists; invocation enforces authorization → schema validation (object/required
  subset) → harness gateway policy patterns over the qualified name + arguments →
  `MCP_TOOL_CALLED` audit event; large raw results are stored as `mcp_result` artifacts and
  responses stay compact. Disabled by default (servers execute arbitrary commands) —
  503 fail-closed. **Verified live** against a real fake MCP server
  (`tests/mcp_echo_server.py`) speaking the protocol.
- **Web research (FR-022)** — `app/research/service.py`: `fetch_and_record` turns a page
  into a durable evidence packet — raw HTML as a `web_content` artifact, provenance
  (final URL, title, timestamp, sha256, excerpt, numeric confidence) and a T5 `evidence`
  context item for retrieval. Facts only; interpretation stays with the agent (spec §22).
  Fetches are bounded (scheme check, 2 MB cap, timeout) with a private-host guard
  (`HARNESS_RESEARCH_PRIVATE_HOSTS_ALLOWED`). Search uses a DuckDuckGo HTML adapter with
  provenance-marked results; it is network-dependent and fails loudly (502) rather than
  fabricating results. **Verified live** against the running API.

No migration needed this phase: sessions are runtime state (TerminalManager pattern) and
research evidence rides on the existing artifacts + context_items tables.

### Phase 7 validation log (2026-09-16)

| Gate | Result |
| ---- | ------ |
| ruff format/check | clean |
| mypy | clean |
| pytest — **173 passed** (6 MCP, 3 browser, 3 research new) | pass |
| `scripts/smoke_integrations.py` — chromium session + screenshot artifact + evidence packet + MCP fail-closed | **PASS** |
| regression smokes: editor / durable / scheduler / runtime | PASS |

## Phase 8 — quality & oversight (implemented 2026-09-16)

Per spec §23/§24, on top of the Phase-2 oversight schema (`decisions`, `reviews`,
`validations` — no migration needed) and the Phase-3 model registry:

- **Requirement overseer (FR-026/027, AC-011/015)** — `app/services/quality/overseer.py`:
  the full spec §23 chain (Requirement → AcceptanceCriterion → Task → Attempt → Evidence →
  VERIFIED/FAILED/UNKNOWN) computed from durable rows. A criterion is VERIFIED **only with
  evidence**: `verify_criterion` writes a `requirement`-kind Validation referencing an
  existing artifact — missing evidence is a 404, so the gate can never be satisfied by a
  claim. `completion_report` fails closed (409 + explicit blockers) when any mandatory
  requirement is unimplemented or any mandatory criterion is unverified; scope drift
  (tasks without requirement linkage) produces warnings plus a `SCOPE_DRIFT_ALERT` event.
  The allowed completion persists the report as a durable artifact (FR-027).
- **Review / debate / adjudication (FR-017, AC-012)** — `app/services/quality/review.py`:
  the spec §24 pipeline — independent reviewers (parallel, isolated contexts: proposal +
  evidence only, never each other's output) → adversarial critic (consolidated findings
  only) → evidence verifier → adjudicator. Every participant's verdict, summary, model and
  rounds persist to `reviews`; the `decisions` row flips to `accepted` only on
  evidence-backed approval. Model calls route through `ModelRegistry` with new default
  roles (`critic`, `evidence_verifier`) — config-driven, so different model families per
  role are a config change. Defensive JSON parsing maps unparsable output to
  `needs_evidence`; provider failure leaves the decision `proposed` (fail-closed) with a
  `REVIEW_FAILED_CLOSED` audit event. Rounds (≤3) and output tokens are bounded.
- **Security validation gate** — `app/services/quality/secrets.py` + `gates.py`: a bounded,
  dependency-free credential scanner (AWS/GitHub/Slack/Google/OpenAI-style keys, private
  keys, generic `api_key=...` assignments, bearer literals) with **redacted** findings —
  secrets are never copied into events or model context (SEC-003 spirit). Scans persist as
  `security`-kind Validations; the task completion gate (`POST /api/tasks/{id}/completion-gate`)
  requires a successful attempt with evidence artifacts, requirement linkage, and no failed
  security validation — explicit blockers, never silent passes (FR-026 enforcement point).
- New `quality` route area (`routes/quality/`: oversight, reviews, gates) + `schemas/quality/`
  + `services/quality/`, following the established layering; the API can run review
  pipelines with a deterministic scripted provider (`provider_override`) for tests/smokes.

### Phase 8 validation log (2026-09-16)

| Gate | Result |
| ---- | ------ |
| ruff format/check | clean |
| mypy (228 files) | clean |
| pytest — **190 passed** (17 new: overseer, review, gates, secrets) | pass |
| `scripts/smoke_oversight.py` — full §23/§24 chain live (block → scan → verify → review → complete) | **PASS** |
| regression smokes: editor / durable / scheduler / runtime / integrations | PASS |

## Phase 9 — office UI (implemented 2026-09-16)

Per spec FR-025/AC-014, the engineering-office sidebar in the web UI — no backend changes
needed (the Phase-8 oversight + existing list/event/HITL endpoints were already sufficient):

- **Engineering-office view** (`apps/web-ui/src/components/office/`): a fifth activity-bar
  view with three live tabs. *Team*: agent cards (name, role, model, lifecycle state as a
  Torph-morphing state pill) and a task board with requirement linkage, evidence badges and
  a "request review" action wired to the Phase-8 pipeline. *Timeline*: the durable event
  stream as a color-coded live feed with kind filters (agent/task/review/HITL/security).
  *Oversight*: the completion-gate card (allowed/blocked, coverage counters, explicit
  blockers/warnings, "generate completion report" → durable artifact), the requirements
  traceability tree with per-criterion states, and the review pipeline visualization
  (reviewers → critic → evidence verifier → adjudicator with verdict pills + findings).
- **HITL approval cards** (spec §25): pending requests render as aicss-style decision
  cards — risk badge, question, choices, note input, approve/reject — driving the durable
  `POST /api/hitl/{id}/decide` endpoint; the status bar surfaces "N approvals needed".
- **Live polling** (`state/officeStore.ts`): a dedicated zustand store refreshes agents,
  tasks, HITL, events and traceability every 2.5 s, with honest error surfacing.
- **AI-agent UI theme**: interaction patterns follow the aicss.dev block conventions
  (state pills, live dots, verdict pills, decision cards); Torph (`torph/react`) morphs
  state transitions and the sync footer; Typehug (`@typehug/en`) keeps label text
  typographically intact.
- **Fixed a real pre-existing bug**: the vite dev proxy stripped the `/api` prefix while
  FastAPI serves routes *with* it — every proxied UI call 404'd. The prefix is preserved
  now; the Playwright smoke exercises the UI through the proxy end to end.

### Phase 9 validation log (2026-09-16)

| Gate | Result |
| ---- | ------ |
| web-ui `npm run build` (tsc + vite) | pass |
| ruff format/check + mypy + pytest — **190 passed** | pass |
| `scripts/smoke_office.py` — Playwright-driven live UI: project open → office tabs → fail-closed gate + blockers → timeline events → HITL approve | **PASS** |
| regression smokes: editor / durable / scheduler / runtime / integrations | PASS |

## Phase 10 — hardening & packaging (implemented 2026-09-16)

The final spec phase, per §26 (failure & recovery), §31 (security), §29 (portability):

- **Failure classification + bounded recovery (FR-016, REC-001..003)** —
  `app/services/orchestration/recovery.py`: every failure detail is classified into one of
  the eleven spec §26 classes (MODEL_FAILURE … HITL_TIMEOUT, SECURITY_BLOCK) and mapped to
  a bounded recovery plan (retry / retry-alternate-model / recreate-runtime /
  rebuild-context / wait-for-dependency / integration-task / throttle / stop), with
  attempts capped (REC-002) and exhaustion escalating to replanning instead of looping
  (REC-003). Wired into the execution activity: failed attempts now carry a `recovery`
  decision; previous attempt identity/evidence is never rewritten (REC-001).
- **Restart recovery (AC-016, PERF-005)** — integration proof: a second app instance on
  the same database sees every durable row (requirements, tasks, attempts, events), the
  artifact content is readable by sha, and re-opening the project is idempotent.
- **Secret redaction in logs (SEC-003)** — `SecretRedactionFilter` in
  `core/logging.py` masks credential-shaped spans (scanner patterns) on every log record;
  plus `redact_span` on the scanner for whole-string masking.
- **Prompt-injection detection (SEC-006/007)** —
  `services/quality/security.py` scans tool outputs for instruction-override, system-prompt
  probing, role-override, exfiltration and policy-bypass attempts; findings attach to
  observations as `security_flags` — the system prompt and gateway policy stay authoritative.
- **Diagnostics (hardening)** — `GET /api/diagnostics`: fail-soft support bundle (app
  version/env/uptime, DB + migration head, artifact-store writability, temp dir, Redis,
  NATS, entity counts, feature flags) — every probe answers ok/down with detail, never a
  500. Surfaced as a dialog in the web UI from the status bar.
- **Project export/import (portability)** — `services/workspace/portability.py` +
  `GET /api/projects/{id}/export` / `POST /api/projects/import`: full durable state
  (requirements, criteria, plans, tasks, dependencies, attempts, oversight rows, events,
  context items) serialized to a JSON bundle with small artifacts inlined (base64, ≤1 MB;
  larger ones referenced by sha). Import restores as a brand-new project with fresh ids.
- **Tauri shell**: deferred honestly — no Rust toolchain in this environment; per ADR-0008
  the web UI ships standalone and the API is consumable as-is.

### Phase 10 validation log (2026-09-16)

| Gate | Result |
| ---- | ------ |
| ruff format/check + mypy (235 files) | clean |
| pytest — **210 passed** (20 new: recovery, redaction, injection, diagnostics, restart, portability) | pass |
| web-ui `npm run build` (tsc + vite) | pass |
| regression smokes: editor / durable / scheduler / runtime / integrations / office (Playwright) | PASS |

All ten spec phases are now delivered; the honesty list below records the deliberate
deferrals that remain.

## Post-completion deferred register

Everything above is delivered; these scoped-down items remain intentionally deferred and
tracked: LSP daemon + call/dependency graphs; external embedding providers;
gVisor/Firecracker-class isolation; browser video capture; remote/HTTP MCP transports;
overseer as a continuous durable workflow; requirement-graph canvas visualization; office
websocket push (polled); Tauri desktop shell (ADR-0008); full SEC-007 policy engine
(detector live); bundle signing for cross-machine import.

## Change log

- 2026-09-19 — Wave 11 acceptance: failure-injection harness, e2e journey with
  cross-surface agreement, P1 HITL/slot race fixes, idempotent execute,
  executable task payloads, health depth, shutdown/Redis/stress/history proofs,
  six release docs. Full suite green (see acceptance report).

- 2026-09-18 — Wave 5 evaluation audit: system verified intact (10/10 baseline
  green); added deterministic failure triage (§39) wired into suite rows +
  report tallies, and an orchestration/message metrics library (§12/§16/§42)
  with integration coverage. Full suite green (see validation below).

- 2026-09-18 — Wave 4 performance audit: measured-first fixes only (requirements
  N+1 → 2 queries, collection pagination everywhere, artifact streaming +
  ranges, worker concurrency knobs, evidence-aware retention); indexes audited
  with EXPLAIN (no new indexes justified); codeintel measured (no bottleneck);
  perf matrix + regression tests added. Full suite green (see validation
  below).

- 2026-09-18 — Wave 3 residuals: hermetic NATS tests clean up their durable
  consumers; intentional bus close no longer logs a spurious disconnect;
  per-command tool lifecycle events (`TOOL_STARTED/COMPLETED/FAILED`, bounded,
  timeline-only in the reducer) with backend + frontend coverage. Full suite
  green (see validation below).

- 2026-09-18 — Wave 3 realtime audit: architecture verified end-to-end against
  all acceptance criteria; closed live-NATS-path coverage (new hermetic e2e +
  load measurement), two missing §22 metrics, and the garbled
  `REALTIME_EVENTS.md` (reordered, DB-verified event vocabulary). Full suite
  green (see validation below).

- 2026-09-18 — Residuals completion: DB-restart recovery proven (best-effort
  heartbeats + `pool_pre_ping`; kill-backend and container-restart-mid-workflow
  chaos tests), HITL `cancelled` state + cancel endpoint (waiters fail closed),
  evidence-preserving automated rollback (per-attempt snapshots, `recovery/*`
  evidence branches, merge-conflict wiring; 5 rollback tests), scheduler
  follow-through proven for debugger/replan children. Full suite green (see
  validation below).

- 2026-09-18 — Wave 2 recovery-execution audit: verified the Temporal
  coordinator end-to-end and closed five genuine gaps (unreachable
  `replace_agent`/`spawn_debugger`/`request_hitl` decisions now emitted on the
  final attempt; replacement chain + session drain fixed; spawn terminals the
  parent with a child reference instead of a dead wait; policy denials are
  contained outcomes that classify to `SECURITY_BLOCK`; failure details carry
  exit code + stderr; dependency pre-wait check against already-finished deps).
  New `tests/integration/test_recovery_workflow.py` (7 Temporal tests:
  time-skipping + local test server). Full suite green: 296 unit, 162
  integration, 7 evals; ruff/mypy clean. No automated ROLLBACK by design
  (evidence preservation; documented in `docs/RECOVERY.md`). DB-restart chaos
  remains the only residual.

- 2026-09-18 — Production-blocker remediation (prioritized list from the Wave 1
  verification): per-IP rate limiting (429 + `Retry-After`), provider
  retry/backoff with jitter + per-route timeouts, per-agent/per-execution token
  budgets, diagnostics off-loop probes + docker hardening flags (`--cap-drop ALL`,
  `--pids-limit`, `--read-only`, optional `--user`), realtime DLQ, port/worktree
  idempotency keys (alembic `0011`, live DB migrated), OTel spans on all 15 worker
  activities, kill-9 + NATS-loss chaos tests, context truncate-before-drop
  compaction, agent capability scopes (`read < write < admin`, SR-14), task-list
  pagination, curated OpenAPI surface. Incidental finds fixed: broker nats-py 2.x
  `add_stream` incompatibility (delivery always 503'd) and unbounded NATS
  connects. Docs: `OPERATIONS.md` §§2.7–2.8/5–6, risk register SR-06/SR-07/SR-14,
  remediation-plan delivery log with variances. Deferred register below unchanged
  except prompt-injection *response* (still detector-only) and DB-restart chaos.

- 2026-09-16 — Phase 10 hardening & packaging: failure classification into the eleven
  spec §26 classes with bounded recovery plans wired into the execution activity,
  restart-recovery integration proof (AC-016/PERF-005), secret-redacting log filter
  (SEC-003), prompt-injection detector on tool observations (SEC-006/007 partial),
  fail-soft diagnostics endpoint + web UI dialog, and project export/import bundles.
  Tauri shell deferred honestly (no Rust toolchain; ADR-0008). All ten spec phases are
  now delivered. Verified: ruff/mypy clean, pytest 210 passed, web build green, all
  smokes green.

- 2026-09-16 — Phase 9 office UI: engineering-office sidebar with live team/timeline/
  oversight tabs, HITL approval cards, Torph/Typehug-powered interactive typography, and
  a Playwright-driven live UI smoke (`scripts/smoke_office.py`) plus a short runner
  (`scripts/run-office-smoke.ps1`). Fixed the vite dev proxy prefix bug that 404'd every
  proxied UI call. New web-ui deps: `torph`, `@typehug/en`. Verified: web-ui build, ruff/
  mypy clean, pytest 190 passed, office UI smoke green with all regression smokes.

- 2026-09-16 — Phase 8 quality & oversight: requirement overseer with machine-checked
  traceability and an evidence-only, fail-closed completion gate (FR-026/027, AC-011/015),
  the 5-role review/debate/adjudication pipeline persisted to decisions/reviews with
  config-driven per-role models (FR-017, AC-012), and a credential-scanner security gate
  with redacted findings. New `quality` route/service/schema area. Verified: ruff/mypy
  clean, pytest 190 passed, oversight smoke green live with all regression smokes.

- 2026-09-16 — Phase 7 integrations: Playwright browser debugging (headless chromium
  sessions, console/network capture, screenshot/evidence artifacts), an MCP stdio gateway
  (minimal JSON-RPC client, config-driven registry, per-server tool allowlists, schema
  validation, audit events, fail-closed when disabled), and web research evidence packets
  (fetch → artifact + T5 provenance context item; bounded; DDG search adapter). New deps:
  `playwright`. Verified: ruff/mypy clean, pytest 173 passed, integrations smoke green
  (real chromium + real fake MCP server) with all prior smokes still green.

- 2026-09-16 — Structure audit round: `db/models/`, `services/`, and `schemas/` grouped into the
  same six domain subpackages as the routes (core/workspace/planning/orchestration/intelligence/
  execution). The models registry (`db/models/__init__`) keeps a flat re-export surface, so
  `from app.db.models import X` consumers are untouched; service/schema imports were rewritten
  to their new paths (43 files). Also: Windows-safe smoke output (ASCII) and docs updated.
  Verified: ruff/mypy clean, pytest 158 passed, and all five live smokes green
  (editor/durable/scheduler/intelligence/runtime).

- 2026-09-16 — **Wave 2 executable recovery** (post-spec production plan, W2): the Temporal
  task workflow is now the authoritative recovery coordinator — the recovery decision returned
  by each failed attempt is actually EXECUTED (it was advisory before). The pure policy core
  (`services/orchestration/recovery.py`) grew deterministic decisions (`recovery_decision`:
  action ladder per failure class with real attempt counts, parameters, budget sensitivity and
  a deterministic `recovery_id`), bounded exponential backoff with hash-free jitter, and a
  non-retryable set (SECURITY_BLOCK/HITL_TIMEOUT/BUDGET_EXCEEDED → terminal, never retried).
  New durable executor activities (`durable/activities/recovery.py` + a HITL recovery gate):
  budget check against the cost ledger before expensive actions (insufficient → durable HITL
  gate, fail-closed), debugger/integration child tasks with structured evidence, replan
  follow-up tasks on ladder exhaustion (REC-003), terminal-failure evidence payloads, agent
  session drain for replacement (replaces_agent_id now driven), dependency resolution via
  durable signals (blocked tasks hold no worker) and idempotency keys on every effect
  (activity replays never duplicate). Recovery events (RECOVERY_SELECTED, RETRY_STARTED,
  MODEL_SWITCHED, AGENT_REPLACED, DEBUGGER_SPAWNED, TASK_REPLANNED, DEPENDENCY_*,
  HITL_RECOVERY_*, TASK_TERMINALLY_FAILED) are queryable via the event stream. Docs:
  `docs/RECOVERY.md` (decision table + flow diagram). Tests: recovery units (28) + executor
  integration suite (9, incl. idempotency and HITL flows) + a live-Temporal recovery smoke
  (`scripts/smoke_recovery.py`, battery 8/8). Verified: ruff/mypy clean (243 files),
  pytest 283 passed.

- 2026-09-16 — **Wave 1 security hardening** (post-spec production plan, W1): optional
  bearer-token auth covering every `/api/*` route AND WebSocket handshakes (`app/api/security.py`
  — constant-time compare, subprotocol transport for browsers, 4401 close code, no secrets in
  logs; token empty = loopback-only local mode, and startup now **refuses a non-loopback bind
  without a token**); deny-by-default agent environment sanitizer (`app/runtime/env_sandbox.py`)
  wired into `run_process` — agent/tool subprocesses no longer inherit host secrets
  (`HARNESS_OPENAI_API_KEY` etc.); a DNS-aware SSRF guard (`app/research/ssrf.py`) validating
  scheme/host/resolved IPs (v4+v6, mapped, link-local, metadata) with **per-hop redirect
  validation** replacing blind `follow_redirects`, private destinations denied by default
  (`HARNESS_RESEARCH_PRIVATE_HOSTS_ALLOWED=false`); explicit CORS allow-list (no wildcard).
  Web UI: token transport (`localStorage` + `Authorization` header + WS subprotocol, terminal
  4401 hint). Tests: 47 new (env/SSRF units + auth/CORS/WS/fail-closed-bind integration);
  also fixed a latent test-isolation bug (pytest tmp-dir numbering can repeat across sessions;
  project fixtures now open unique repo roots). Verified: ruff/mypy clean, **pytest 262
  passed**, web-ui lint+build green.

- 2026-09-16 — Phase 6 execution plane: runtime manager (local + docker backends with
  network-none/memory/CPU/no-new-privileges isolation — docker verified live), per-project
  execution quota slots built on runtime-kind leases, and the central port allocator with
  live bind-probe + TTL expiry (spec §19/§19.1) — all four live smokes green.

- 2026-09-15 — Phase 5 code intelligence: tree-sitter/ast symbol index with hash-driven
  incremental reindexing (PERF-008), hybrid lexical+pgvector retrieval wired into the agent
  context T3 tier, SCIP-JSON export, and the model cost ledger with an optional per-task token
  budget gate (spec §32) — live smoke green.

- 2026-09-15 — Maintainability restructure: the 585-line `durable/activities.py` monolith split
  into an `app/durable/activities/` package by concern (context/tasks/agents/execution/hitl, with
  the public activity surface re-exported); the 19 flat route modules grouped into four domain
  subpackages (`core/`, `workspace/`, `planning/`, `orchestration/`) exposing `routers`; tests
  renamed/split by domain (`test_leases`, `test_scheduler`, `test_message_delivery`,
  `test_agent_runtime` — no more phase-named files) with a shared `project` fixture; web-ui
  components grouped into `editor/`, `panels/`, `shell/`; scheduler/agents service cleanups
  (closure-in-loop removed, imports hoisted). All gates green and all three live smokes
  (editor/durable/scheduler) pass after the restructure.
- 2026-09-15 — Phase 4 COMPLETE: resource leases (TTL + renewal + deterministic batch), bounded
  scheduler (global/role caps, lease-aware, fail-closed), spawn policy, NATS JetStream message
  fan-out, worktree isolation + controlled integration queue with explicit conflict tasks —
  scheduler smoke green through live Temporal.
- 2026-09-15 — Phase 3 COMPLETE: agent runtime (lifecycle, model routing with fallback, tool
  gateway + HITL fail-closed gates, context broker, observation compression, pause/resume,
  supervision, agent replacement) — live Temporal smoke green.

- 2026-09-14 — Phase 2 durable core implemented and validated (full §29 schema, artifacts,
  requirement→plan→task graph, Temporal task execution with attempts/evidence; durable smoke green).
- 2026-09-14 — Phase 1 conventional editor implemented and validated (projects/explorer/Monaco
  tabs/search/Git/PTY terminals/toolchain registry+run; smoke script green).
- 2026-09-14 — Phase 0 architecture foundation implemented and validated.

# Implementation Status

**Generated:** 2026-09-16 · **Spec:** v1.0 (2026-09-14) · **Current phase:** 6 — Execution plane (complete)

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
| 7 | Browser / MCP / web research | NOT_STARTED | Playwright, MCP registry, evidence packets |
| 8 | Quality & oversight | NOT_STARTED | Requirement overseer, review/debate, security validation |
| 9 | Office UI | NOT_STARTED | Live agents, graph, timeline, diff/review |
| 10 | Hardening & packaging | NOT_STARTED | Recovery/security testing, Tauri packaging, diagnostics |

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
- Playwright browser debugging, MCP gateway, web research evidence (Phase 7)
- Requirement overseer, review/debate/adjudication (Phase 8)
- Office/graph/timeline/diff UIs (Phase 9)
- Packaging, diagnostics screen, export/import (Phase 10)

## Next phase entry criteria (Phase 7)

Phase 6 gates green → begin Phase 7 browser/MCP/web research:
Playwright browser debugging with console/network inspection and screenshot artifacts (FR-020),
MCP tool discovery/invocation/permission controls wired into the gateway policy (FR-021, SEC-001),
and web research with evidence/provenance packets (FR-022). Deferred: LSP daemon + call/dependency
graphs, external embedding providers.

## Change log

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

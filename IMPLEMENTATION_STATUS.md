# Implementation Status

**Generated:** 2026-09-14 · **Spec:** v1.0 (2026-09-14) · **Current phase:** 1 — Conventional editor (complete)

## Phase overview

| Phase | Deliverable | Status | Notes |
| ----- | ----------- | ------ | ----- |
| 0 | Architecture foundation | **COMPLETE** | Repo, CI, service scaffold, migrations, tests, compose, observability skeleton, docs |
| 1 | Conventional editor (no AI required) | **COMPLETE** | Projects, explorer, Monaco editor+tabs, search, Git panel, terminals (real PTY), toolchain registry/detection/run, quick-open |
| 2 | Durable core (PostgreSQL entities + artifacts) | NOT_STARTED | Remaining entities from spec §29; Temporal integration |
| 3 | Agent runtime + durable orchestration | NOT_STARTED | Lifecycle, model adapter, tool gateway, context broker, pause/resume |
| 4 | Multi-agent orchestration | NOT_STARTED | Spawn policy, scheduler, messaging, worktrees, leases |
| 5 | Code intelligence | NOT_STARTED | Tree-sitter, LSP, SCIP, retrieval |
| 6 | Execution plane | NOT_STARTED | Containers, quotas, port manager |
| 7 | Browser / MCP / web research | NOT_STARTED | Playwright, MCP registry, evidence packets |
| 8 | Quality & oversight | NOT_STARTED | Requirement overseer, review/debate, security validation |
| 9 | Office UI | NOT_STARTED | Live agents, graph, timeline, diff/review |
| 10 | Hardening & packaging | NOT_STARTED | Recovery/security testing, Tauri packaging, diagnostics |

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
- Agent lifecycle engine, model adapters/routing, tool gateway, observation compression (Phase 3)
- Dynamic spawning, scheduler, leases, worktree integration (Phase 4)
- Tree-sitter/LSP/SCIP indexing, pgvector retrieval (Phase 5)
- Sandbox runtime manager, quotas, port manager (Phase 6)
- Playwright browser debugging, MCP gateway, web research evidence (Phase 7)
- Requirement overseer, review/debate/adjudication (Phase 8)
- Office/graph/timeline/diff UIs (Phase 9)
- Packaging, diagnostics screen, export/import (Phase 10)

## Next phase entry criteria (Phase 2)

Phase 1 gates green (see validation logs) → begin Phase 2 durable core:
complete the PostgreSQL entity set from spec §29 (requirements, plans, tasks, task_attempts,
agents, agent_sessions, messages, context_items, memories, artifacts, tool_definitions, tool_calls,
worktrees, resources, decisions, reviews, validations, hitl_requests, runtime_instances,
toolchains), artifact storage, then Temporal integration.

## Change log

- 2026-09-14 — Phase 1 conventional editor implemented and validated (projects/explorer/Monaco
  tabs/search/Git/PTY terminals/toolchain registry+run; smoke script green).
- 2026-09-14 — Phase 0 architecture foundation implemented and validated.

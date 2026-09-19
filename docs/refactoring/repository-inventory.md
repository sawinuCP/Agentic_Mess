# Repository Inventory (Phase A — 2026-09-19)

Evidence: AST import scan of all 214 backend + 88 frontend modules
(`forensics.json`, generated outside the repo), route registration, barrel
analysis, test/docs/script/migration listings. Scale: backend 214 source /
92 tests, frontend 88 source / 17 test files, 24 scripts, 38 docs,
11 migrations. Baseline: everything green (see `BASELINE.md`).

Status values: ACTIVE / DUPLICATE / DEPRECATED / ORPHANED / EXPERIMENTAL /
GENERATED / TEMPORARY / TEST_ONLY / DOCUMENTATION_ONLY / UNKNOWN.

## Top-level layout

| Path | Type | Purpose | Status | Recommendation |
|---|---|---|---|---|
| `services/api/app/` | backend | FastAPI modular monolith (all server code) | ACTIVE | KEEP structure; fix boundary violations per plan |
| `services/api/tests/` | tests | 45 integration + 43 unit + evals + fixtures | ACTIVE | KEEP; reorganize by boundary later (plan) |
| `services/api/alembic/versions/` | migrations | 0001–0011, head current | ACTIVE | KEEP; never rewrite history |
| `apps/web-ui/src/` | frontend | React 18 + Vite + TS + Zustand, no router lib | ACTIVE | KEEP; feature-boundary cleanup per plan |
| `scripts/` | ops | 24 scripts: 20 Playwright smokes + benchmark + runners + validators | ACTIVE | KEEP; archive list in plan |
| `docs/` | docs | 38 markdown files (see §Documentation) | MIXED | Consolidate hierarchy (plan) |
| `infrastructure/` | infra | Only `observability/otel-collector.yaml`; compose file lives at root | ACTIVE (thin) | KEEP; consider co-locating compose |
| `docker-compose.yml` | infra | PG/Redis/NATS/Temporal services | ACTIVE | KEEP |
| `.github/workflows/ci.yml` | CI | Backend + frontend + eval gates | ACTIVE | KEEP; verify content in plan |
| `data/` | runtime data | Local artifacts/worktrees (git-ignored) | GENERATED | KEEP (ignored) |
| `tmp-w3-*.log` (root) | logs | Leftover debug output from Wave 3 work | TEMPORARY | DELETE (git-ignored `*.log`, safe) |
| `AI_Harness_*Specification.docx/.md` | spec | Original product spec, two formats | DOCUMENTATION_ONLY | KEEP one; mark hierarchy |

## Backend domains (`services/api/app/`)

| Module | Files | Purpose / owner | Status | Recommendation |
|---|---|---|---|---|
| `main.py`, `__init__.py` | 2 | App factory, lifespan, middleware wiring | ACTIVE | KEEP |
| `api/` | 4 | Middleware (RequestID/Metrics/RateLimit), security, deps | ACTIVE | KEEP |
| `api/routes/*` (35 files, 8 groups) | 35 | HTTP surface: core/workspace/planning/orchestration/execution/intelligence/quality/research/browser/mcp | ACTIVE | KEEP; audit list in §API |
| `agents_runtime/` (8) | 8 | Gateway (policy), lifecycle, context broker, models registry/providers, observations | ACTIVE | Core domain — boundary-guard (plan R-06) |
| `services/*` (26) | 26 | Application services per area (planning, orchestration, workspace, quality, execution, intelligence, core) | ACTIVE | KEEP; note services↔models coupling (§Architecture) |
| `db/models/*` (19) | 19 | SQLAlchemy entities by area; barrel `app.db.models` | ACTIVE | KEEP; repository layer is future work, not this plan |
| `db/base.py` | 1 | Engine/session factory/Base (`pool_pre_ping`) | ACTIVE | KEEP |
| `durable/` (4 + activities/7) | 11 | Temporal workflows, 19 activities, worker, client | ACTIVE | KEEP; determinism guard in plan |
| `realtime/` (7) | 7 | Envelope, bus, gateway, SSE route, bridge, retention | ACTIVE | KEEP |
| `core/` (6) | 6 | Config, errors, logging, metrics, observability | ACTIVE | KEEP |
| `runtime/` (4) | 4 | Process runner, runtimes (local/docker), env sandbox | ACTIVE | KEEP |
| `toolchains/` (6) | 6 | Language detection/registry/overrides/execution (domain) | ACTIVE | KEEP; `services/workspace/toolchains.py` is its app service, not a duplicate |
| `codeintel/` (6) | 6 | Parser, indexer (incremental), retrieval, embeddings, SCIP | ACTIVE | KEEP |
| `evaluation/` (11) | 11 | Suite runner, dataset EVAL-001..010, scorecard, triage, metrics, reports, CLI | ACTIVE | KEEP |
| `chaos/` (2) | 2 | Failure-injection harness (settings-gated) | ACTIVE | KEEP |
| `schemas/*` (21) | 21 | Pydantic DTOs mirroring route groups | ACTIVE | KEEP; check DTO/model drift in plan |
| `artifacts/`, `files/`, `gitops/`, `terminal/`, `browser/`, `messaging/`, `research/`, `mcp/`, `tasks/` | 2–3 ea | Infrastructure capabilities (store, fs, git, pty, playwright, NATS-msgs, fetch, MCP, task DAG) | ACTIVE | KEEP as infra layer |
| `core/errors.py` + `ArtifactStoreError`, `GitError`, `PolicyViolation` | — | Error taxonomy: `DomainError` base + domain kinds | ACTIVE | Unify listing in target arch; no rewrite |

Import-coupling facts (measured): `app.db.models` ← 56 modules, `app.core.errors` ← 38,
`app.api.deps` ← 27, `app.db.base` ← 16. Services import ORM models directly
(no repository layer) — the single most pervasive boundary smell; scheduled as
P2 (plan R-07), not P0 (all tests green, no corruption).

## Frontend (`apps/web-ui/src/`, 88 files)

| Area | Files | Purpose | Status |
|---|---|---|---|
| `state/` (12) | store, officeStore, layout, theme, monacoSetup + tests | Zustand stores, persistence, editor setup | ACTIVE |
| `api/` (5) | client, sse, errors + tests | REST + SSE transport, error mapping | ACTIVE |
| `commands/` (4) | registry, taskCommands + tests | Palette command model (30 static + dynamic) | ACTIVE |
| `office/` (4) | selectors + tests, useBulkAction, derivationPerformance | Pure projections over durable state | ACTIVE |
| `components/shell` (13) | App shell, palette, dialogs, status, panels infra | ACTIVE |
| `components/office` (11) | Team/timeline/comms/oversight, agent detail, dialogs | ACTIVE |
| `components/panels` (11) | Explorer/run/problems/settings/runtime + tests | ACTIVE |
| `components/graph|history|editor|command` (2/3/2/1) | Graph, history/replay, Monaco, Command Center | ACTIVE |
| `graph/`, `timeline/`, `intent/`, `context/`, `command/` | Pure builders/models + tests | ACTIVE |
| `components/shared` (1) | ArtifactMeta | ACTIVE (thin — good) |

No `utils/helpers/common` dumping grounds exist (verified). No duplicate
state systems (single Zustand). No router library (view-state driven).

## Routes (103 paths, OpenAPI-verified)

Groups: core (health/readiness/diagnostics/events/artifacts/metrics/retention),
workspace (projects/files/git/terminal/toolchains/portability), planning
(requirements/plans/tasks), orchestration (agents/sessions/messages/HITL/
leases/scheduler/worktrees/knowledge), execution (ports/runtimes), intelligence
(costs/index/symbols/retrieval), quality (gates/overseer/reviews),
research, browser, mcp. Full per-endpoint table belongs in the target-architecture
API-boundary section (Phase D), not here.

## Tests (92 backend files + 17 frontend)

* Backend unit (43): policy cores, tokenizers, reducers-in-spirit, config,
  lifecycle matrix, evaluation classifiers — deterministic, no infra.
* Backend integration (45): live PG/NATS/Temporal/Docker; fixtures via API.
* `tests/evals/test_golden.py`: scripted repairs on fixture repos.
* `tests/fixtures/e2e_projects.py`: generated fixture repos (not committed blobs).
* Frontend (17 files, 144 tests): node-env pure units (reducer, parser,
  selectors, commands, metrics) + Playwright Python smokes in `scripts/`.
* No obsolete test files found (all collect; suite green).

## Scripts (24)

20 Playwright smokes (palette/office/task-controls/graph/history/editor/
recovery/runtime/scheduler/shell/oversight/integrations/intelligence/agent-office/
command-center/panel-retention/project-picker/design-tokens), `benchmark_wave4.py`,
`run-*.ps1`, `check.ps1`, `validate_wave1_live.py`. All referenced by docs/CI
or the validation plan. Status: ACTIVE. Recommendation: KEEP; archive list
only if a smoke goes permanently red (none are).

## Migrations (11, `0001`–`0011`)

Linear history, head current on live DB. `0011_idempotency_keys` uses partial
unique indexes (autogenerate `alembic check` reports pre-existing drift on
untouched tables — cosmetic, not a migration bug). Recommendation: KEEP
history immutable; forward-only.

## Documentation (38 files)

Full classification in Phase A-docs section below. Headline: one spec pair
(.md + .docx duplication), wave/audit docs (CURRENT), per-view architecture
docs (CURRENT), `IMPLEMENTATION_STATUS.md` changelog (CURRENT), risk registers
(CURRENT), no `docs/architecture/` hierarchy yet (target arch creates it).

## Generated / temporary

* `__pycache__`, `.venv`, `node_modules`, `dist`, `.ruff_cache`, `.mypy_cache`,
  `.pytest_cache`, `data/` — all git-ignored. Verified: `git status` clean
  except intended work.
* Root `tmp-w3-*.log` — ignored (`*.log`) but clutter: DELETE (3 files, safe).
* No `.bak/.old/.generated`, notebooks, screenshots, or coverage artifacts
  in the tree.

## Dependencies (manifests)

* Backend: single `services/api/pyproject.toml` (no requirements.txt sprawl).
* Frontend: `apps/web-ui/package.json` (+ lockfile).
* Full unused-dependency proof requires install-graph analysis — scheduled as
  plan item R-11 (P3), not asserted here.

## Duplication verdicts (proven, not guessed)

* `app/toolchains/*` vs `services/workspace/toolchains.py`: NOT duplicates
  (domain vs application service). KEEP both, document the layering.
* `ArtifactStoreError`/`GitError`/`PolicyViolation` vs `DomainError`: all
  subclass `DomainError` (verified) — one taxonomy, KEEP.
* `TOOL_RUN_COMPLETED` (toolchain runs) vs `TOOL_STARTED/COMPLETED` (agent
  commands): overlapping names, different producers/meanings — rename
  candidate in plan (P3), not a merge (different semantics).
* No duplicate utils, stores, routers, brokers, or state systems found.

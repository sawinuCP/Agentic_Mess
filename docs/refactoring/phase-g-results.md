# Phase G Results (2026-09-19)

## 1. Architectural Debt Before

Phase F left one P2 (pervasive service → ORM/model coupling, ~30 call sites),
13 of 25 use cases PARTIAL (backend-proven, UI/live leg unasserted), a
713-line `CenterView` watch-item, 4 AST boundary tests, and a frozen Wave-12
worktree (uncommitted paths, do-not-touch without demonstrated cause).

## 2. Architectural Debt Addressed

* 3 cross-domain read couplings moved behind owner contracts (C1–C3).
* 1 frontend direct-fetch straggler routed through `api/client` (R-04 class).
* Agent lifecycle negative space locked (exhaustive illegal-transition guards).
* 3 critical use-case flows gained true API→persistence→events→verification
  E2E proof with failure scenarios.
* 1 Wave-12 correctness break (task-guard vs workflow entry) repaired.

## 3. Refactors Implemented

| ID | Change | Files |
|---|---|---|
| C1 | Worktree release resolves git root via `projects.require_project_root` (new owner getter); route drops inline `db.get(Project)` + local 404 | `services/workspace/projects.py`, `routes/orchestration/worktrees.py` |
| C2 | Event reads own `services/core/event_queries.py::query_events` (new); route translates only | new `event_queries.py`, `routes/core/events.py` |
| C3 | Symbol reads own `indexer.search_symbols/file_symbols` (new owner helpers); route translates only | `codeintel/indexer.py`, `routes/intelligence/symbols.py` |
| W1 | Workflow entry routes `pending` through `ready` (deterministic branch on `load_task_activity.status`) | `durable/workflows.py` (Wave-12 path, justified §19) |
| F1 | `GitView` diff handler uses `api.readFile` instead of inline `fetch` | `apps/web-ui/.../panels/GitView.tsx` |

No ports/interfaces/factories added; no repositories; no service layers; no
microservices. Each refactor is one boundary, independently revertible.

## 4. Refactors Intentionally Not Implemented

* Repository-per-table port; generic service layer; microservices (per no-go).
* `supervise_sessions` policy extraction (covered, churn buys little).
* `retrieval.py` ranking extraction (Wave-12-frozen + PG-pinned Case C).
* `CenterView` split (coherent composition root — see §16 below).
* New frontend AST rules (no demonstrated violation class remains).
* Remaining 10 PARTIAL use cases → E2E (out of scope: top 3 flows only).

## 5. Why They Were Not Implemented

Every declined item failed the "smallest useful change" test: proven
non-duplicates, accepted Case C persistence services, or watch-items without
a demonstrated violation. Evidence in `phase-g-debt-ranking.md`.

## 6. Dependency Boundary Changes

Routes no longer SELECT `Event`/`Symbol`/`SymbolFile`/`Project` inline in the
three moved cases; they depend on owner-context functions. `agents_runtime`
still DB-free (CI test green); workflows still deterministic (CI test green).

## 7. Persistence Boundary Changes

Read-only moves: zero transaction change (no commit/rollback moved; new
helpers take the caller's `Session`). Transaction ownership reconfirmed:
services/activities own commit per operation; routes never commit (except the
pre-existing artifact-report persist in oversight, unchanged); events written
via `emit_event` (in-tx) or `record_event` (own session, failures logged).

## 8. Agent Architecture Changes

None structural. Verified: spawn/session/heartbeat/supervision stay in
`services/orchestration/agents.py` + `agents_runtime/lifecycle.py`; runtime
never owns tasks/messages/artifacts. Guard coverage extended (§6 unit file).

## 9. Tool Architecture Changes

None structural. Verified: `agents_runtime/gateway.py` remains the single
choke point (policy → allowlist → HITL gate → runner → normalized
observation → artifact); tool-specific logic stays in adapters. F1 keeps the
UI on the client contract.

## 10. Model Provider Changes

None. Verified: registry → provider adapters; orchestration calls
`complete()` only; retry/fallback/budget behavior covered by existing unit +
chaos tests (green).

## 11. Context Architecture Changes

None. Verified: `context_broker.assemble` owns retrieval/ranking/budgeting;
runtime requests bundles. No scattered truncation logic found.

## 12. Recovery Architecture Changes

Policy core untouched (`recovery.py` pure, deterministic). Executor path
repaired (W1): workflow entry now lawful under the task guard. No second
recovery engine; ladders/termination proven by the green recovery suite.

## 13. E2E Use Cases Strengthened

* UC-02 + UC-03 + UC-14 + UC-22 (requirement → plan → evidence → verify →
  traceability VERIFIED → completion 200 + streamed report artifact).
* UC-04 + UC-06 (spawn → session → heartbeat → durable message → inbox +
  conversation replay → clean end).
* C2/C3 regression net (event paging asc/desc/since_seq; index → symbol
  search → file symbols through the moved contracts).

## 14. E2E Results

`test_phase_g_critical_flows.py`: 3/3 pass (live PG). Each asserts durable
state (rows, events, sessions, artifacts, verification state), not just HTTP
codes. Negative paths: 409-before-proof, 404-without-evidence,
422-vague/422-bad-link, 404-unknown-agent/session — all verified.

## 15. Tests Before vs After

| Suite | Before | After |
|---|---|---|
| Backend unit | 315 | 323 (+5 lifecycle guards; +3 from Wave-12's task-lifecycle file present in tree) |
| Backend integration | 217 claimed (incl. docker file) | 217/217 green excl. docker-runtime file (214 pre-existing + 3 new Phase G flows; docker file needs a daemon, as at baseline) |
| Backend evals | 7 | 7 |
| Frontend vitest | 144 | 144 |
| Lint (ruff + format) | clean | clean (311 backend files) |
| Typecheck (mypy) | clean | clean (215 files) |
| tsc / eslint / vite build | clean | clean |
| Alembic | 0011 head | 0011 head |

Mid-phase full run surfaced 13 failures, all
`Invalid task transition: pending → running` from Wave-12's new guard vs the
old workflow entry — repaired (W1 + lawful test close-out); final full run:
**217/217 green** (docker-runtime file excluded: needs Docker daemon, as at
baseline).

## 16. Performance Before vs After

No measurable change: read-only query moves (same SQL), one extra activity
only on the `pending`-entry path, no new indexes/migrations. Perf-marked
suites (graph/timeline/realtime-load/task-query) green.

## 17. Remaining Architectural Debt

* P2 service→ORM coupling persists as accepted discipline (R-03 as-touched).
* `supervise_sessions` policy inline (watch).
* Codeintel SQL in domain (accepted Case C).
* 10 PARTIAL use cases still lack UI/live legs (listed in use-case-coverage).
* `health.ts` fetch (justified transport, not debt).

## 18. Remaining Partial Use Cases

UC-03/05/08/10/12/13/16/18/22/24 keep backend-only proof (UC-02/04/06/14
strengthened here). UC-16 stays environment-dependent (honest chromium skip).

## 19. Remaining Risks

* Wave-12 work still uncommitted: its task-guard/workflow hardening is now
  consistent at the entry path, but further Wave-12 edits could re-skew the
  table vs callers — re-run the Temporal suites after any Wave-12 touch.
* One justified Wave-12 touch made (`durable/workflows.py` entry); the rest
  of the Wave-12 boundary is byte-identical (verified via `git status` +
  targeted diff).
* `CenterView` (738 lines incl. helpers) stays a watch-item: split only on a
  demonstrated feature-boundary violation, never on size.

### CenterView decision (G16, recorded)

Responsibilities: command input + intent dispatch composition (modeOf,
relativeTime, LiveTaskStatus helpers). State: stores only (`useStore`,
`useOffice`); no local domain state. Events: none constructed. Rendering:
one view, no reusable sections trapped inside. Business logic: zero — intent
classification/planning/context live in `intent/*` + `context/assemble`.
API: exclusively `api/client`. Verdict: coherent composition root —
**leave alone**.

### Frontend boundary review (G17, recorded)

Audit: no `fetch(` in views except the fixed GitView straggler; `health.ts`
is transport, not bypass; SSE only via `api/sse`. No new AST rules added —
no demonstrated violation class. Existing backend AST guards (4) green.

## 20. Recommended Next Step

Commit Phase G as 5 small commits (§G20), then decide from this evidence:
either continue Wave-12 (re-run Temporal suites after every touch) or pick
the next 2–3 PARTIAL use cases for E2E. No further architecture refactoring
without a new demonstrated violation (STOPPING CONDITION).

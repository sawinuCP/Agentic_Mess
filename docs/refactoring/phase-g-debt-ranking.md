# Phase G Debt Ranking (G1–G2 — measured, not assumed)

Method: AST import scan of `services/*` + `api/routes/*` (2026-09-19),
classified per Phase G2 categories. Wave-12 uncommitted paths are excluded
as refactor targets — they are a frozen boundary.

## Classification

### Category A — Legitimate persistence application service (KEEP)

The service IS the persistence owner; the query is its public contract.

- `services/workspace/projects.py`, `services/planning/requirements.py`,
  `services/planning/plans.py`, `services/orchestration/agents.py`,
  `services/orchestration/messages.py`, `services/quality/overseer.py`,
  `services/quality/gates.py`, `services/intelligence/costs.py`,
  `services/core/artifacts.py`, `codeintel/indexer.py` (writes its own tables).
- Most route modules import `Project`/`Session` only for `Depends(get_project)`
  type hints — no query, no violation.

Disposition: KEEP. No repository layer. Rule R-03 (as-touched helpers) stands.

### Category B — Business logic coupled to ORM (watch, not selected)

- `services/orchestration/agents.py::supervise_sessions`: policy (stale cutoff,
  state transitions running→lost/failed) inline with UPDATE loop. Impact:
  medium; testability: needs DB today. Smallest change would extract
  `stale_sessions(rows, cutoff)` pure selector — but the function is already
  covered by `test_agent_sessions_api.py` and churn buys little. DECLINED.
- `codeintel/retrieval.py` ranking: blocked by Wave-12 + sqlite-incompatible
  JSONB pins it to PG (Case C accepted in Phase F). DECLINED.

### Category C — Cross-domain persistence coupling (SELECTED, 3 items)

Ranked by architectural impact × testability × change cost × risk:

| # | Violation | Impact | Testability | Cost | Risk | Verdict |
|---|---|---|---|---|---|---|
| C1 | `routes/orchestration/worktrees.py:129` — route does `db.get(Project)` to resolve `root_path` for `GitClient`. Project reads are owned by `services/workspace/projects.py`. | medium (route bypasses owner) | low (route test needs PG anyway) | tiny (one getter) | negligible | **SELECT** |
| C2 | `routes/core/events.py` — route builds `select(Event)` + ordering/filter logic inline. Events are owned by `services/core/*`; `events.py` itself is Wave-12-frozen so the read contract needs its own home. | medium (query logic in transport; every filter change touches HTTP layer) | medium (unqueryable without HTTP) | small (one new query module) | low | **SELECT** |
| C3 | `routes/intelligence/symbols.py` — route builds `select(Symbol, SymbolFile)` joins inline (×2). Symbol reads are owned by `codeintel/*` (indexer owns the tables). | medium (duplicated join in two handlers; ranking/retrieval callers can't reuse) | medium | small (two helpers in owner module) | low | **SELECT** |
| C4 | `routes/*` single-row `db.get` elsewhere (browser, mcp, research, git, terminal, toolchains import `Project` only for hints — verified: no query) | low | none | — | — | DECLINE (no violation) |
| C5 | `services/*` cross-writes (execution→agent tables etc.): audit found none — activities call owner services; `executions.py` delegates to `leases`. | — | — | — | — | NO-OP (already clean) |

### Category D — Infrastructure leakage (none found)

- `agents_runtime/*`: no sqlalchemy/db imports (CI-enforced). Providers use
  `httpx` (adapter, justified). Workflows import only `timedelta` + pure
  recovery policy (CI-enforced). Routes construct `GitClient`/infra clients
  only to pass into services/activities (justified per audit).
- No `Temporal`/`NATS`/`Redis` imports in domain logic. No change.

## Selected (max 3): C1, C2, C3

Each gets: current graph → problem → target graph → affected files →
unchanged behavior → tests → rollback (`git revert` per commit).
Transaction behavior is unchanged (read-only moves; see G5 note in results).

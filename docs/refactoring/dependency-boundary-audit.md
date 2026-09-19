# Dependency Boundary Audit (Phase F1 — measured, not assumed)

Method: AST import scan of all 214 backend modules, categorized
domain/infra/framework/db. Raw data in `forensics.json` (outside repo).

## Clean (verified)

* `durable/workflows.py`: only `temporalio`, `timedelta`, pure policy.
  Determinism holds — enforce with a test (plan R-02).
* `agents_runtime/*`: no sqlalchemy/db imports. The gateway imports
  `app.runtime.runner/runtimes` (it IS the execution choke point — justified)
  and providers import `httpx` (adapter — justified).
* Health/diagnostics import nats/redis directly (probes — justified).
* Routes import infra clients (`files`, `gitops`, `artifacts`, `terminal`,
  `broker`) only to pass them into services/activities — justified.

## Smells (evidence + disposition)

1. **Services → ORM models (pervasive, ~30 call sites).** Location: all
   `services/*` + ~15 routes (`session.get`, inline selects). Expected: ports/
   contracts. Why it matters: medium — domain logic untestable without a DB.
   Risk of fixing blindly: high churn, zero behavior gain. Migration: Case C
   (persistence-oriented services) + as-touched repository helpers (plan R-03).
2. **Codeintel SQL inside domain** (`indexer`, `retrieval`, `scip` import
   sqlalchemy + models). Expected: domain pure, SQL in adapter. Why it
   matters: low-medium — retrieval ranking untestable without PG. Migration:
   Case C accepted for now (functions take `Session`, sqlite-incompatible
   JSONB pins them to PG); extract pure scoring later if churn justifies it.
3. **Routes → `app.db.models`** (single-row `get` for 404s). Expected:
   services own reads. Why it matters: low — mechanical. Migration: move to
   service getters as-touched (plan R-04 class).
4. **`TOOL_RUN_COMPLETED` vs `TOOL_*`** (naming overlap, different producers).
   Expected: distinct names. Why it matters: low (docs confusion only).
   Migration: document-only (plan R-06 likely decline — renames break history).

## No-go findings (do NOT "fix")

* No repository-per-table port (unjustified churn).
* No microservices, no DI framework, no Clean-Architecture layer cake.
* Barrel imports (`app.db.models`, `app.services.orchestration`) are the
  codebase's chosen coupling style — consistent, not accidental.

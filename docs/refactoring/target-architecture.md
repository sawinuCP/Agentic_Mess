# Target Architecture (Phase D)

Verdict from forensics: the modular monolith is sound — keep it. No
microservices, no framework changes, no layer-cake rewrite. The target fixes
boundary violations and documentation hierarchy, not the architecture itself.

## Bounded contexts and owners

| Context | Owner module(s) | Owns (writes) | Others may |
|---|---|---|---|
| Identity/policy gate | `api/security.py`, `agents_runtime/gateway.py` | auth decisions, policy verdicts | read verdicts only |
| Agent lifecycle | `agents_runtime/lifecycle.py` + `services/orchestration/agents.py` | agent/session rows, transitions | read |
| Task planning | `services/planning/*`, `tasks/graph.py` | tasks, deps, plans | read |
| Execution | `durable/*` (workflow = coordinator) | attempts, run progression | read; activities are the only writers of run state |
| Cost ledger | `services/intelligence/costs.py` | `model_invocations` | read aggregates |
| Context | `agents_runtime/context_broker.py` | bundles (ephemeral) | — |
| Models | `agents_runtime/models_registry.py`, `providers.py` | routing decisions | call `complete()` |
| Recovery | `services/orchestration/recovery.py` + `durable/activities/recovery.py` | decisions, recovery events | execute via workflow only |
| HITL | `services/orchestration/hitl.py` | request rows, verdicts | read; decide via service |
| Requirements/validation | `services/planning/requirements.py`, `services/quality/*` | requirements, validations, verifications | read |
| Artifacts | `artifacts/store.py`, `services/core/artifacts.py` | blobs + metadata | read by ref |
| Realtime projection | `realtime/*` | NOTHING durable (consumer offsets only) | subscribe |
| Messaging | `messaging/broker.py`, `services/orchestration/messages.py` | message rows, delivery marks | read inboxes |

## Dependency direction (enforced rule)

```text
routes → services → {domain, db.models}      (never services → routes)
activities → services + domain                (never domain → activities)
domain (agents_runtime, codeintel, toolchains) → stdlib + app.core only
realtime → db.models (read) + bus             (never writes domain tables)
frontend views → stores → api client          (never views → fetch directly;
                                               thin legacy exceptions grandfathered)
```

Single sanctioned violation today: services import ORM models directly (no
repository layer). Accepted as P2 (plan R-07): introduce read/write repository
functions per context only where churn justifies it; no big-bang port layer.
Phase G precedent (not a layer): owner-context read contracts —
`event_queries.query_events`, `indexer.search_symbols/file_symbols`,
`projects.require_project_root` — routes translate, never SELECT.

## Public interfaces (stability contract)

* HTTP: OpenAPI surface (`/api/*`, SSE stream). Additive changes only;
  `started`/`payload`-style extensible shapes preferred over v2 endpoints.
* Temporal: activity names + input dict keys (worker registration is the registry).
* Events: `event_type` strings are append-only; envelope v1 validation rejects
  unknown majors.
* Frontend: store shape + `api/client.ts` functions; reducer is pure.

## Data ownership (tables)

Postgres tables are written ONLY by their owning context (table above).
Cross-context reads are plain SELECTs (no shared write paths). Exceptions,
all intentional: `events` (every context appends its own types — single
`record_event`/activity helper per writer, never cross-type writes);
`artifacts` metadata (creators own their rows; retention deletes blobs only
when unreferenced).

## Event ownership

Each `event_type` has exactly one producer (matrix in requirement-matrix +
`REALTIME_EVENTS.md` vocabulary). Consumers: realtime fan-out (projection),
UI reducer (projection), retention (lifecycle). Delivery: at-least-once live,
exactly-once durable (idempotency keys + dedup). Versioning: schema_version.

## API boundaries

103 paths in 8 groups (inventory). Rules: auth on everything except
health/docs; validated DTOs in/out (no ORM leakage — `*_out()` translators);
bounded pages (limit caps); errors as `DomainError` → HTTP (ArtifactStoreError,
GitError, PolicyViolation all subclass it); 409 conflicts, 422 validation,
503 unavailable, 416 ranges.

## Configuration

`Settings` (pydantic, `HARNESS_*` env): defaults = local-first fail-closed.
Secrets never in code (scan clean). Knobs grouped: security, budgets, backoff,
realtime, retention, worker, runtime. See `production-configuration.md`.

## Errors / observability

`DomainError(message, status_code)` → HTTP; terminal HITL/timeout/cancelled
states; structured logs with task/agent/attempt/recovery/correlation IDs;
Prometheus `/metrics` (§22 list); OTel opt-in. No stack traces to users.

## Frontend boundaries

Views (panels) → Zustand stores → `api/client` + `sse` transport → pure
`office/selectors` + `eventReducer` → targeted components. No second store,
no router lib, DOM-free units stay in `*.test.ts` (node), Playwright smokes
for interaction. Monaco/xterm themed via the theme contract.

## What explicitly does NOT change

Temporal, NATS, Postgres, Redis-role, FastAPI, React/Zustand/Monaco, the
modular-monolith deployment, migration history, the v1 envelope, the
lifecycle matrix.

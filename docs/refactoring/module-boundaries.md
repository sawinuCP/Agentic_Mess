# Module Boundaries (Phase F6)

Authoritative ownership per context (enforced where marked [TEST]).

## Backend contexts

| Context | Public API | Internals | Owned models/persistence | Events produced | Allowed deps | Forbidden [TEST] |
|---|---|---|---|---|---|---|
| gateway/policy | `check_policy`, `invoke`, scopes | deny/approval lists | none (stateless) | none | stdlib, observations, runner | sqlalchemy, app.db |
| lifecycle | `assert_transition`, `can_transition` | TRANSITIONS table | none | none (callers emit) | stdlib only | everything app-level |
| models | `ModelRegistry.complete/load`, providers | retry/backoff, faults | `model_invocations` (via costs) | `MODEL_SWITCHED` (workflow) | chaos.faults, httpx (adapter) | app.db |
| context broker | `assemble`, `truncate_text` | tier strategies | none (ephemeral) | none | providers (tokens) | app.db |
| recovery policy | `recovery_decision`, `classify_failure`, `backoff_seconds` | ladders, NON_RETRYABLE | none (pure) | none | stdlib only | — |
| workflows | `TaskExecutionWorkflow` + signals | attempt loop, dispatch | progression (Temporal history) | via `record_event_activity` | temporalio, timedelta, pure policy [TEST] | clocks/RNG/infra |
| activities | 19 named activities | I/O + idempotency keys | per-activity rows/events | typed per activity | services, domain | — |
| realtime | SSE route, gateway, bus, bridge | consumer, queues, DLQ | none durable | re-emits durable rows | db.models (read) | domain service writes [TEST] |
| codeintel | `update_index`, `retrieve`, parsers | sha-skip, hybrid blend | `symbol_files`, `symbols` | none | sqlalchemy (accepted, Case C) | — |
| toolchains | detection/registry/`run_tool` | language adapters | none | `TOOL_RUN_COMPLETED` (route) | files, runner | — |
| evaluation | suite CLI, dataset, scorecard, triage, metrics | budgets, repeats, compare | own JSON reports (not DB) | none | runner, models | paid calls in CI (rehearsal only) |

## Frontend boundaries

Views → `state/*` stores → `api/client` + `api/sse` → pure `office/*`,
`graph/*`, `eventReducer`. No second store, no router lib, DOM-free units in
`*.test.ts`, Playwright for interaction. Monaco/xterm themed via the theme
contract (`state/theme.ts`).

## Cross-cutting (owned centrally)

Config (`core/config.py` — sole `HARNESS_*` authority except eval-runner and
provider-adapter env contracts, both documented); errors (`DomainError`
taxonomy, all store errors subclass it); logging (structured + redaction);
metrics (`core/metrics.py`); migrations (forward-only, 0011 head).

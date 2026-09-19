# Production Remediation Plan

**Source:** `docs/PRODUCTION_READINESS_AUDIT.md` · **Principle:** evidence-driven, incremental,
no rewrites of working subsystems. Each item has an ID, priority (CRITICAL/HIGH/MEDIUM/LOW),
category, and acceptance criteria. Waves are sequential; within a wave items are independent.

## Wave 1 — Critical production risks (security & data)

| ID | Item | Priority | Acceptance criteria |
|----|------|----------|---------------------|
| W1-AUTH-1 | Local API token auth: optional `HARNESS_API_TOKEN`; when set, all `/api/*` + WS require `Authorization: Bearer`; when unset (local desktop), server **binds 127.0.0.1 by default** (`HARNESS_HOST`) and logs a warning if bound wider | CRITICAL | Token enforced in tests; binding default verified; OFF state documented |
| W1-SECRET-1 | Sanitized env for agent/tool subprocesses: `run_process` drops secret-patterned vars (`*_API_KEY`, `*_TOKEN`, `HARNESS_OPENAI_API_KEY`, AWS/GCP/Azure creds) unless explicitly allow-listed via `env_extra` | CRITICAL | Integration test asserts model key absent from a subprocess dump; normal tools unaffected |
| W1-SSRF-1 | Research/browser fetch guard: resolve DNS and block loopback/private/link-local/metadata (169.254.169.254) unless `*_PRIVATE_HOSTS_ALLOWED`; apply to redirect targets | CRITICAL | Unit tests for resolver guard; test with rebinding-style hostname stub |
| W1-WS-1 | Terminal WebSocket auth: same token check on WS handshake | HIGH | WS rejected without token when enabled |
| W1-CORS-1 | Explicit CORS: no wildcard; allow-list `http://localhost:5173` + Tauri origins | HIGH | Config-driven; tests |
| W1-RATE-1 | Simple per-IP token-bucket on mutating endpoints (opt-in) | MEDIUM | 429 path tested |

## Wave 2 — Reliability

| ID | Item | Priority | Acceptance criteria |
|----|------|----------|---------------------|
| W2-RECOV-1 | Durable workflow consumes `recovery` decisions: MODEL_FAILURE → retry on fallback role; RESOURCE_LIMIT → delay; exhausted → replan/escalate event | HIGH | Workflow unit test with injected outcomes; attempt bounds respected (REC-002/003) |
| W2-GATEWAY-1 | Provider retry with exponential backoff + jitter on 429/5xx/timeouts; per-route timeout in models config | HIGH | Fake provider test; config key documented |
| W2-BUDGET-1 | Per-agent and per-execution token/tool-call budgets (in addition to per-task) | MEDIUM | Budget gate tests |
| W2-CHAOS-1 | `tests/chaos/`: worker-kill, stale-lease takeover, NATS down (delivery degrades, durable intact), DB restart (pool recovers), port squatting, model timeout injection | HIGH | Each chaos test asserts durable-state invariants |
| W2-MSG-1 | JetStream DLQ/park + redelivery ceiling for poison messages | MEDIUM | Poison message test |
| W2-IDEM-1 | Idempotency keys on mutating POSTs (worktree create, port allocate) | MEDIUM | Duplicate POST returns same resource |

## Wave 3 — Observability

| ID | Item | Priority | Acceptance criteria |
|----|------|----------|---------------------|
| W3-METRICS-1 | `/metrics` (Prometheus): HTTP latencies, event counts by type, model tokens/cost, tool failure rate, queue depth | HIGH | Endpoint test; office surfaces key numbers |
| W3-STREAM-1 | SSE endpoint `/api/events/stream` (durable-event tail + live emit) replacing office polling; UI reconnect + resync via `since` cursor | HIGH | Reconnect test; UI switches to SSE with poll fallback |
| W3-RETAIN-1 | Retention policy: configurable prune for events/artifacts (defaults e.g. 30 d events, artifacts by size cap) | MEDIUM | Prune endpoint + scheduled worker; test |
| W3-TRACE-1 | Trace context propagation into Temporal activities | LOW | Correlation visible in logs |

## Wave 4 — Performance

| ID | Item | Priority | Acceptance criteria |
|----|------|----------|---------------------|
| W4-PERF-1 | Timeline/event feed virtualization + aggregation (per-second buckets beyond N events) | MEDIUM | 10k-event synthetic feed stays responsive |
| W4-PERF-2 | DB index review under 100k events (EXPLAIN on hot queries) | MEDIUM | Documented query plans |
| W4-PERF-3 | Context-engine compaction for long histories (summarize T4 beyond cap) | MEDIUM | Token-budget test |

## Wave 5 — AI/agent evaluation

| ID | Item | Priority | Acceptance criteria |
|----|------|----------|---------------------|
| W5-EVAL-1 | `scripts/eval/` benchmark scenarios (Python/TS/Go repos with seeded bugs) + result schema (success, coverage, cost, tokens, duration) | MEDIUM | Eval runs offline (rehearsal) and records JSON |
| W5-EVAL-2 | Report comparing runs (model/config changes) | LOW | Two runs diffable |

## Wave 6 — UX foundation

| ID | Item | Priority | Acceptance criteria |
|----|------|----------|---------------------|
| W6-PALETTE-1 | Command palette (Ctrl+K): searchable actions (start/pause/resume execution, open views, run tools, spawn review, diagnostics) | HIGH | Keyboard-only usable; tests via Playwright |
| W6-STATES-1 | Production states component: loading/empty/error/offline/reconnecting applied to office + timeline + oversight | HIGH | Office degrades gracefully with API down (poll backoff + banner) |
| W6-A11Y-1 | Focus management in dialogs, ARIA roles on tabs/pills, reduced-motion honored | MEDIUM | axe-style manual pass documented |

## Wave 7 — Signature experiences (post-foundation)

Execution graph (dependency DAG from durable tasks with live status), requirement
traceability drill-down (REQ → TASK → ATTEMPT → artifact), execution replay from the
durable event stream. Sequenced after Waves 1–6; designed against the durable state
(never against in-memory events).

## Wave 8 — Release engineering

SBOM (pip-audit, npm audit --omit=dev gate), image/diagnostics bundle export,
Tauri shell (requires Rust toolchain), signed artifacts. Gated on toolchain availability.

## Out of scope (explicit)

Microservices split; frontend framework migration; replacing Temporal/NATS/Postgres;

## Delivery log — 2026-09-18 (production blockers, prioritized)

| ID | Disposition | Evidence | Variance from plan (if any) |
|----|-------------|----------|------------------------------|
| W1-RATE-1 | Delivered | `app/api/middleware.py` `RateLimitMiddleware` + `HARNESS_RATE_LIMIT_*`; wired in `app/main.py`; `tests/unit/test_rate_limit.py` | Fixed-window buckets, not token-bucket — same 429 acceptance; in-memory (single-process deployment, documented in `OPERATIONS.md` §5) |
| W2-GATEWAY-1 | Delivered | `transient` flag on `ModelProviderError` (429/5xx/timeout vs permanent); bounded retry + jitter in `ModelRegistry.complete` (`HARNESS_MODEL_PROVIDER_MAX_ATTEMPTS` + `HARNESS_RECOVERY_BACKOFF_*`); per-route `timeout_seconds` in models config; `tests/unit/test_provider_retry.py` (7 tests) | — |
| W2-BUDGET-1 | Delivered | `tokens_for_agent` / `invocations_for_task` / `invocations_for_agent` in `app/services/intelligence/costs.py`; 4-way gate in `agent_execute_activity` (`HARNESS_MODEL_BUDGET_*`, 0 = unlimited); `MODEL_BUDGET_EXCEEDED` event carries the scope; `tests/unit/test_costs_budgets.py` + agent-gate integration test | Per-execution runs are bounded by the per-task gate (ledger rows are task-scoped across runs) — no separate run-scoped counter, documented in `OPERATIONS.md` §5 |
| W2-CHAOS-1 | Partially delivered | `tests/integration/test_chaos.py`: kill-9 worker mid-run → durable state intact + retry succeeds; NATS transport loss mid-run → 503 fail-closed, durable history intact, drain on recovery. Pre-existing: port squatting (`test_bind_probe_skips_occupied_ports`), stale-lease takeover (`test_expired_lease_is_reported_expired_and_taken_over`) | DB-restart pool recovery and model-timeout injection not covered (residual) |
| W2-MSG-1 | Delivered | `RealtimeGateway._dispatch_message`: decode failures and delivery-exhausted poison → verbatim publish to `<prefix>.dlq` + ack; transient crashes → nak (redelivery ceiling `realtime_max_deliver`); `tests/unit/test_realtime_dlq.py` | DLQ lives on the same stream subjects (retained, inspectable), not a separate stream |
| W2-IDEM-1 | Delivered | Nullable `idempotency_key` + partial unique indexes via alembic `0011` (live DB migrated); replay returns the live row (worktree replay: HTTP 200); race losers replay the winner; `idempotency_key` on `PortAllocateIn`/`WorktreeCreateIn`; integration tests in `test_execution_ports.py` / `test_worktrees.py` | — |
| W3-TRACE-1 | Delivered | `trace_activity` decorator (`app/core/observability.py`, no-op without provider) on all 15 Temporal activities; spans carry ID-only attributes + outcome/error status; `tests/unit/test_activity_tracing.py` (in-memory exporter) | — |
| W4-PERF-3 | Delivered | Truncate-before-drop in `app/agents_runtime/context_broker.py`: oversized tiers truncate to remaining budget (head; tail for T4 history) with omission markers; drop only below a 16-token floor; T0 truncated-never-dropped; total never exceeds budget; `tests/unit/test_context_compaction.py` | Deterministic truncation, not LLM summarization of T4 (no model call in the hot path) |
| W4-PERF-2 | Evidence added | Task list paginated (`limit`/`offset`, stable order with id tiebreaker, related rows page-scoped); EXPLAIN shows index scan on `ix_tasks_project_status` (~0.4 ms) — documented in `OPERATIONS.md` §5; `test_task_query_performance.py` (constant-query + tiling tests) | Full 100k-event index review remains future work |
| W5-EVAL-2 | Already delivered (verified) | `app/evaluation/reports.py::compare_suites` + `tests/unit/test_evaluation_comparison.py` | — |

Additionally delivered (found while implementing): `NatsJetStreamBroker` used the
nats-py 1.x `add_stream` idiom and always 503'd against the installed 2.x client
(caught by the chaos test) — fixed to `StreamConfig`, plus a `wait_for` connect
cap so blackholed servers surface as 503 instead of hanging; agent capability
scopes `read < write < admin` (SR-14) since the gateway previously checked tool
names only; `/metrics` excluded from the OpenAPI schema + API description
documenting public conventions.

## Wave 2 verification — 2026-09-18 (recovery execution audit)

The recovery coordinator was inspected end-to-end (policy core → Temporal
workflow → activities → tests) and five genuine gaps were closed; everything
else verified intact:

| ID | Disposition | Evidence |
|----|-------------|----------|
| W2-RECOV-1 | Fixed + verified | `replace_agent` / `spawn_debugger` / `request_hitl` existed as workflow branches and doc rows but the decision function could never emit them (dead code + doc mismatch). The ladder now specializes on the final attempt: `TOOL_FAILURE → replace_agent`, `TASK_FAILURE → spawn_debugger`, `RESOURCE_LIMIT → request_hitl`. `prev_agent_id` was never updated, so replacement drained `None` (crash in `end_agent_session_activity`); the loop now tracks it and the replace branch drains the just-failed agent. Spawned children terminally close the parent *with a child reference* instead of waiting on a signal nothing sends. Policy denials inside the execution activity are contained `SECURITY_BLOCK` outcomes (previously an escaping `DomainError` failed the workflow run and stranded the task as `running`). Failure details now carry exit code + stderr lines (stdout-only summaries starved the classifier). New: `tests/integration/test_recovery_workflow.py` (7 Temporal tests on the time-skipping/local test server: retry→success, replace→replan chain with drain proof, debugger with child ref, security stop, HITL timeout, pre-check resume, live-signal resume) |
| W2-GATEWAY-1 | Verified intact | Backoff/retry + per-route timeouts (delivered 2026-09-18, see above) |
| W2-BUDGET-1 | Verified intact | `recovery_budget_activity` gates budget-sensitive actions incl. the newly reachable `replace_agent`/`spawn_debugger` (covered by `test_budget_gate_blocks_expensive_recovery_when_exhausted`) |
| W2-CHAOS-1 | Extended | Pre-wait unfinished-dependency check added: a dependency that finished before the waiter parks would never signal again (waiter hung to its deadline). Covered by `test_finished_dependency_resumes_without_waiting`. DB-restart recovery remains residual |
| W2-MSG-1 / W2-IDEM-1 | Verified intact | No changes needed |
| W3-TRACE-1 | Verified intact | All recovery activities carry `trace_activity` spans (incl. the new `dependency_status_activity`) |

Deliberate non-implementation: no automated ROLLBACK action. Restoring code
state automatically would destroy the durable evidence the system must preserve
(dirty worktrees require explicit `force`; conflicts become explicit tasks in
the integration queue — by design, documented in `docs/RECOVERY.md`). Rollback
stays an explicit human operation.

## Residuals completion — 2026-09-18 (follow-up to both logs above)

| Item | Disposition | Evidence |
|------|-------------|----------|
| DB-restart pool recovery | Delivered | Heartbeats made best-effort (a DB blip no longer fails hours-long executions; durable writes keep their retry policies); `tests/integration/test_chaos.py`: killed-backend transparency (`pool_pre_ping`) + full container restart mid-workflow → completes with no duplicate attempt |
| HITL EXPIRED/CANCELLED | Delivered | `timeout` documented as the expired state; `cancelled` added (`cancel_request` + `POST .../hitl/{id}/cancel`, 409 on decided); waiters treat cancel as rejection (fail-closed); covered in `test_recovery_executor.py` |
| Automated ROLLBACK | Delivered (evidence-preserving) | Per-attempt HEAD snapshots (`snapshot_attempt_activity`); `rollback_attempt_activity` restores tracked state after preserving pre-reset HEAD on a `recovery/*` branch; wired into the merge-conflict path before integration delegation; `tests/integration/test_rollback.py` (5 tests incl. end-to-end conflict → restore → delegate) |
| Child follow-through | Verified + proven | Debugger/replan children are born `pending` and the scheduler tick picks them up (`test_spawned_children_are_scheduler_visible`); `request_hitl` scope (last-attempt resource pressure only) retained as deliberate policy |

## Wave 3 verification — 2026-09-18 (realtime event streaming audit)

The Wave 3 architecture was inspected end-to-end (durable events → bridge →
NATS → gateway → SSE → Zustand reducer) and verified intact against every
acceptance criterion; three genuine gaps were closed:

| Item | Disposition | Evidence |
|------|-------------|----------|
| Live NATS path untested | Fixed | All prior realtime tests drove `gateway.broadcast` in-process; the JetStream hop (stream creation, dedup headers, durable pull consumer, decode/ack/fan-out) had zero coverage. New `tests/integration/test_realtime_nats_path.py` runs bus → live NATS → consumer → fan-out on a hermetic stream scope: 300 events / 20 agents / 3 subscribers delivered in order, plus server-side `Nats-Msg-Id` dedup proof. Load numbers (measured, local dev): 300 events → ~2–4 s end-to-end (~100 ev/s incl. consumer startup); gateway-only fan-out of 1000 events to 5 subscribers < 5 s with slow-client drops counted |
| Missing §22 metrics | Fixed | `harness_realtime_connections_total` (accepts; reconnects appear as new connections) and `harness_event_delivery_latency_seconds` (envelope timestamp → fan-out) added to the gateway; asserted in unit + `/metrics` tests and documented |
| Garbled architecture doc | Fixed | `docs/REALTIME_EVENTS.md` had sections out of order (backpressure split, stray paragraph) and listed unemitted event types (`AGENT_STARTED/COMPLETED/FAILED`); rewritten in canonical order with the DB-verified 48-type vocabulary |
| Everything else | Verified intact | Canonical v1 envelope + validation; dense per-project `project_seq` (atomic upsert); SSE-over-fetch transport (bearer headers; documented decision); Wave 1 auth on the stream + project-scoped fan-out (scenario H); replay + `since` cursor + `RESYNC_REQUIRED` (scenarios D/G); reducer dedup/ordering/incremental updates (scenario F + frontend suite); polling removed (only degraded-fallback resync loop + health probe + replay clocks remain); bounded queues/retention/DLQ; 8/8 backend scenarios A–H green |

Deliberate positions retained: no per-tool-start/progress frames (storm avoidance —
completion summaries + artifact refs only); `request_hitl` scope unchanged;
`timeout` remains the HITL expired-state name.

## Wave 3 residuals completion — 2026-09-18

| Item | Disposition | Evidence |
|------|-------------|----------|
| Test NATS consumers accumulate | Fixed | Hermetic tests delete their durable consumer on teardown (`_delete_consumer`); stream purged per test |
| Spurious `event_bus_disconnected` on close | Fixed | `_on_disconnected` stays quiet when `_closed` (intentional close is not an outage) |
| No per-command tool lifecycle | Delivered (bounded) | `TOOL_STARTED`/`TOOL_COMPLETED`/`TOOL_FAILED` per shell command (≤2 frames, concise outcome + evidence refs, best-effort write); reducer treats them as timeline-only; covered backend (success + failure) and frontend (reducer) |
| `request_hitl` scope / `timeout` name / dev-box load numbers | Retained as deliberate policy | Documented; no change |

## Wave 4 verification — 2026-09-18 (performance audit)

Measured-first; only evidenced bottlenecks were changed (details + matrix in
`docs/WAVE4_PERFORMANCE.md`):

| Item | Disposition | Evidence |
|------|-------------|----------|
| Requirements N+1 (20 reqs → 21 queries) | Fixed | Batched criteria (2 queries) + pagination; query-count regression test |
| Unbounded agents/requirements/memories/context-items; leases fetch-then-slice | Fixed | Server-side limits everywhere; SQL-side status filter for leases; tiling tests |
| Artifact full-blob loads, no ranges | Fixed | Chunked streaming + single-range 206/416; also fixed `ArtifactStoreError` escaping as 500 instead of 404 |
| Worker concurrency = SDK defaults | Fixed | `HARNESS_TEMPORAL_MAX_CONCURRENT_WORKFLOWS/ACTIVITIES/ACTIVITIES_PER_SECOND` |
| Blind blob retention | Fixed | Evidence-referenced blobs spared (attempt + terminal refs) |
| Index review | Audited, no change | EXPLAIN shows index scans, sub-ms; new indexes unjustified at measured scale |
| Codeintel scale | Measured, no change | 500 files: full 7.6 s, incremental noop 68 ms, retrieval 269 ms |
| Virtualization/distributed scaling | Declined | Lists bounded at data layer; no evidence warrants new infra |
| 100k-volume review, hour-scale soak, NATS burst UI | Residual | Documented in WAVE4_PERFORMANCE.md |

## Wave 5 verification — 2026-09-18 (evaluation audit)

The evaluation system was inspected (dataset EVAL-001..010, offline suite with
disposable DB, scorecard gates, compare/repeatability, CLI, CI fast + manual
full) and verified intact against every acceptance criterion; two genuine gaps
were closed:

| Item | Disposition | Evidence |
|------|-------------|----------|
| No failure triage taxonomy (§39) | Fixed | `triage_result()` in `app/evaluation/suite.py`: hard signals (BUDGET/TIMEOUT/INFRA) win, then failed-node evidence mapping (security/planner/decomp/agent/recovery/model/coverage/validation/cost/context/tool → classes, EXECUTION_FAILURE fallback); rows carry `triage`, `report` tallies it; never overrides status |
| No orchestration/message metrics library (§12/§16/§42) | Fixed | `app/evaluation/metrics.py`: `execution_metrics(task_id)` (attempts, retries + rate, recoveries + success, tool/model/HITL counts, tokens, cost) and `communication_health(conversation_id)` (orphans, duplicates, unanswered, undelivered); `tests/integration/test_evaluation_metrics.py` |
| Everything else | Verified intact | Full eval baseline 10/10 PASS (67 s, disposable DB); fast path green; CLI list/run/compare/report/persist/audit; CI fast-per-push + manual full; repeats/FLAKY; budgets enforced; evaluator self-tests; no model-override of hard failures |

Deliberate positions retained: scripted offline evaluation (no autonomous
planner loop — documented limitation); no evaluator model; `timeout` remains
the expired-state name.

## Wave 6 verification — 2026-09-18 (UI/UX foundation audit)

Frontend foundation verified against Phases 1–8 with live browser smokes; three
genuine gaps closed (all frontend/test-side, zero backend changes):

| Item | Disposition | Evidence |
|------|-------------|----------|
| Stale office smoke assertions | Fixed | Task-title exact-text assertion broke on the status glyph; tab `nth=` indices drifted after Comms insertion. Both replaced with accessible-role selectors (`get_by_role("button", name=…)`). `OFFICE UI SMOKE PASSED` |
| Stale registry/docs counts | Fixed | Registry header claimed task creation + symbol search "deliberately absent" (both exist end-to-end); interaction model said "23 commands" (28 static + per-task controls). Corrected; verified `NewTaskDialog`/`SpawnAgentDialog`/`SymbolSearch` all perform real API actions — no placeholders |
| Everything else | Verified intact | Palette (Ctrl+K, filter/nav/Enter/Escape/focus-restore, disabled reasons, busy/error) + registry/task-command unit tests; `UiState`/`StatusLabel` (never color-alone, unknown≠success); `useDialogFocus` containment + restoration; reduced-motion + focus-visible CSS; responsive breakpoints; bounded projections (0 selector invalidations); degraded-only resync loop; no backend contract changes |

Validation: Vitest green, `tsc` exit 0, ESLint 0 errors, production build green;
Playwright smokes green (palette, office, task-controls) against live API +
dev server; backend suite not rerun (no backend changes). Full Agent Office,
graph, traceability, replay and Command Center remain future waves per the
stopping condition.

## Wave 6 limitations completion — 2026-09-18

Frontend/test-side only, zero backend changes:

| Item | Disposition | Evidence |
|------|-------------|----------|
| Problems view missing | Delivered | `ProblemsView` triages failed/blocked tasks, failed tool runs, pending approvals from existing stores (pure `collectProblems`, unit-tested); navigates to office/output/oversight; `nav.problems` palette command; empty means clean |
| Settings view missing | Delivered | `SettingsView`: token save/clear, layout reset, live connection telemetry — all local real actions; `nav.settings` palette command |
| Stale smoke selectors | Fixed | Accessible-role selectors; office + palette smokes extended for the new views |
| Stale registry/docs counts | Fixed | 28 static + per-task controls; gap lists corrected |
| Per-agent lifecycle, message composing, runtime view, light theme, virtualization | Retained as gaps | No safe backend contract (agents/messages), no evidence for new infra (virtualization), theme scope — documented |

## Wave 6 remaining-parts completion — 2026-09-18

Almost entirely frontend/test-side; one pre-existing backend endpoint surfaced:

| Item | Disposition | Evidence |
|------|-------------|----------|
| Per-agent session release | Delivered (UI only) | `POST /api/sessions/{id}/end` already existed + tested; added the Release button (confirmed) in AgentDetail. Full pause/resume/stop of agents stays unavailable by architecture (disposable agents; workflows own control) |
| Operator composing | Already existed — verified | CommsTab compose box posts with null sender (explicit operator attribution); documented |
| Runtime view | Delivered | `RuntimeView` (ports + release w/ confirm, leases, refresh) over existing list endpoints; pure `summarizeRuntime` unit-tested; `nav.runtime` palette command; office-smoke covered |
| Light theme | Delivered | `[data-theme="light"]` variable layer, `harness-light` Monaco theme, live xterm recolor, Settings toggle + `nav.theme` palette command, persisted; no hard-coded dark hex in components; smoke-verified toggle |
| Virtualization | Declined with measurements | Timeline burst-grouped + capped at 120, history paginated 500/page, lists capped at 100, 0 selector invalidations — no list justifies windowing; building it would violate the wave's own rule |
LSP/call-graph (deferred register); real-time collaborative editing.

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
LSP/call-graph (deferred register); real-time collaborative editing.

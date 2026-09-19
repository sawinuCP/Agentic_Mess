# ADRs (accepted — extracted from the as-built system)

## ADR-001 Modular monolith
One deployable API + worker over shared Postgres. Rejected: microservices
(operational cost unjustified for local-first single operator).

## ADR-002 Temporal for durable execution (opt-in)
Workflows own run progression; activities own I/O. Direct-call mode preserved
for tests. Rejected: bespoke orchestrator (Wave 2 proved Temporal semantics).

## ADR-003 PostgreSQL as sole truth
Events, ledger, leases, HITL, artifacts metadata. Redis carries no workload;
NATS carries no authority. Rejected: polyglot persistence.

## ADR-004 NATS JetStream for live transport
Bounded projection only (retention + DLQ). Rejected: Kafka (weight),
pure polling (latency), second broker.

## ADR-005 Disposable agents
Agents are created per attempt with role-derived scopes; replacement chains
instead of long-lived identities. Rejected: daemon agents (lifecycle risk).

## ADR-006 Tiered context broker with budgets
Assemble → truncate-before-drop under token budgets; per-agent/per-execution
gates. Rejected: whole-repo dumping, LLM summarization in the hot path.

## ADR-007 Gateway as single policy choke point
Allowlist + deny + approval + capability floors, enforced before any provider
or process call. Rejected: per-tool ad-hoc checks.

## ADR-008 Local-first security posture
Loopback default, token gate, fail-closed binds, sanitized subprocess env,
DNS-aware SSRF. Rejected: multi-tenant identity (documented gap).

## ADR-009 Worktrees + integration queue
Isolated worktrees; conflicts become explicit tasks, never silent merges;
evidence-preserving rollback. Rejected: in-place shared mutation.

## ADR-010 SSE-over-fetch for realtime
Bearer headers work; per-project sequence cursors; replay/resync. Rejected:
second WebSocket, EventSource (no headers).

## ADR-011 Evidence-gated verification
VERIFIED requires durable validation records; UNKNOWN is the default.
Rejected: agent self-report as verification.

## ADR-012 Deterministic recovery policy
Pure classifier + ladders + idempotent activities; budgets/HITL gates.
Rejected: LLM-chosen recovery actions, retry frameworks.

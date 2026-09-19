# Data-Flow Architecture (Phase C — as implemented)

## Command path (reads and writes)

```text
User (browser, bearer token)
 ↓  fetch /api/* (CORS allow-list, AuthMiddleware, rate limit, request ID)
FastAPI route (validation via Pydantic DTO)
 ↓  asyncio.to_thread
Application service (services/*: policy + orchestration logic)
 ↓  SQLAlchemy session (single transaction per call)
PostgreSQL (sole truth) + artifact blobs on disk
 ↓  commit → SQLAlchemy mapper/session listeners
```

## Durable execution path

```text
POST /api/tasks/{id}/execute  (Temporal enabled? else 503)
 ↓  deterministic workflow id task-exec-{id} (repeat start dedupes)
Temporal TaskExecutionWorkflow (pure deterministic code ONLY)
 ↓  activities (all I/O lives here):
    load → start_attempt → start_agent → snapshot → execute → finish
 ↓  agent_execute_activity:
    context broker assemble → registry.complete (retry/backoff) →
    gateway.invoke (policy → run → observation) → ledger + TOOL_* events
 ↓  failure? recovery_decision (pure) → bounded action activities →
    next attempt | terminal | HITL gate | dependency wait
 ↓  completion → dependents signaled → task status + TASK_COMPLETED
```

## Event flow (projection, never authority)

```text
Event row INSERT (any writer: routes, services, activities, workflows)
 ↓  after_insert stash → after_commit → bridge → EventBus (bounded, drops live copy on overflow)
NATS JetStream harness-events (bounded retention, Nats-Msg-Id dedup)
 ↓  one durable pull consumer per process (explicit ack, max_deliver 3)
RealtimeGateway._dispatch_message → decode | DLQ | nak → broadcast
 ↓  per-connection bounded queues (slow-client drop → RESYNC → disconnect)
SSE GET /api/events/stream (auth + project scope + since cursor + durable replay)
 ↓  Zustand officeStore (stream loop, backoff, gap→resync, degraded fallback)
Pure eventReducer (validate → dedupe → order → incremental project)
 ↓  targeted component renders (selectors, memoization)
```

Miss the stream → `since` replay; replay range pruned → `RESYNC_REQUIRED` →
authoritative REST refetch. The bus is never read for state.

## Agent communication

```text
Agent/operator
 ↓  POST /api/messages (durable row; sender null = operator, never faked)
messages table (conversation_id, correlation, reply_to, delivered_at)
 ↓  deliver-pending → broker.publish (at-least-once, Nats-Msg-Id = message id)
NATS harness-messages → (no agent-side consumer by design)
Recipient agents read via inbox endpoints inside activities
```

## Recovery

```text
Failed outcome (outcome failed + failure_class + detail + evidence ids)
 ↓  recovery_decision (pure policy core: class → ladder → last-attempt specials)
Temporal workflow executes the decided action through activities
 ↓  retry (sleep backoff) | model route | replace (drain+chain) | debugger child |
    replan child | dependency signal wait | rollback (snapshot-anchored) |
    HITL gate (budget-aware) | terminal_failure (evidence + recommendation)
 ↓  next attempt | terminal state (all paths recorded as events)
```

## Ownership notes (evidence for Phase D)

* State transitions validated ONLY in `agents_runtime/lifecycle.py` and the
  workflow; UI never transitions.
* Money/tokens: `services/intelligence/costs.py` ledger; budgets enforced at
  call sites, never in the UI.
* Policy: `agents_runtime/gateway.py` (`check_policy`) is the single choke
  point; providers never see denied calls.
* Money, policy, and lifecycle are read-mostly from elsewhere — the main
  coupling smell is services importing ORM models directly (no repository
  layer); see target architecture.

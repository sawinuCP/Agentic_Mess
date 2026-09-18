# Realtime Event Streaming Architecture (Wave 3)

**Principle:** the realtime stream is a *low-latency projection* of durable state.
PostgreSQL (`events` table) and Temporal remain the only sources of truth. A missed,
dropped, or duplicated realtime event never corrupts state — clients recover through
authoritative replay and resynchronization, never through the bus.

```text
Durable writes (FastAPI routes / Temporal activities / services)
      ↓  SQLAlchemy commit (after_insert / after_commit bridge)
events table (authoritative, per-project sequence)  ──►  REST /api/events (replay/resync)
      ↓  event bridge (committed rows only)
NATS JetStream  (harness-events, bounded live projection)
      ↓  durable pull consumer (one per process)
Realtime gateway (fan-out, per-connection bounded queues)
      ↓  SSE  GET /api/events/stream
Zustand office store → pure event reducer → targeted UI updates
```

## Components

| Component | File | Role |
|-----------|------|------|
| Event model | `app/db/models/core/events.py` | Durable rows; `project_seq` = dense per-project monotonic sequence |
| Event service | `app/services/core/events.py` | Authoritative write only; never touches the bus |
| Bridge | `app/realtime/bridge.py` | Mapper/session listeners: committed `Event` rows → bus enqueue (bounded, never blocks) |
| Bus | `app/realtime/bus.py` | JetStream publisher; bounded queue; worker-thread safe; `Nats-Msg-Id` = event_id dedup |
| Gateway | `app/realtime/gateway.py` | One durable pull consumer per process → authorized SSE fan-out, slow-client policy, DLQ |
| SSE route | `app/realtime/route.py` | `GET /api/events/stream`; auth, connection limit, durable replay from PostgreSQL |
| Envelope | `app/realtime/envelope.py` | Canonical wire format v1 + validation |
| Retention | `app/realtime/retention.py` | Bounded prune for events / artifact blobs; explicit opt-in for durable history |
| Metrics | `app/core/metrics.py` | In-process Prometheus registry exposed at `/metrics` (scrape target, not in OpenAPI) |

## Event envelope (schema v1)

`app/realtime/envelope.py` — one wire format for every execution event. Only fields
that exist on the durable row are populated; large data never rides in `payload`
(producers attach `payload_ref` = `artifact://…` plus a concise summary; clients fetch
artifacts on demand).

```json
{
  "schema_version": 1,
  "event_id": "uuid (durable Event.id)",
  "event_type": "AGENT_STATUS_CHANGED",
  "timestamp": "2026-09-17T12:00:00+00:00",
  "project_id": "uuid | null",
  "execution_id": "string | null",
  "task_id": "uuid | null",
  "agent_id": "string | null",
  "correlation_id": "string | null",
  "source": "api | orchestration | temporal | …",
  "sequence": 12345,
  "payload": {},
  "payload_ref": null
}
```

Validation (`decode_envelope`) rejects unknown `schema_version` > 1, non-UUID event
ids, and malformed payloads — consumers resync from the authoritative API instead of
guessing. The frontend mirrors this envelope in `types.ts` and rejects frames that do
not match, forcing a resync rather than applying garbage.

## Event types

Event names reuse the durable `events.event_type` vocabulary already written by the
orchestration services (no parallel taxonomy). Verified against the live database
(`SELECT DISTINCT event_type FROM events`); the stream carries, among others:

* agent lifecycle: `AGENT_CREATED`, `AGENT_STATUS_CHANGED` (running / verifying /
  completed / failed …), `AGENT_REPLACED`;
* task lifecycle: `TASK_CREATED`, `TASK_SCHEDULED`, `TASK_EXECUTION_STARTED`,
  `TASK_COMPLETED`, `TASK_FAILED`, `TASK_TERMINALLY_FAILED`, `TASK_CANCELLED`,
  `TASK_REPLANNED`, `TASK_REPLAN_STARTED`, `DEPENDENCY_WAIT_STARTED`,
  `DEPENDENCY_RESUMED`;
* recovery: `RECOVERY_SELECTED`, `RETRY_STARTED`, `MODEL_SWITCHED`,
  `DEBUGGER_SPAWNED`, `MODEL_BUDGET_EXCEEDED`, `SNAPSHOT_CREATED`,
  `ROLLBACK_COMPLETED`;
* HITL: `HITL_REQUESTED`, `HITL_RESPONDED`, `HITL_RECOVERY_REQUESTED`,
  `HITL_RECOVERY_RESPONDED`;
* tools (per-command lifecycle only — STARTED/COMPLETED/FAILED with concise
  outcome + evidence refs; no per-token/per-step storm): `TOOL_STARTED`,
  `TOOL_COMPLETED`, `TOOL_FAILED`, `TOOL_RUN_COMPLETED`, `MCP_TOOL_CALLED`,
  `BROWSER_SCREENSHOT`, `SECURITY_SCAN_COMPLETED`;
* resources: `PORT_ALLOCATED`, `PORT_RENEWED`, `PORT_EXPIRED`, `PORT_RELEASED`,
  `LEASE_ACQUIRED`, `LEASE_RENEWED`, `LEASE_EXPIRED`, `LEASE_RELEASED`,
  `WORKTREE_CREATED`, `WORKTREE_QUEUED`, `WORKTREE_RELEASED`,
  `INTEGRATION_STARTED`, `INTEGRATION_MERGED`, `INTEGRATION_CONFLICT`,
  `FILE_WRITTEN`, `GIT_COMMIT`;
* planning: `PROJECT_OPENED`, `PLAN_CREATED`, `REQUIREMENT_CREATED`,
  `DECISION_ADJUDICATED`.

Events represent meaningful state changes only; high-frequency output stays in
artifacts referenced by `payload_ref`. Per-command tool lifecycle (≤2 frames per
command) is the finest allowed granularity — per-invocation start/progress
beyond that, and any per-token streaming, stay out of the event stream by
design (§18).

## Event ordering & sequence handling

`events.project_seq` is a dense, per-project monotonic sequence assigned at insert
(atomically via the `event_sequences` counter table): the smallest reliable ordering
scope. The frontend gates every envelope through a sequence check — `apply` /
`duplicate` (by event_id or already-advanced cursor) / `gap` — and a gap
(`100, 101, 103`) triggers `RESYNC_REQUIRED` handling, never blind application.
The server detects a pruned leading range (`min_seq > since + 1`) on replay and
sends an explicit `RESYNC_REQUIRED` control frame.

## NATS subjects & stream

* Stream: `harness-events`, subjects `harness.events.>` (configurable via
  `HARNESS_NATS_EVENTS_*`), `RetentionPolicy.LIMITS`.
* Subject per event: `harness.events.project.<project_id>` (or `…global`).
* One durable pull consumer per process (`realtime-gateway`), explicit acks,
  `max_ack_pending` 512, `max_deliver` 3, fetch batch 64 — no consumer explosion,
  graceful shutdown, bounded reconnect backoff with jitter.
* Live hop is **at-most-once**: queue overflow drops the live copy and counts a
  metric; clients recover via durable replay. Server-side dedup
  (`Nats-Msg-Id` = event_id, 120 s window) protects the stream from publisher retries.
* Poison handling: undecodable envelopes are dead-lettered (never redelivered
  forever); unexpected processing crashes are nacked until the final allowed
  delivery, then dead-lettered to `<prefix>.dlq` (same stream subjects, retained
  and inspectable) and counted.

## Transport decision: SSE

Server → client execution updates are strictly one-directional; the terminal already
uses a separate authenticated WebSocket. SSE over `fetch` + `ReadableStream` (not
`EventSource`) keeps the Wave 1 bearer header, gives incremental frame parsing, and
avoids a second bidirectional transport. No new realtime transport was introduced.

## Authentication & authorization

Realtime connections ride the Wave 1 model: `HARNESS_API_TOKEN` (bearer) is enforced
by the same middleware as every other `/api/*` route (verified by
`test_realtime_stream.py` unauthenticated-rejection tests). The gateway authorizes at
connection time: project existence is verified server-side; client-supplied IDs are
never trusted. A connection registered for project P receives only envelopes whose
`project_id` matches P. No tokens or secrets travel in URLs or payloads. Tests:
unauthenticated rejected, unauthorized project rejected, authorized accepted,
cross-project isolation (§29-H).

## Reconnection & resynchronization

Client states (visible in the office UI): `connecting → live`, `reconnecting`
(bounded exponential backoff 500 ms → 15 s cap with ±25% jitter — no reconnect
storms), `degraded` (NATS unavailable: gateway still replays durably; a slow visible
fallback resync loop replaces the old 2.5 s polling), `resyncing` (authoritative
reload), `offline`. After reconnect the client sends its last processed sequence as
the `since` cursor; the server replays the durable range and live resumes. Every
resync captures the sequence cursor **before** reading entities, aborts the live
stream during the swap, and reopens with the captured cursor; concurrent resyncs
coalesce into one job; a superseded session (project switch) can never apply
snapshots or stream frames (generation counter guards every callback).
`RESYNC_REQUIRED` always causes an authoritative refetch, never stale continuation.

## Backpressure & large payloads

Bounded at every hop: publisher queue (4096; overflow drops the live copy + metric),
per-connection SSE queue (256; first overflow sends `RESYNC_REQUIRED`, sustained
overflow disconnects that client only), connection cap (50, 429 on exceed), payload
cap (32 KiB — oversized events are rejected at publish and must travel as
`payload_ref` + summary), SSE heartbeats (15 s), bounded replay pages (500). One
slow browser tab can never block backend execution or other clients.

## Metrics (`/metrics`, Prometheus text format)

`harness_events_published_total{event_type}` ·
`harness_events_delivered_total` ·
`harness_events_dropped_total{reason}` ·
`harness_event_processing_latency_seconds` (commit → bus enqueue) ·
`harness_event_delivery_latency_seconds` (envelope timestamp → fan-out) ·
`harness_realtime_connections_total` (accepts; reconnects appear as new connections) ·
`harness_realtime_active_connections` · `harness_realtime_resyncs_total` ·
`harness_realtime_slow_clients_total` · `harness_realtime_stream_errors_total{kind}` ·
`harness_realtime_consumer_lag`. The bridge, bus, and gateway count drops and rejects
with explicit reasons; HTTP middleware still provides the `harness_http_*` series.

## Failure behavior

| Failure | Behavior |
|---------|----------|
| NATS unavailable | Execution unaffected (durable write first). Gateway degrades to replay-only; SSE still serves; UI shows `degraded` + visible slow resync loop |
| Gateway restart | Connections drop; clients reconnect with backoff; replay + live resume; nothing authoritative is lost |
| Frontend offline | `offline` state; reconnect with jittered backoff; resync on return |
| Slow client | Bounded queue overflows → drop + `RESYNC_REQUIRED` → eventual disconnect of the worst offender |
| Schema mismatch | Envelope rejected → `RESYNC_REQUIRED`; never applied |
| Event delivery failure | Losing a live copy is acceptable: durable row + replay/resync recover |

## Frontend event reducer

`apps/web-ui/src/state/eventReducer.ts` — pure functions: validate → dedupe →
sequence-check → project into state. `officeStore.ts` owns the connection machinery
(SSE loop, backoff, resync, degraded fallback) and applies envelopes through the
reducer; components subscribe via targeted selectors — `AGENT_STATUS_CHANGED`
updates one agent row, `TASK_COMPLETED` updates one task, the timeline prepends one
capped entry (120); no full-state refresh per event. Polling removal: the 2.5 s REST
poll is gone; the only interval that remains is an explicit slow fallback resync loop
that runs **only while degraded** (visible in the UI), plus the 15 s `/healthz`
liveness probe in the status bar, which is not part of office state.

## Configuration reference

`HARNESS_NATS_EVENTS_ENABLED` (true) · `HARNESS_NATS_EVENTS_STREAM` (`harness-events`)
· `HARNESS_NATS_EVENTS_SUBJECT_PREFIX` (`harness.events`) ·
`HARNESS_NATS_EVENTS_MAX_AGE_SECONDS` (86400) · `HARNESS_NATS_EVENTS_MAX_MSGS`
(100000) · `HARNESS_NATS_EVENTS_MAX_BYTES` (268435456) ·
`HARNESS_REALTIME_ENABLED` (true) · `HARNESS_REALTIME_MAX_CONNECTIONS` (50) ·
`HARNESS_REALTIME_CONNECTION_QUEUE_SIZE` (256) ·
`HARNESS_REALTIME_HEARTBEAT_SECONDS` (15) · `HARNESS_REALTIME_MAX_PAYLOAD_BYTES`
(32768) · `HARNESS_REALTIME_SLOW_CLIENT_MAX_DROPS` (50) ·
`HARNESS_REALTIME_REPLAY_PAGE_CAP` (500) · `HARNESS_RETENTION_EVENTS_DAYS`
(0 = keep authoritative history) · `HARNESS_RETENTION_ARTIFACTS_DAYS` (0 = off) ·
`HARNESS_RETENTION_INTERVAL_SECONDS` (3600).

## Retention

`retention_events_days` (default **0 = off**): durable event history is
authoritative audit data; deletion requires explicit opt-in.
`retention_artifacts_days` (default 0): artifact *blob files* past the window are
pruned (metadata rows kept). NATS retention is bounded separately (age 24 h /
100k msgs / 256 MiB) — pruning NATS never touches authoritative history. Prunes run
in bounded batches via the scheduled worker and `POST /api/retention/prune`.

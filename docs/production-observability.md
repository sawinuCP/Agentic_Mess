# Production Observability (Wave 11 §19)

How an operator diagnoses each failure class with existing telemetry.
No new system was introduced — everything below is already wired.

## Where to look first

| Failure | Signal | Detail |
|---|---|---|
| Execution failure | `TASK_FAILED` / `TASK_TERMINALLY_FAILED` events; workflow summary `recovery_history` | `failure_class` + `failure_detail` + evidence artifact ids on the event payload and `task.payload.terminal` |
| Agent failure | `AGENT_STATUS_CHANGED` → failed; agent row `state` | Session rows (heartbeat gaps); `replaces_agent_id` chain in `AGENT_CREATED` payloads |
| Tool failure | `TOOL_STARTED` / `TOOL_FAILED` events | `exit_code`, stderr excerpt, duration; raw output in artifacts |
| Model failure | `MODEL_SWITCHED` event; ledger `model_invocations` | Provider/model/route + token counts per task (`/intelligence/costs`) |
| Database failure | `/readyz` postgres check; `pool_pre_ping` recycle logs | Heartbeats skip (warning) while durable writes retry; chaos tests prove recovery |
| NATS failure | Gateway `degraded`; `bus_disconnected` warnings; `/readyz` nats check | Live copies drop (counted); durable replay authoritative |
| Temporal failure | Workflow task failures; `/readyz` temporal check | History replayable; activities idempotent by key |
| Realtime failure | `harness_realtime_stream_errors_total{kind}`; consumer lag gauge; DLQ subject | `<prefix>.dlq` retains poison verbatim |
| Resource exhaustion | `QUOTA_EXCEEDED` / 409s; scheduler `skipped` entries; port/lease lists | `exec_max_concurrent_per_project`, scheduler caps, port range |

## Correlation

Every span, log line and event carries a subset of: `task_id`, `agent_id`,
`attempt_id`, `recovery_id`, `event_id`, `project_id`, `correlation_id`,
`connection_id`. Worker activity spans (`temporal-activity.*`) carry ID-only
attributes + outcome/error status. Request logs carry `X-Request-ID`.

## Metrics (`/metrics`, Prometheus text)

HTTP (`harness_http_*`), events published/delivered/dropped, commit→enqueue and
envelope→fan-out latencies, connections total/active, resyncs, slow clients,
stream errors by kind, NATS consumer lag. Full list in `docs/REALTIME_EVENTS.md`.

## Secrets

Logs, events, metrics and traces never contain tokens, credentials, prompts
beyond summaries, or secret environment values (redaction filter + sanitized
spawns, both tested).

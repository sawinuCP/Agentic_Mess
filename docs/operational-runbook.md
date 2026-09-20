# Operational Runbook (Wave 12 — routine operations)

## Start / stop

```powershell
docker compose up -d                    # postgres, redis, nats, temporal
docker compose --profile temporal up -d # include temporal server
cd services/api
alembic upgrade head                    # migrations, verify with alembic current
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
python -m app.durable.worker            # temporal worker (only with temporal on)
cd ../apps/web-ui; npm run dev          # vite :5173 proxies /api
```

Stop in reverse. Workers finish in-flight activities within their timeouts;
Temporal replays unfinished workflows on restart. No manual cleanup needed
beyond `docker compose down` (add `-v` only if disposable data is acceptable).

## Daily checks

1. `/readyz` 200 with postgres ok (temporal/artifacts informative).
2. `/metrics`: consumer lag ~0, no growing `stream_errors_total{kind}`,
   no `slow_clients_total` spikes.
3. Disk: artifact dir + Postgres volume (no disk quota on containers).
4. If retention enabled: prune counts in logs; evidence blobs never deleted
   (reference-aware).

## Incident recipes

* **Task stuck running**: traceability → attempts → `TOOL_*`/recovery events;
  check worker liveness; cancel (`POST /api/tasks/{id}/cancel`) or retry.
* **Agent stuck**: sessions list → heartbeat age; Release (UI) or wait for
  supervision to mark lost; replacement chains automatically.
* **HITL unanswered**: request ages to `timeout` (fail-closed); decide or
  cancel via API; waiters proceed terminally.
* **NATS down**: UI shows degraded; execution continues; replay on return.
* **DB down**: heartbeats skip; activities retry; workflows resume post-restart.
  If corrupted: follow `disaster-recovery.md`.
* **Poison events**: inspect `<prefix>.dlq`, fix producer, purge DLQ subject.

## Configuration changes

Edit env, restart API (stateless besides pools/registries). Worker picks up
settings per activity run (no worker restart needed for most knobs).
Retention windows and budgets apply immediately to new decisions.

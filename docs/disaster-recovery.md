# Disaster Recovery (Wave 11 §18)

No automated backup infrastructure lives in this repository. This document
states the operational requirement so a deployment is not pretending.

## Recovery objectives

* **RPO**: last committed Postgres transaction + last written artifact blob.
  NATS/Redis hold no authoritative state — losing them loses nothing durable.
* **RTO**: time to restore Postgres + blobs + restart API/worker (minutes on
  this stack; rehearse it).

## Required backups

1. **PostgreSQL**: full logical backup (`pg_dump`) at least daily + WAL
   archiving for point-in-time recovery if the deployment needs it. Test
   restores — an untested backup is not a backup.
2. **Artifact blobs** (`HARNESS_ARTIFACTS_DIR` content-addressed tree):
   filesystem snapshot or rsync alongside the DB backup. Metadata rows
   reference blobs by sha — restoring one without the other breaks evidence.
3. **Configuration**: the exact environment (`HARNESS_*`), `models config`
   JSON, CORS origins, retention windows. Version them with the deployment.
4. **Alembic head**: record `alembic current` with every backup; restore =
   `upgrade head` on an empty DB then load the dump (migrations are
   forward-only; `downgrade` exists per revision for emergencies).

## Restore sequence

1. Provision Postgres, create role/db, `alembic upgrade head`.
2. Load the dump; verify `alembic current` matches the code revision.
3. Restore the blob tree to `HARNESS_ARTIFACTS_DIR`; spot-check sha paths.
4. Start API → `/readyz` 200 (postgres ok) → start worker → scheduler tick.
5. Reconciliation: tasks stuck `running` with dead sessions are reaped by
   supervision (stale → lost); re-run or cancel them explicitly. No automatic
   resurrection — a restarted task is a new run, recorded as such.

## Failure scenarios

| Scenario | Handling | Verified by |
|---|---|---|
| Container/DB restart mid-run | Pool recycles (`pre_ping`); heartbeats best-effort; durable writes retry; workflow completes | `test_postgres_restart_mid_workflow_recovers`, killed-backend test |
| Worker/API killed mid-run | Temporal replays history; activities idempotent by key; no duplicate effects | kill-9 chaos test, idempotency tests |
| NATS loss | Live copies drop; durable replay authoritative; clients resync | transport-loss chaos test, scenarios D/G |
| Single message poison | DLQ + ack; consumer never crash-loops | DLQ unit tests |
| Disk full on blobs | Writes fail loudly (no silent truncation); evidence rows reference missing blobs as 404, never as success | (operational: monitor disk; no test fabricates ENOSPC) |

## Recovery verification

After any restore: run `/readyz`, the fast eval (`EVAL-001`), and the
requirement→VERIFIED journey test. All three green before accepting traffic.

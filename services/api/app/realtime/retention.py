"""Bounded retention for realtime/event infrastructure (Wave 3, W3-RETAIN-1).

Deliberately boring: three explicit, configured prune windows —

* ``retention_events_days``  → durable ``events`` rows (authoritative history
  beyond this window is intentionally dropped; JetStream never held it),
* ``retention_artifacts_days`` → artifact *blob files* past their window (the
  content-addressed metadata rows remain; fetching a pruned blob 404s),
* NATS stream limits live in ``Settings`` (max age/msgs/bytes) — the bus is a
  recent-live projection only.

Prunes run in bounded batches so a large backlog cannot lock the database, and
are exposed as ``POST /api/retention/prune`` plus the scheduled worker loop.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Event

logger = logging.getLogger("harness.realtime.retention")


def prune_events(factory: sessionmaker[Session], older_than_days: int, batch_size: int) -> int:
    """Delete durable events older than the window (bounded batches). Returns count."""
    if older_than_days <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    removed = 0
    with factory() as session:
        while True:
            ids = session.scalars(
                select(Event.id).where(Event.occurred_at < cutoff).limit(batch_size)
            ).all()
            if not ids:
                break
            session.execute(delete(Event).where(Event.id.in_(ids)))
            session.commit()
            removed += len(ids)
            if len(ids) < batch_size:
                break
    if removed:
        logger.info("events_pruned count=%d older_than_days=%d", removed, older_than_days)
    return removed


def prune_artifact_blobs(root: Path, older_than_days: int) -> int:
    """Delete artifact blob files past the window (metadata rows are kept)."""
    if older_than_days <= 0 or not root.is_dir():
        return 0
    cutoff = datetime.now(UTC).timestamp() - timedelta(days=older_than_days).total_seconds()
    removed = 0
    for path in root.rglob("*"):
        if path.is_file() and path.suffix != ".tmp":
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError as exc:  # noqa: PERF203 — keep pruning on per-file errors
                logger.warning("artifact_prune_failed path=%s error=%s", path, exc)
    if removed:
        logger.info("artifact_blobs_pruned count=%d older_than_days=%d", removed, older_than_days)
    return removed


def run_retention(settings: Any, factory: sessionmaker[Session]) -> dict[str, int]:
    """One bounded retention pass with the configured windows (0 = disabled)."""
    return {
        "events_pruned": prune_events(
            factory, settings.retention_events_days, settings.retention_batch_size
        ),
        "artifact_blobs_pruned": prune_artifact_blobs(
            Path(settings.artifacts_dir), settings.retention_artifacts_days
        ),
    }


async def retention_worker(settings: Any, factory: sessionmaker[Session]) -> None:
    """Scheduled loop (lifespan task). Exits on cancellation; never raises."""
    import asyncio  # noqa: PLC0415

    while True:
        try:
            await asyncio.sleep(max(30, settings.retention_interval_seconds))
            results = await asyncio.to_thread(run_retention, settings, factory)
            if any(results.values()):
                logger.info("retention_pass %s", results)
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001 — retention must never kill the app
            logger.warning("retention_pass_failed error=%s", exc)

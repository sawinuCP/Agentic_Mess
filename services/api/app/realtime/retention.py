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
import uuid
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


def _protected_artifact_shas(session: Session) -> set[str]:
    """Sha256s referenced as durable evidence (never prune their blobs).

    Sources: attempt evidence lists + task terminal summaries. Event payloads
    intentionally excluded — they duplicate attempt evidence, and scanning the
    hot events table per retention pass is not worth it.
    """
    from app.db.models import Artifact, Task, TaskAttempt  # noqa: PLC0415

    ids: set[str] = set()
    for (evidence,) in session.execute(select(TaskAttempt.evidence_artifact_ids)).all():
        ids.update(str(x) for x in (evidence or []) if x)
    for (payload,) in session.execute(select(Task.payload)).all():
        terminal = (payload or {}).get("terminal") or {}
        ids.update(str(x) for x in (terminal.get("evidence_artifact_ids") or []) if x)
    parsed = []
    for raw in ids:
        try:
            parsed.append(uuid.UUID(str(raw)))
        except (ValueError, AttributeError):
            continue
    if not parsed:
        return set()
    return {
        sha
        for (sha,) in session.execute(select(Artifact.sha256).where(Artifact.id.in_(parsed))).all()
        if sha
    }


def prune_artifact_blobs(
    root: Path, older_than_days: int, factory: sessionmaker[Session] | None = None
) -> int:
    """Delete artifact blob files past the window (metadata rows are kept).

    With ``factory``, blobs referenced as durable evidence (attempt + terminal
    task refs) are spared regardless of age — retention must never delete final
    evidence. Without it (unit tests), pure age-based pruning applies.
    """
    if older_than_days <= 0 or not root.is_dir():
        return 0
    protected: set[str] = set()
    if factory is not None:
        with factory() as session:
            protected = _protected_artifact_shas(session)
    cutoff = datetime.now(UTC).timestamp() - timedelta(days=older_than_days).total_seconds()
    removed = skipped_protected = 0
    for path in root.rglob("*"):
        if path.is_file() and path.suffix != ".tmp":
            try:
                if path.stat().st_mtime < cutoff:
                    if path.name in protected:
                        skipped_protected += 1
                        continue
                    path.unlink()
                    removed += 1
            except OSError as exc:  # noqa: PERF203 — keep pruning on per-file errors
                logger.warning("artifact_prune_failed path=%s error=%s", path, exc)
    if removed or skipped_protected:
        logger.info(
            "artifact_blobs_pruned count=%d protected=%d older_than_days=%d",
            removed,
            skipped_protected,
            older_than_days,
        )
    return removed


def run_retention(settings: Any, factory: sessionmaker[Session]) -> dict[str, int]:
    """One bounded retention pass with the configured windows (0 = disabled)."""
    return {
        "events_pruned": prune_events(
            factory, settings.retention_events_days, settings.retention_batch_size
        ),
        "artifact_blobs_pruned": prune_artifact_blobs(
            Path(settings.artifacts_dir), settings.retention_artifacts_days, factory
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

"""Event recording service (FR-024): durable audit/observability events."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Event

logger = logging.getLogger("harness.events")


def _write(
    factory: sessionmaker[Session],
    event_type: str,
    project_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
    payload: Mapping[str, Any] | None,
    source: str | None,
    agent_id: str | None,
    execution_id: str | None,
    correlation_id: str | None,
) -> None:
    with factory() as session:
        session.add(
            Event(
                event_type=event_type,
                source=source or "api",
                project_id=project_id,
                task_id=task_id,
                agent_id=agent_id,
                execution_id=execution_id,
                correlation_id=correlation_id,
                payload=dict(payload or {}),
            )
        )
        session.commit()


async def record_event(
    factory: sessionmaker[Session],
    event_type: str,
    *,
    project_id: uuid.UUID | None = None,
    task_id: uuid.UUID | None = None,
    agent_id: str | None = None,
    execution_id: str | None = None,
    correlation_id: str | None = None,
    payload: Mapping[str, Any] | None = None,
    source: str | None = None,
) -> None:
    """Persist an event off the event loop; failures are logged, never raised.

    Realtime delivery is handled by the event bridge on commit (Wave 3) — this
    function stays authoritative-write-only and never touches the bus directly.
    """
    try:
        await asyncio.to_thread(
            _write,
            factory,
            event_type,
            project_id,
            task_id,
            payload,
            source,
            agent_id,
            execution_id,
            correlation_id,
        )
    except Exception as exc:  # noqa: BLE001 — observability must not break requests
        logger.warning("event_record_failed type=%s error=%s", event_type, exc)
        return


def emit_event(
    db: Session,
    event_type: str,
    *,
    source: str,
    project_id: uuid.UUID | None,
    task_id: uuid.UUID | None = None,
    agent_id: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> Event:
    """Add one durable event row in the caller's transaction (no commit).

    The single owned constructor for service/activity event writes: callers
    build domain payloads, this function owns the row shape. Replaces the
    five private ``_emit``/``_task_event`` helpers that each constructed
    ``Event`` directly.
    """
    row = Event(
        event_type=event_type,
        source=source,
        project_id=project_id,
        task_id=task_id,
        agent_id=agent_id,
        payload=dict(payload or {}),
    )
    db.add(row)
    return row

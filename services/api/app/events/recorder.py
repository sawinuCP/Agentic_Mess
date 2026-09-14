"""Write durable events to PostgreSQL. Best-effort: never breaks the main request."""

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
    payload: Mapping[str, Any] | None,
    source: str | None,
) -> None:
    with factory() as session:
        session.add(
            Event(
                event_type=event_type,
                source=source or "api",
                project_id=project_id,
                payload=dict(payload or {}),
            )
        )
        session.commit()


async def record_event(
    factory: sessionmaker[Session],
    event_type: str,
    *,
    project_id: uuid.UUID | None = None,
    payload: Mapping[str, Any] | None = None,
    source: str | None = None,
) -> None:
    """Persist an event off the event loop; failures are logged, never raised."""
    try:
        await asyncio.to_thread(_write, factory, event_type, project_id, payload, source)
    except Exception as exc:  # noqa: BLE001 — observability must not break requests
        logger.warning("event_write_failed type=%s error=%s", event_type, exc)

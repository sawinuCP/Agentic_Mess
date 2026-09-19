"""Durable event reads (FR-024): query contract owned by the core context (C2).

The HTTP route translates rows to wire shapes; all SELECT/ordering/filter
logic lives here so non-HTTP callers (replay, resync, tests) reuse one
implementation. Write path stays in ``services/core/events.py`` (Wave-12
frozen — intentionally untouched).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Event


def query_events(
    db: Session,
    *,
    project_id: uuid.UUID | None = None,
    event_type: str | None = None,
    task_id: uuid.UUID | None = None,
    since_seq: int | None = None,
    before_seq: int | None = None,
    order: str = "desc",
    limit: int = 100,
) -> list[Event]:
    """Replay the durable event stream (filterable; newest first by default)."""
    query = select(Event)
    if order == "asc":
        query = query.order_by(Event.project_seq.asc().nulls_last(), Event.occurred_at.asc())
    else:
        query = query.order_by(Event.occurred_at.desc())
    query = query.limit(limit)
    if project_id:
        query = query.where(Event.project_id == project_id)
    if event_type:
        query = query.where(Event.event_type == event_type)
    if task_id:
        query = query.where(Event.task_id == task_id)
    if since_seq is not None:
        query = query.where(Event.project_seq > since_seq)
    if before_seq is not None:
        query = query.where(Event.project_seq < before_seq)
    return list(db.scalars(query).all())

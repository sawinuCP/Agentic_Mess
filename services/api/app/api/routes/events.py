"""Durable event stream queries (FR-024; feeds the office/timeline UIs later)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models import Event

router = APIRouter(tags=["events"])


class EventOut(BaseModel):
    id: uuid.UUID
    occurred_at: str
    event_type: str
    source: str | None
    project_id: uuid.UUID | None
    task_id: uuid.UUID | None
    agent_id: str | None
    payload: dict


@router.get("/api/events", response_model=list[EventOut])
def list_events(
    project_id: uuid.UUID | None = None,
    event_type: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[EventOut]:
    """Replay the durable event stream, newest first (filterable)."""
    query = select(Event).order_by(Event.occurred_at.desc()).limit(limit)
    if project_id:
        query = query.where(Event.project_id == project_id)
    if event_type:
        query = query.where(Event.event_type == event_type)
    rows = db.scalars(query).all()
    return [
        EventOut(
            id=e.id,
            occurred_at=e.occurred_at.isoformat(),
            event_type=e.event_type,
            source=e.source,
            project_id=e.project_id,
            task_id=e.task_id,
            agent_id=e.agent_id,
            payload=e.payload or {},
        )
        for e in rows
    ]

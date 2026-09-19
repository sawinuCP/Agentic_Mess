"""Durable event stream queries (FR-024; feeds the office/timeline UIs).

Wave 3 additions: ``project_seq`` is the per-project ordering cursor used by the
realtime stream, ``since_seq`` + ``order=asc`` power authoritative replay and
resynchronization (the realtime stream is a projection — never a second truth).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.core import event_queries

router = APIRouter(tags=["events"])


class EventOut(BaseModel):
    id: uuid.UUID
    occurred_at: str
    event_type: str
    source: str | None
    project_id: uuid.UUID | None
    task_id: uuid.UUID | None
    agent_id: str | None
    execution_id: str | None
    project_seq: int | None
    correlation_id: str | None
    payload: dict


@router.get("/api/events", response_model=list[EventOut])
def list_events(
    project_id: uuid.UUID | None = None,
    event_type: str | None = None,
    task_id: uuid.UUID | None = None,
    since_seq: int | None = Query(None, ge=0),
    before_seq: int | None = Query(None, ge=0),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[EventOut]:
    """Replay the durable event stream (filterable; newest first by default).

    Wave 9 additions are strictly additive: ``before_seq`` pages backward
    (strict ``project_seq < before_seq``, mirroring ``since_seq``),
    ``task_id`` scopes to one task, and ``correlation_id`` is exposed for
    client-side chain following. Default ordering is unchanged.
    """
    rows = event_queries.query_events(
        db,
        project_id=project_id,
        event_type=event_type,
        task_id=task_id,
        since_seq=since_seq,
        before_seq=before_seq,
        order=order,
        limit=limit,
    )
    return [
        EventOut(
            id=e.id,
            occurred_at=e.occurred_at.isoformat(),
            event_type=e.event_type,
            source=e.source,
            project_id=e.project_id,
            task_id=e.task_id,
            agent_id=e.agent_id,
            execution_id=e.execution_id,
            project_seq=e.project_seq,
            correlation_id=e.correlation_id,
            payload=e.payload or {},
        )
        for e in rows
    ]

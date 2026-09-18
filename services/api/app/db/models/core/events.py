"""Event entity: durable execution events (observability + audit stream).

Wave 3: each project-scoped event carries a dense per-project monotonic
``project_seq`` assigned inside the inserting transaction via the
``event_sequences`` counter table (atomic upsert). The sequence is the ordering
scope for the realtime stream: clients detect missed events by sequence gaps and
resynchronize from this authoritative table — never from the bus.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, event, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_project_occurred", "project_id", "occurred_at"),
        Index("ix_events_execution", "execution_id"),
        Index("ix_events_correlation", "correlation_id"),
        Index("ix_events_trace", "trace_id"),
        Index("ix_events_project_seq", "project_id", "project_seq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    source: Mapped[str | None] = mapped_column(String(100), default=None)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), default=None
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), default=None
    )
    execution_id: Mapped[str | None] = mapped_column(String(64), default=None)
    agent_id: Mapped[str | None] = mapped_column(String(64), default=None)
    correlation_id: Mapped[str | None] = mapped_column(String(64), default=None)
    trace_id: Mapped[str | None] = mapped_column(String(64), default=None)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # Dense per-project sequence (NULL for events without a project scope).
    project_seq: Mapped[int | None] = mapped_column(BigInteger, default=None)


def _assign_project_seq(mapper: Any, connection: Any, target: Event) -> None:
    """Assign the next dense sequence for the target project inside the flush.

    The atomic upsert serializes concurrent inserts per project; the returned
    value is committed atomically with the event row, so committed events always
    have gapless sequences even across processes (API + Temporal worker).
    """
    if target.project_id is None:
        return
    seq = connection.execute(
        text(
            "INSERT INTO event_sequences (project_id, last_seq) VALUES (:pid, 1) "
            "ON CONFLICT (project_id) DO UPDATE SET last_seq = event_sequences.last_seq + 1 "
            "RETURNING last_seq"
        ),
        {"pid": target.project_id},
    ).scalar_one()
    target.project_seq = seq


event.listen(Event, "before_insert", _assign_project_seq)

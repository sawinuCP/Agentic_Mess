"""Knowledge entities: durable context references and typed memories (spec §15, §31)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ContextItem(Base):
    """Durable context/evidence reference with provenance (spec §15 tiering)."""

    __tablename__ = "context_items"
    __table_args__ = (
        Index("ix_context_items_project_kind", "project_id", "kind"),
        Index("ix_context_items_task", "task_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), default=None
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), default=None
    )
    tier: Mapped[int] = mapped_column(Integer, default=5)  # T0..T6 (spec §15)
    kind: Mapped[str] = mapped_column(String(50))  # code|evidence|message|artifact|memory|plan
    ref: Mapped[str] = mapped_column(String(500))  # path / artifact id / url
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    tokens_est: Mapped[int | None] = mapped_column(Integer, default=None)
    confidence: Mapped[float | None] = mapped_column(default=None)
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=func.jsonb_build_object()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Memory(Base):
    """Typed memory: FACT | EVIDENCE | DECISION | OPINION | APPROVAL (spec §31)."""

    __tablename__ = "memories"
    __table_args__ = (Index("ix_memories_project_kind", "project_id", "kind"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), default=None
    )
    scope: Mapped[str] = mapped_column(String(30), default="project")  # execution|project|agent
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), default=None
    )
    kind: Mapped[str] = mapped_column(String(20))  # FACT|EVIDENCE|DECISION|OPINION|APPROVAL
    content: Mapped[str] = mapped_column(Text)
    provenance: Mapped[str | None] = mapped_column(String(500), default=None)
    freshness_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )  # when this was last known true
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

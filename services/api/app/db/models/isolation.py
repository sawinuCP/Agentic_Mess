"""Isolation entities: git worktrees and resource leases (spec §17, §18)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Worktree(Base):
    __tablename__ = "worktrees"
    __table_args__ = (
        UniqueConstraint("project_id", "branch", name="uq_worktrees_project_branch"),
        Index("ix_worktrees_task", "task_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), default=None
    )
    branch: Mapped[str] = mapped_column(String(200))
    path: Mapped[str] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(String(30), default="active")  # active|merged|abandoned
    # Integration queue (FR-012, spec §17): controlled, ordered integration; conflicts
    # become explicit tasks instead of silent canonical-branch writes.
    integration_status: Mapped[str] = mapped_column(
        String(30), default="none", server_default="none"
    )  # none|queued|integrating|merged|conflict
    integration_position: Mapped[int | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Resource(Base):
    """Resource lease with TTL + expiry (spec §18). Release/heartbeat live in Phase 4."""

    __tablename__ = "resources"
    __table_args__ = (
        UniqueConstraint("kind", "key", name="uq_resources_kind_key"),
        Index("ix_resources_expires", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), default=None
    )
    kind: Mapped[str] = mapped_column(String(50))  # file|symbol|branch|worktree|port|runtime|tool
    key: Mapped[str] = mapped_column(String(500))
    holder_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), default=None
    )
    holder_session: Mapped[str | None] = mapped_column(String(64), default=None)
    ttl_seconds: Mapped[int] = mapped_column(Integer, default=300)
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

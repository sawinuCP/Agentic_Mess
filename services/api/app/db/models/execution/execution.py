"""Execution-plane entities (Phase 6): port allocations (spec §19.1)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PortAllocation(Base):
    """One reserved port. Expiry is computed against ``expires_at`` (leases pattern)."""

    __tablename__ = "port_allocations"
    __table_args__ = (Index("ix_port_allocations_project", "project_id", "port"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), default=None
    )
    port: Mapped[int] = mapped_column(Integer, unique=True)
    purpose: Mapped[str] = mapped_column(String(50))  # preview|service|debug
    holder: Mapped[str | None] = mapped_column(String(200), default=None)
    ttl_seconds: Mapped[int] = mapped_column(Integer, default=3600)
    allocated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

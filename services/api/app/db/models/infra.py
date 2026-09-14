"""Infrastructure entities: runtime instances and durable toolchain configs (spec §29)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RuntimeInstance(Base):
    """Containers/processes/browser sessions started by the harness (spec §19.1, §20)."""

    __tablename__ = "runtime_instances"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), default=None
    )
    kind: Mapped[str] = mapped_column(String(50))  # docker|process|browser|preview
    reference: Mapped[str] = mapped_column(String(300))  # container id / pid / ws url
    ports: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default=func.jsonb_build_array()
    )
    status: Mapped[str] = mapped_column(String(30), default="running")  # running|stopped|failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class ToolchainConfig(Base):
    """Durable, resolved toolchain configuration per project+language (spec §29)."""

    __tablename__ = "toolchains"
    __table_args__ = (
        UniqueConstraint("project_id", "language", name="uq_toolchains_project_language"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    language: Mapped[str] = mapped_column(String(50))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(
        String(30), default="project_override"
    )  # builtin|project_override
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

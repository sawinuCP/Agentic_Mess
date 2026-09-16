"""Artifact entity: metadata for files/logs/screenshots/reports/evidence (spec §19)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        Index("ix_artifacts_project_created", "project_id", "created_at"),
        Index("ix_artifacts_sha", "sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), default=None
    )
    name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(
        String(50), default="raw_output"
    )  # raw_output|screenshot|report|file|evidence
    mime: Mapped[str] = mapped_column(String(100), default="text/plain")
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(String(1024))  # relative to the artifacts root
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

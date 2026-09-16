"""Code-intelligence entities (Phase 5): symbol index + model cost ledger (spec §15, §32)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

EMBEDDING_DIM = 256


class SymbolFile(Base):
    """One indexed file: language + content hash drive incremental re-indexing (PERF-008)."""

    __tablename__ = "symbol_files"
    __table_args__ = (Index("ix_symbol_files_project", "project_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(String(1024))
    language: Mapped[str] = mapped_column(String(30))
    sha256: Mapped[str] = mapped_column(String(64))
    symbol_count: Mapped[int] = mapped_column(Integer, default=0)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Symbol(Base):
    """A structural symbol (class/function/method/…) extracted from one indexed file."""

    __tablename__ = "symbols"
    __table_args__ = (
        Index("ix_symbols_project_name", "project_id", "name"),
        Index("ix_symbols_file", "file_id"),
        Index("ix_symbols_project_kind", "project_id", "kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("symbol_files.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(30))  # class|function|method|interface|struct|…
    parent: Mapped[str | None] = mapped_column(String(300), default=None)
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    signature: Mapped[str | None] = mapped_column(Text, default=None)
    doc: Mapped[str | None] = mapped_column(Text, default=None)
    # pgvector embedding for hybrid retrieval (local hashing embedder, dim fixed 256).
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)


class ModelInvocation(Base):
    """One model call with token accounting — the budget/cost ledger (spec §32)."""

    __tablename__ = "model_invocations"
    __table_args__ = (
        Index("ix_model_invocations_task", "task_id", "created_at"),
        Index("ix_model_invocations_project", "project_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), default=None
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), default=None
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), default=None
    )
    role: Mapped[str] = mapped_column(String(50))
    provider: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(200))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Any] = mapped_column(Numeric(12, 6), default=None)
    latency_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

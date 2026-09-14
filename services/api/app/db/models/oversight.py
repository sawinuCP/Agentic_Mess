"""Oversight entities: decisions, reviews, validations, HITL (spec §23-25)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = (Index("ix_decisions_project", "project_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), default=None
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), default=None
    )
    title: Mapped[str] = mapped_column(String(300))
    rationale: Mapped[str | None] = mapped_column(Text, default=None)
    kind: Mapped[str] = mapped_column(
        String(50), default="architecture"
    )  # architecture|engineering|scope|approval
    made_by: Mapped[str | None] = mapped_column(String(200), default=None)  # agent id or "human"
    status: Mapped[str] = mapped_column(
        String(30), default="proposed"
    )  # proposed|accepted|rejected|superseded
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Review(Base):
    """Independent review/adjudication record (spec §24)."""

    __tablename__ = "reviews"
    __table_args__ = (
        Index("ix_reviews_decision", "decision_id"),
        Index("ix_reviews_task", "task_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("decisions.id", ondelete="SET NULL"), default=None
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), default=None
    )
    reviewer_role: Mapped[str] = mapped_column(
        String(50)
    )  # reviewer|critic|evidence_verifier|adjudicator
    verdict: Mapped[str] = mapped_column(
        String(30), default="unknown"
    )  # approve|reject|needs_evidence|unknown
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    rounds: Mapped[int] = mapped_column(Integer, default=1)
    model: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Validation(Base):
    """Test/build/lint/security/requirement verification with evidence link."""

    __tablename__ = "validations"
    __table_args__ = (
        Index("ix_validations_project_kind", "project_id", "kind"),
        Index("ix_validations_criterion", "acceptance_criterion_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), default=None
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), default=None
    )
    acceptance_criterion_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("acceptance_criteria.id", ondelete="SET NULL"), default=None
    )
    kind: Mapped[str] = mapped_column(String(50))  # test|build|lint|security|requirement
    status: Mapped[str] = mapped_column(
        String(30), default="pending"
    )  # pending|passed|failed|error
    evidence_artifact_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=func.jsonb_build_object()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HitlRequest(Base):
    """Human decision point: fail-closed by policy (spec §25)."""

    __tablename__ = "hitl_requests"
    __table_args__ = (
        Index("ix_hitl_requests_project_status", "project_id", "status"),
        Index("ix_hitl_requests_task", "task_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), default=None
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), default=None
    )
    kind: Mapped[str] = mapped_column(
        String(50)
    )  # approve_plan|approve_command|approve_merge|question|...
    question: Mapped[str] = mapped_column(Text)
    choices: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default=func.jsonb_build_array()
    )
    risk: Mapped[str] = mapped_column(String(30), default="medium")  # low|medium|high
    status: Mapped[str] = mapped_column(
        String(30), default="pending"
    )  # pending|approved|rejected|modified|timeout
    decided_by: Mapped[str | None] = mapped_column(String(200), default=None)
    decision_note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

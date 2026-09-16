"""Task and task-attempt entities implementing the Task Protocol (spec §13)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Task(Base):
    """Durable work unit. Task state lives here — never in an agent process (TASK-002)."""

    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_project_status", "project_id", "status"),
        Index("ix_tasks_plan", "plan_id"),
        Index("ix_tasks_requirement", "requirement_id"),
        Index("ix_tasks_parent", "parent_task_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("plans.id", ondelete="SET NULL"), default=None
    )
    requirement_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("requirements.id", ondelete="SET NULL"), default=None
    )
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), default=None
    )
    title: Mapped[str] = mapped_column(String(300))
    request: Mapped[str] = mapped_column(Text)
    expected_output: Mapped[str | None] = mapped_column(Text, default=None)
    constraints: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=func.jsonb_build_object()
    )
    acceptance_criteria: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default=func.jsonb_build_array()
    )
    allowed_tools: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default=func.jsonb_build_array()
    )
    context_refs: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default=func.jsonb_build_array()
    )
    retry_policy: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=func.jsonb_build_object()
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=func.jsonb_build_object()
    )
    priority: Mapped[int] = mapped_column(Integer, default=5)  # 1 = highest
    status: Mapped[str] = mapped_column(String(30), default="pending")
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dependency"),
        Index("ix_task_dependencies_depends_on", "depends_on_task_id"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    depends_on_task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )


class TaskAttempt(Base):
    """Every (task × attempt × agent) with outcome + evidence (TASK-003, REC-001)."""

    __tablename__ = "task_attempts"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_number", name="uq_task_attempt_number"),
        Index("ix_task_attempts_task", "task_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    attempt_number: Mapped[int] = mapped_column(Integer)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), default=None
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    outcome: Mapped[str | None] = mapped_column(
        String(30), default=None
    )  # success|failed|cancelled|timeout
    failure_class: Mapped[str | None] = mapped_column(String(50), default=None)  # spec §26 classes
    failure_detail: Mapped[str | None] = mapped_column(Text, default=None)
    evidence_artifact_ids: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default=func.jsonb_build_array()
    )

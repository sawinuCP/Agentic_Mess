"""Worktree + integration-queue DTOs (FR-012, spec §17)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class WorktreeCreateIn(BaseModel):
    task_id: UUID | None = None
    branch: str | None = Field(None, max_length=200)  # default: agent/task-<short-id>
    # Client-generated per logical operation: a retried create with the same
    # key returns the live worktree (HTTP 200) instead of re-running git.
    idempotency_key: str | None = Field(None, max_length=64)


class WorktreeOut(BaseModel):
    id: UUID
    project_id: UUID
    task_id: UUID | None
    branch: str
    path: str
    status: str  # active|merged|abandoned
    integration_status: str  # none|queued|integrating|merged|conflict
    integration_position: int | None
    created_at: datetime


class IntegrationOut(BaseModel):
    """Outcome of one controlled integration step (spec §17)."""

    worktree: WorktreeOut | None  # None when the queue is empty
    merged: bool
    commit: str | None = None
    conflict_task_id: UUID | None = None
    message: str

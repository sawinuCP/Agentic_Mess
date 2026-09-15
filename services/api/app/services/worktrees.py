"""Worktree isolation + integration queue (FR-012, spec §17).

Durable side only: git operations live in ``app.gitops.client`` and are driven by
the routes; this service owns the worktree records, the queue order, and the
explicit-conflict-task rule ("conflicts are treated as explicit tasks").
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.models import Event, Task, Worktree
from app.schemas.worktrees import WorktreeOut

VALID_BRANCH_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/._-")


def _wt_out(worktree: Worktree) -> WorktreeOut:
    return WorktreeOut(
        id=worktree.id,
        project_id=worktree.project_id,
        task_id=worktree.task_id,
        branch=worktree.branch,
        path=worktree.path,
        status=worktree.status,
        integration_status=worktree.integration_status,
        integration_position=worktree.integration_position,
        created_at=worktree.created_at,
    )


def _emit(db: Session, event_type: str, worktree: Worktree, extra: dict[str, Any]) -> None:
    db.add(
        Event(
            event_type=event_type,
            source="worktrees",
            project_id=worktree.project_id,
            task_id=worktree.task_id,
            payload={
                "worktree_id": str(worktree.id),
                "branch": worktree.branch,
                "path": worktree.path,
                **extra,
            },
        )
    )


def sanitize_branch(branch: str) -> str:
    """Branch-name hygiene: no whitespace, colons or shell-hostile characters."""
    branch = (branch or "").strip()
    if not branch or not set(branch) <= VALID_BRANCH_CHARS or branch.startswith("-"):
        raise DomainError(f"invalid branch name: {branch!r}", 422)
    return branch


def ensure_branch_free(db: Session, project_id: uuid.UUID, branch: str) -> None:
    """An agent must never take over another active worktree's branch (spec §17)."""
    existing = db.scalar(
        select(Worktree).where(
            Worktree.project_id == project_id,
            Worktree.branch == branch,
            Worktree.status == "active",
        )
    )
    if existing is not None:
        raise DomainError(f"branch {branch!r} is already an active worktree ({existing.path})", 409)


def register(
    db: Session,
    project_id: uuid.UUID,
    task_id: uuid.UUID | None,
    branch: str,
    path: str,
) -> WorktreeOut:
    """Record a freshly created worktree (or re-activate an abandoned one)."""
    existing = db.scalar(
        select(Worktree).where(Worktree.project_id == project_id, Worktree.branch == branch)
    )
    worktree = existing or Worktree(project_id=project_id, branch=branch)
    worktree.task_id = task_id if task_id is not None else worktree.task_id
    worktree.path = path
    worktree.status = "active"
    worktree.integration_status = "none"
    worktree.integration_position = None
    db.add(worktree)
    _emit(db, "WORKTREE_CREATED", worktree, {})
    db.commit()
    return _wt_out(worktree)


def list_worktrees(
    db: Session, project_id: uuid.UUID, status: str | None, limit: int
) -> list[WorktreeOut]:
    rows = db.scalars(
        select(Worktree)
        .where(Worktree.project_id == project_id)
        .order_by(Worktree.created_at.desc())
    ).all()
    out = [_wt_out(w) for w in rows]
    if status is not None:
        out = [w for w in out if w.status == status]
    return out[:limit]


def _worktree_or_404(db: Session, worktree_id: uuid.UUID) -> Worktree:
    worktree = db.get(Worktree, worktree_id)
    if worktree is None:
        raise DomainError("Worktree not found", 404)
    return worktree


def get_worktree(db: Session, worktree_id: uuid.UUID) -> WorktreeOut:
    """Fetch one worktree record (404 when unknown)."""
    return _wt_out(_worktree_or_404(db, worktree_id))


def release(db: Session, worktree_id: uuid.UUID, *, merged: bool) -> WorktreeOut:
    """Mark a worktree finished. Failed/abandoned attempts stay inspectable (spec §17)."""
    worktree = _worktree_or_404(db, worktree_id)
    if worktree.status == "active":
        worktree.status = "merged" if merged else "abandoned"
        db.add(worktree)
        _emit(db, "WORKTREE_RELEASED", worktree, {"merged": merged})
        db.commit()
    return _wt_out(worktree)


def enqueue(db: Session, worktree_id: uuid.UUID) -> WorktreeOut:
    """Append a worktree to the controlled integration queue (FIFO)."""
    worktree = _worktree_or_404(db, worktree_id)
    if worktree.status != "active":
        raise DomainError("only active worktrees can be queued for integration", 409)
    if worktree.integration_status == "queued":
        return _wt_out(worktree)  # idempotent
    if worktree.integration_status == "integrating":
        raise DomainError("worktree integration is already in progress", 409)
    if worktree.integration_status == "conflict":
        raise DomainError(
            "worktree has a recorded conflict; resolve its explicit conflict task first", 409
        )
    max_position = db.scalar(
        select(func.max(Worktree.integration_position)).where(
            Worktree.integration_status == "queued"
        )
    )
    worktree.integration_status = "queued"
    worktree.integration_position = (int(max_position) + 1) if max_position is not None else 1
    db.add(worktree)
    _emit(db, "WORKTREE_QUEUED", worktree, {"position": worktree.integration_position})
    db.commit()
    return _wt_out(worktree)


def next_queued(db: Session, project_id: uuid.UUID) -> Worktree | None:
    return db.scalar(
        select(Worktree)
        .where(
            Worktree.project_id == project_id,
            Worktree.integration_status == "queued",
        )
        .order_by(Worktree.integration_position)
    )


def mark_integration(db: Session, worktree_id: uuid.UUID, status: str) -> WorktreeOut:
    """Advance the integration state machine: queued→integrating→merged|conflict."""
    worktree = _worktree_or_404(db, worktree_id)
    allowed = {"queued": {"integrating"}, "integrating": {"merged", "conflict"}}
    if status not in allowed.get(worktree.integration_status, set()):
        raise DomainError(
            f"invalid integration transition {worktree.integration_status!r} -> {status!r}", 409
        )
    worktree.integration_status = status
    worktree.integration_position = None
    if status == "merged":
        worktree.status = "merged"
        _emit(db, "INTEGRATION_MERGED", worktree, {})
    elif status == "conflict":
        _emit(db, "INTEGRATION_CONFLICT", worktree, {})
    else:
        _emit(db, "INTEGRATION_STARTED", worktree, {})
    db.add(worktree)
    db.commit()
    return _wt_out(worktree)


def create_conflict_task(db: Session, worktree: Worktree, detail: str) -> Task:
    """Spec §17: conflicts are explicit tasks, never silent canonical writes."""
    task = Task(
        project_id=worktree.project_id,
        parent_task_id=worktree.task_id,
        title=f"Resolve integration conflict: {worktree.branch}",
        request=(
            f"The worktree branch {worktree.branch!r} conflicts with the canonical branch "
            f"during controlled integration. Resolve manually or with an integration agent. "
            f"Detail: {detail}"
        ),
        expected_output="Canonical branch integrates the worktree changes without conflicts.",
        payload={
            "role": "integration",
            "conflict_worktree_id": str(worktree.id),
            "branch": worktree.branch,
        },
        status="ready",
        priority=1,
    )
    db.add(task)
    db.commit()
    return task

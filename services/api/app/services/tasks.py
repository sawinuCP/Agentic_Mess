"""Task service: durable reads, cancellation and execution dispatch (FR-006, FR-014)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.models import Task, TaskAttempt, TaskDependency
from app.schemas.tasks import AttemptOut, TaskOut


def _task_or_404(task_id: uuid.UUID, db: Session) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise DomainError("Task not found", 404)
    return task


def task_out(db: Session, task: Task) -> TaskOut:
    depends_on = list(
        db.scalars(
            select(TaskDependency.depends_on_task_id).where(TaskDependency.task_id == task.id)
        ).all()
    )
    attempts = db.scalars(
        select(TaskAttempt)
        .where(TaskAttempt.task_id == task.id)
        .order_by(TaskAttempt.attempt_number)
    ).all()
    return TaskOut(
        id=task.id,
        project_id=task.project_id,
        plan_id=task.plan_id,
        requirement_id=task.requirement_id,
        parent_task_id=task.parent_task_id,
        title=task.title,
        request=task.request,
        expected_output=task.expected_output,
        priority=task.priority,
        status=task.status,
        payload=task.payload or {},
        retry_policy=task.retry_policy or {},
        depends_on=depends_on,
        attempts=[
            AttemptOut(
                id=a.id,
                attempt_number=a.attempt_number,
                agent_id=a.agent_id,
                outcome=a.outcome,
                failure_class=a.failure_class,
                failure_detail=a.failure_detail,
                evidence_artifact_ids=[str(x) for x in (a.evidence_artifact_ids or [])],
            )
            for a in attempts
        ],
    )


def list_tasks(db: Session, project_id: uuid.UUID, status: str | None) -> list[TaskOut]:
    query = select(Task).where(Task.project_id == project_id)
    if status:
        query = query.where(Task.status == status)
    rows = db.scalars(query.order_by(Task.priority, Task.created_at)).all()
    return [task_out(db, t) for t in rows]


def get_task(db: Session, task_id: uuid.UUID) -> TaskOut:
    return task_out(db, _task_or_404(task_id, db))


def cancel_task(db: Session, task_id: uuid.UUID) -> TaskOut:
    """Human intervention: cancel a task without destroying its history (FR-014)."""
    task = _task_or_404(task_id, db)
    if task.status in ("completed", "cancelled"):
        raise DomainError(f"Task already terminal: {task.status}", 409)
    task.status = "cancelled"
    db.commit()
    return task_out(db, task)


def mark_status(db: Session, task_id: uuid.UUID, status: str) -> Task:
    task = _task_or_404(task_id, db)
    task.status = status
    db.commit()
    return task

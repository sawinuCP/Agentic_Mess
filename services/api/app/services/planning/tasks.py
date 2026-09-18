"""Task service: durable reads, cancellation and execution dispatch (FR-006, FR-014)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.models import Task, TaskAttempt, TaskDependency
from app.schemas.planning.tasks import AttemptOut, TaskIn, TaskOut


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
    return _task_out(task, depends_on, attempts)


def _task_out(task: Task, depends_on: list[uuid.UUID], attempts: Sequence[TaskAttempt]) -> TaskOut:
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
    if not rows:
        return []
    # Keep the related-data query scope identical to the task filter, without
    # materializing an unbounded IN parameter list or doing two queries per row.
    selected_ids = select(Task.id).where(Task.project_id == project_id)
    if status:
        selected_ids = selected_ids.where(Task.status == status)
    dependencies: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for task_id, dependency_id in db.execute(
        select(TaskDependency.task_id, TaskDependency.depends_on_task_id).where(
            TaskDependency.task_id.in_(selected_ids)
        )
    ):
        dependencies[task_id].append(dependency_id)
    attempts: dict[uuid.UUID, list[TaskAttempt]] = defaultdict(list)
    for attempt in db.scalars(
        select(TaskAttempt)
        .where(TaskAttempt.task_id.in_(selected_ids))
        .order_by(TaskAttempt.task_id, TaskAttempt.attempt_number)
    ):
        attempts[attempt.task_id].append(attempt)
    return [_task_out(task, dependencies[task.id], attempts[task.id]) for task in rows]


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


def create_task(
    db: Session,
    project_id: uuid.UUID,
    body: TaskIn,
) -> TaskOut:
    """Human-authored task creation (Wave 7 completion): a pending task with
    validated project-scoped links. Mirrors the plan-creation validation
    (unknown/foreign dependencies rejected) without the batch cycle check —
    a fresh task cannot close a cycle since nothing references it yet."""
    from app.db.models import Requirement  # noqa: PLC0415 — keep module import graph flat

    requirement_id = body.requirement_id
    if requirement_id is not None:
        requirement = db.get(Requirement, requirement_id)
        if requirement is None:
            raise DomainError("Requirement not found", 404)
        if requirement.project_id != project_id:
            raise DomainError("Requirement belongs to a different project", 422)
    parent_id = body.parent_task_id
    if parent_id is not None:
        parent = db.get(Task, parent_id)
        if parent is None:
            raise DomainError("Parent task not found", 404)
        if parent.project_id != project_id:
            raise DomainError("Parent task belongs to a different project", 422)
    for dependency_id in body.depends_on:
        dependency = db.get(Task, dependency_id)
        if dependency is None or dependency.project_id != project_id:
            raise DomainError(
                f"Unknown dependency '{dependency_id}' (must be a task of this project)", 422
            )
    task = Task(
        project_id=project_id,
        requirement_id=requirement_id,
        parent_task_id=parent_id,
        title=body.title,
        request=body.request,
        priority=body.priority,
    )
    db.add(task)
    db.flush()
    for dependency_id in dict.fromkeys(body.depends_on):
        db.add(TaskDependency(task_id=task.id, depends_on_task_id=dependency_id))
    db.commit()
    return task_out(db, task)


def mark_status(db: Session, task_id: uuid.UUID, status: str) -> Task:
    task = _task_or_404(task_id, db)
    task.status = status
    db.commit()
    return task

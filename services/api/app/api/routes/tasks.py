"""Task endpoints: durable reads, cancellation (human intervention) and execution."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.core.errors import DomainError
from app.db.models import Project, Task, TaskAttempt, TaskDependency
from app.durable.client import DurableTasks
from app.events.recorder import record_event

router = APIRouter(tags=["tasks"])


class AttemptOut(BaseModel):
    id: uuid.UUID
    attempt_number: int
    agent_id: uuid.UUID | None
    outcome: str | None
    failure_class: str | None
    failure_detail: str | None
    evidence_artifact_ids: list[str]


class TaskOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    plan_id: uuid.UUID | None
    requirement_id: uuid.UUID | None
    parent_task_id: uuid.UUID | None
    title: str
    request: str
    expected_output: str | None
    priority: int
    status: str
    payload: dict
    retry_policy: dict
    depends_on: list[uuid.UUID]
    attempts: list[AttemptOut]


class ExecuteOut(BaseModel):
    started: bool
    workflow_id: str | None = None
    detail: str | None = None


def _task_or_404(task_id: uuid.UUID, db: Session) -> Task:
    task = db.get(Task, task_id)
    if task is None:
        raise DomainError("Task not found", 404)
    return task


def _task_out(db: Session, task: Task) -> TaskOut:
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


@router.get("/api/projects/{project_id}/tasks", response_model=list[TaskOut])
def list_tasks(
    project: Project = Depends(get_project),
    status: str | None = None,
    db: Session = Depends(get_db),
) -> list[TaskOut]:
    query = select(Task).where(Task.project_id == project.id)
    if status:
        query = query.where(Task.status == status)
    rows = db.scalars(query.order_by(Task.priority, Task.created_at)).all()
    return [_task_out(db, t) for t in rows]


@router.get("/api/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: uuid.UUID, db: Session = Depends(get_db)) -> TaskOut:
    return _task_out(db, _task_or_404(task_id, db))


@router.post("/api/tasks/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(
    task_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> TaskOut:
    """Human intervention: cancel a task without destroying its history (FR-014)."""
    task = _task_or_404(task_id, db)
    if task.status in ("completed", "cancelled"):
        raise DomainError(f"Task already terminal: {task.status}", 409)
    task.status = "cancelled"
    db.commit()
    await record_event(
        request.app.state.session_factory,
        "TASK_CANCELLED",
        project_id=task.project_id,
        task_id=task.id,
        payload={"by": "user"},
    )
    return _task_out(db, task)


@router.post("/api/tasks/{task_id}/execute", response_model=ExecuteOut)
async def execute_task(
    task_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
) -> ExecuteOut:
    """Start the durable TaskExecutionWorkflow via Temporal (fail-closed 503 if disabled)."""
    task = _task_or_404(task_id, db)
    durable = DurableTasks(request.app.state.settings)
    try:
        handle = await durable.start_task_execution(task.id)
    except Exception as exc:  # noqa: BLE001 — DurableUnavailable or connection issue
        raise DomainError(str(getattr(exc, "message", exc)), 503) from None
    task.status = "ready"
    db.commit()
    await record_event(
        request.app.state.session_factory,
        "TASK_EXECUTION_STARTED",
        project_id=task.project_id,
        task_id=task.id,
        payload={"workflow_id": handle["workflow_id"]},
    )
    return ExecuteOut(started=True, workflow_id=handle["workflow_id"])

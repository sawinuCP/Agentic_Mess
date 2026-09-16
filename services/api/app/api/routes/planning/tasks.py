"""Task endpoints: durable reads, cancellation (FR-014) and execution dispatch."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.core.errors import DomainError
from app.db.models import Project
from app.durable.client import DurableTasks
from app.schemas.planning.tasks import ExecuteOut, TaskOut
from app.services.core import events as event_service
from app.services.planning import tasks as task_service

router = APIRouter(tags=["tasks"])


@router.get("/api/projects/{project_id}/tasks", response_model=list[TaskOut])
async def list_tasks(
    project: Project = Depends(get_project),
    status: str | None = None,
    db: Session = Depends(get_db),
) -> list[TaskOut]:
    return await asyncio.to_thread(task_service.list_tasks, db, project.id, status)


@router.get("/api/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: uuid.UUID, db: Session = Depends(get_db)) -> TaskOut:
    return await asyncio.to_thread(task_service.get_task, db, task_id)


@router.post("/api/tasks/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(
    task_id: uuid.UUID, request: Request, db: Session = Depends(get_db)
) -> TaskOut:
    """Human intervention: cancel a task without destroying its history (FR-014)."""
    task = await asyncio.to_thread(task_service.cancel_task, db, task_id)
    await event_service.record_event(
        request.app.state.session_factory,
        "TASK_CANCELLED",
        project_id=task.project_id,
        task_id=task.id,
        payload={"by": "user"},
    )
    return task


@router.post("/api/tasks/{task_id}/pause", status_code=204)
async def pause_task(task_id: uuid.UUID, request: Request) -> None:
    """Pause: the workflow reaches a safe checkpoint and suspends new work (FR-015)."""
    durable = DurableTasks(request.app.state.settings)
    try:
        await durable.signal_task(task_id, "pause")
    except Exception as exc:  # noqa: BLE001 — unavailable/disabled maps to 503
        raise DomainError(str(getattr(exc, "message", exc)), 503) from None


@router.post("/api/tasks/{task_id}/resume", status_code=204)
async def resume_task(task_id: uuid.UUID, request: Request) -> None:
    """Resume a paused task from its durable checkpoint (FR-015)."""
    durable = DurableTasks(request.app.state.settings)
    try:
        await durable.signal_task(task_id, "resume")
    except Exception as exc:  # noqa: BLE001 — unavailable/disabled maps to 503
        raise DomainError(str(getattr(exc, "message", exc)), 503) from None


@router.post("/api/tasks/{task_id}/execute", response_model=ExecuteOut)
async def execute_task(
    task_id: uuid.UUID, request: Request, db: Session = Depends(get_db)
) -> ExecuteOut:
    """Start the durable TaskExecutionWorkflow via Temporal (fail-closed 503 if disabled)."""
    task = await asyncio.to_thread(task_service.get_task, db, task_id)
    durable = DurableTasks(request.app.state.settings)
    if not durable.enabled:
        raise DomainError(
            "Temporal integration is disabled (set HARNESS_TEMPORAL_ENABLED=true and start "
            "the 'temporal' compose profile)",
            503,
        )
    handle: dict[str, str]
    try:
        handle = await durable.start_task_execution(task.id)
    except Exception as exc:  # noqa: BLE001 — connect failures map to 503
        raise DomainError(str(getattr(exc, "message", exc)), 503) from None
    await asyncio.to_thread(task_service.mark_status, db, task.id, "ready")
    await event_service.record_event(
        request.app.state.session_factory,
        "TASK_EXECUTION_STARTED",
        project_id=task.project_id,
        task_id=task.id,
        payload={"workflow_id": handle["workflow_id"]},
    )
    return ExecuteOut(started=True, workflow_id=handle["workflow_id"])

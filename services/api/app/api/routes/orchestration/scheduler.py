"""Scheduler endpoints (FR-009/011, PERF-003): bounded scheduling passes.

Fail-closed posture, consistent with task execution: when Temporal is disabled the
tick endpoint returns 503 instead of scheduling tasks it cannot durably start.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import asdict

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.core.errors import DomainError
from app.db.models import Project
from app.durable.client import DurableTasks
from app.schemas.orchestration.scheduler import (
    ScheduleEntryOut,
    SchedulerStateOut,
    SchedulerTickOut,
)
from app.services.orchestration import scheduler as scheduler_service
from app.services.orchestration.scheduler import SchedulingLimits

router = APIRouter(tags=["scheduler"])


@router.post("/api/projects/{project_id}/scheduler/tick", response_model=SchedulerTickOut)
async def scheduler_tick(
    request: Request, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> SchedulerTickOut:
    settings = request.app.state.settings
    if not settings.scheduler_enabled:
        raise DomainError("Scheduler is disabled (HARNESS_SCHEDULER_ENABLED=false)", 503)
    durable = DurableTasks(settings)
    if not durable.enabled:
        raise DomainError(
            "Temporal integration is disabled (set HARNESS_TEMPORAL_ENABLED=true and start "
            "the 'temporal' compose profile)",
            503,
        )
    limits = SchedulingLimits.from_settings(settings)
    tick = await asyncio.to_thread(scheduler_service.plan_schedule, db, project.id, limits)

    started: dict[uuid.UUID, str] = {}
    start_errors: dict[str, str] = {}
    for entry in tick.scheduled:
        try:
            handle = await durable.start_task_execution(entry.task_id)
        except Exception as exc:  # noqa: BLE001 — per-task start failures skip, not abort
            start_errors[str(entry.task_id)] = str(getattr(exc, "message", exc))
            continue
        started[entry.task_id] = handle["workflow_id"]

    started_count = await asyncio.to_thread(
        scheduler_service.commit_scheduled, db, project.id, started
    )
    return SchedulerTickOut(
        project_id=project.id,
        running=tick.running + started_count,
        limits={
            "max_concurrency": limits.max_concurrency,
            "role_limits": dict(limits.role_limits),
            "spawn_max_depth": limits.spawn_max_depth,
        },
        scheduled=[ScheduleEntryOut(**asdict(e)) for e in tick.scheduled],
        skipped=[ScheduleEntryOut(**asdict(e)) for e in tick.skipped],
        started_count=started_count,
        start_errors=start_errors,
    )


@router.get("/api/projects/{project_id}/scheduler/state", response_model=SchedulerStateOut)
async def scheduler_state(
    request: Request, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> SchedulerStateOut:
    limits = SchedulingLimits.from_settings(request.app.state.settings)
    state = await asyncio.to_thread(scheduler_service.scheduler_state, db, project.id, limits)
    return SchedulerStateOut(**state)

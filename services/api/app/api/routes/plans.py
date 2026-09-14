"""Plan endpoints: requirement decomposition into durable task graphs (FR-006)."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.requirements import PlanIn, PlanOut
from app.services import events as event_service
from app.services import plans as plan_service
from app.services import requirements as requirement_service

router = APIRouter(tags=["plans"])


@router.post("/api/requirements/{requirement_id}/plans", response_model=PlanOut, status_code=201)
async def create_plan(
    requirement_id: uuid.UUID,
    body: PlanIn,
    request: Request,
    db: Session = Depends(get_db),
) -> PlanOut:
    plan = await asyncio.to_thread(plan_service.create_plan, db, requirement_id, body)
    requirement = await asyncio.to_thread(requirement_service.get_requirement, db, requirement_id)
    await event_service.record_event(
        request.app.state.session_factory,
        "PLAN_CREATED",
        project_id=requirement.project_id,
        payload={
            "plan_id": str(plan.id),
            "requirement_id": str(requirement_id),
            "tasks": len(body.tasks),
        },
    )
    return plan

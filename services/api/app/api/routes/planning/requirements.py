"""Requirement endpoints (FR-005, TASK-001)."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.db.models import Project
from app.schemas.planning.requirements import RequirementIn, RequirementOut
from app.services.core import events as event_service
from app.services.planning import requirements as requirement_service

router = APIRouter(tags=["requirements"])


@router.post(
    "/api/projects/{project_id}/requirements",
    response_model=RequirementOut,
    status_code=201,
)
async def create_requirement(
    body: RequirementIn,
    request: Request,
    project: Project = Depends(get_project),
    db: Session = Depends(get_db),
) -> RequirementOut:
    requirement = await asyncio.to_thread(
        requirement_service.create_requirement, db, project.id, body
    )
    await event_service.record_event(
        request.app.state.session_factory,
        "REQUIREMENT_CREATED",
        project_id=project.id,
        payload={"requirement_id": str(requirement.id), "title": requirement.title[:200]},
    )
    return requirement_service.requirement_out(db, requirement)


@router.get("/api/projects/{project_id}/requirements", response_model=list[RequirementOut])
async def list_requirements(
    project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> list[RequirementOut]:
    return await asyncio.to_thread(requirement_service.list_requirements, db, project.id)


@router.get("/api/requirements/{requirement_id}", response_model=RequirementOut)
async def get_requirement(
    requirement_id: uuid.UUID, db: Session = Depends(get_db)
) -> RequirementOut:
    return await asyncio.to_thread(requirement_service.get_requirement, db, requirement_id)

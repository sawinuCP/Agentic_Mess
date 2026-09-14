"""Project lifecycle endpoints (FR-001)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.db.models import Project
from app.schemas.projects import ProjectOpenRequest, ProjectOut
from app.services import events as event_service
from app.services import projects as project_service

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("/open", response_model=ProjectOut)
async def open_project(
    body: ProjectOpenRequest, request: Request, db: Session = Depends(get_db)
) -> ProjectOut:
    project = await asyncio.to_thread(project_service.open_project, db, body.root_path, body.name)
    await event_service.record_event(
        request.app.state.session_factory,
        "PROJECT_OPENED",
        project_id=project.id,
        payload={"root_path": project.root_path, "name": project.name},
    )
    return project


@router.get("", response_model=list[ProjectOut])
async def list_projects(db: Session = Depends(get_db)) -> list[ProjectOut]:
    return await asyncio.to_thread(project_service.list_projects, db)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project_dto(project: Project = Depends(get_project)) -> ProjectOut:
    return project_service.project_out(project)


@router.delete("/{project_id}", status_code=204)
def delete_project(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> None:
    project_service.delete_project(db, project)

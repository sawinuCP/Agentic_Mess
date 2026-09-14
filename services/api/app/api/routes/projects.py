"""Project lifecycle endpoints: open/list/get/delete local projects (FR-001)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.db.models import Project
from app.events.recorder import record_event

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectOpenRequest(BaseModel):
    root_path: str
    name: str | None = None


class ProjectOut(BaseModel):
    id: UUID
    name: str
    root_path: str
    default_branch: str


def _dto(project: Project) -> ProjectOut:
    return ProjectOut(
        id=project.id,
        name=project.name,
        root_path=project.root_path,
        default_branch=project.default_branch,
    )


def _unique_name(db: Session, base: str) -> str:
    name, suffix = base, 2
    while db.scalar(select(Project).where(Project.name == name)) is not None:
        name = f"{base}-{suffix}"
        suffix += 1
    return name


@router.post("/open", response_model=ProjectOut)
async def open_project(
    body: ProjectOpenRequest, request: Request, db: Session = Depends(get_db)
) -> ProjectOut:
    root = Path(body.root_path).expanduser()
    if not root.is_absolute():
        raise HTTPException(status_code=422, detail="root_path must be an absolute path")
    if not root.is_dir():
        raise HTTPException(status_code=404, detail=f"Directory not found: {root}")
    root = root.resolve()

    existing = db.scalar(select(Project).where(Project.root_path == str(root)))
    if existing is not None:
        return _dto(existing)

    project = Project(name=_unique_name(db, body.name or root.name), root_path=str(root))
    db.add(project)
    db.commit()
    await record_event(
        request.app.state.session_factory,
        "PROJECT_OPENED",
        project_id=project.id,
        payload={"root_path": project.root_path, "name": project.name},
    )
    return _dto(project)


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)) -> list[ProjectOut]:
    return [_dto(p) for p in db.scalars(select(Project).order_by(Project.name)).all()]


@router.get("/{project_id}", response_model=ProjectOut)
def get_project_dto(project: Project = Depends(get_project)) -> ProjectOut:
    return _dto(project)


@router.delete("/{project_id}", status_code=204)
def delete_project(project: Project = Depends(get_project), db: Session = Depends(get_db)) -> None:
    """Unregister a project. Files on disk are never touched."""
    db.delete(project)
    db.commit()

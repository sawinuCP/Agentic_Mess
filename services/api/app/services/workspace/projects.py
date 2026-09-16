"""Project service: open/list/unregister local projects (FR-001)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.models import Project
from app.schemas.workspace.projects import ProjectOut


def project_out(project: Project) -> ProjectOut:
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


def open_project(db: Session, root_path: str, name: str | None) -> ProjectOut:
    root = Path(root_path).expanduser()
    if not root.is_absolute():
        raise DomainError("root_path must be an absolute path", 422)
    if not root.is_dir():
        raise DomainError(f"Directory not found: {root}", 404)
    root = root.resolve()

    existing = db.scalar(select(Project).where(Project.root_path == str(root)))
    if existing is not None:
        return project_out(existing)

    project = Project(name=_unique_name(db, name or root.name), root_path=str(root))
    db.add(project)
    db.commit()
    return project_out(project)


def list_projects(db: Session) -> list[ProjectOut]:
    rows = db.scalars(select(Project).order_by(Project.name)).all()
    return [project_out(p) for p in rows]


def delete_project(db: Session, project: Project) -> None:
    """Unregister a project. Files on disk are never touched."""
    db.delete(project)
    db.commit()

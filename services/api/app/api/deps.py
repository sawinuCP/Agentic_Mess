"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.models import Project
from app.files.service import ProjectFiles


def get_db(request: Request) -> Iterator[Session]:
    """Request-scoped database session."""
    factory = request.app.state.session_factory
    with factory() as session:
        yield session


def get_project(project_id: UUID, db: Session = Depends(get_db)) -> Project:
    """Load a registered project or raise 404."""
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


def get_files_service(project: Project = Depends(get_project)) -> ProjectFiles:
    """Filesystem service bound to the project root, validating it still exists."""
    root = Path(project.root_path)
    if not root.is_dir():
        raise HTTPException(status_code=404, detail=f"Project root is missing on disk: {root}")
    return ProjectFiles(root)

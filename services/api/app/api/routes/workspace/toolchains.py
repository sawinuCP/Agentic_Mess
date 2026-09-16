"""Toolchain endpoints: registry, availability, detection, run (FR-002/003/004/019)."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_files_service, get_project
from app.artifacts.store import ArtifactStore
from app.core.errors import DomainError
from app.db.models import Project
from app.files.service import ProjectFiles
from app.schemas.workspace.toolchains import ProjectToolchainsOut, ToolRunOut, ToolRunRequest
from app.services.core import events as event_service
from app.services.workspace import toolchains as toolchain_service

router = APIRouter(tags=["toolchains"])


def _store(request: Request) -> ArtifactStore:
    store = getattr(request.app.state, "artifacts", None)
    if store is None:
        raise DomainError("Artifact storage unavailable", 503)
    return store


@router.get("/api/toolchains")
async def list_registry() -> list[dict]:
    """The builtin registry itself (LANG-001 metadata)."""
    return toolchain_service.registry_view()


@router.get("/api/toolchains/availability")
async def registry_availability() -> dict[str, dict[str, dict]]:
    return toolchain_service.registry_availability()


@router.get("/api/projects/{project_id}/toolchains", response_model=ProjectToolchainsOut)
async def project_toolchains(
    project_id: uuid.UUID, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> ProjectToolchainsOut:
    return await asyncio.to_thread(
        toolchain_service.project_toolchains, db, Path(project.root_path)
    )


@router.post("/api/projects/{project_id}/toolchains/run", response_model=ToolRunOut)
async def run_tool_endpoint(
    body: ToolRunRequest,
    request: Request,
    project: Project = Depends(get_project),
    files: ProjectFiles = Depends(get_files_service),
    db: Session = Depends(get_db),
) -> ToolRunOut:
    root = Path(project.root_path)
    result = await toolchain_service.run_tool(
        db,
        _store(request),
        root,
        files,
        project.id,
        body.tool,
        body.language,
        body.path,
    )
    await event_service.record_event(
        request.app.state.session_factory,
        "TOOL_RUN_COMPLETED",
        project_id=project.id,
        payload={
            "language": result.language,
            "tool": result.tool,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "path": body.path,
            "artifact_ids": result.artifact_ids,
        },
    )
    return result

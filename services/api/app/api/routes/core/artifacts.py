"""Artifact endpoints: upload/download raw outputs, evidence and files (FR-024)."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.artifacts.store import ArtifactStore
from app.core.errors import DomainError
from app.db.models import Project
from app.schemas.core.artifacts import ArtifactOut
from app.services.core import artifacts as artifact_service

router = APIRouter(tags=["artifacts"])


def _store(request: Request) -> ArtifactStore:
    store = getattr(request.app.state, "artifacts", None)
    if store is None:
        raise DomainError("Artifact storage unavailable", 503)
    return store


@router.post("/api/projects/{project_id}/artifacts", response_model=ArtifactOut, status_code=201)
async def upload_artifact(
    request: Request,
    file: UploadFile,
    project: Project = Depends(get_project),
    db: Session = Depends(get_db),
) -> ArtifactOut:
    """Store a file as a content-addressed artifact (raw bytes on disk, metadata in PG)."""
    data = await file.read()
    return await asyncio.to_thread(
        artifact_service.store_artifact,
        db,
        _store(request),
        project.id,
        file.filename or "",
        "file",
        file.content_type or "",
        data,
    )


@router.get("/api/artifacts/{artifact_id}", response_model=ArtifactOut)
async def get_artifact(artifact_id: uuid.UUID, db: Session = Depends(get_db)) -> ArtifactOut:
    return await asyncio.to_thread(artifact_service.get_artifact, db, artifact_id)


@router.get("/api/artifacts/{artifact_id}/content")
async def get_artifact_content(
    artifact_id: uuid.UUID, request: Request, db: Session = Depends(get_db)
) -> Response:
    artifact, content = await asyncio.to_thread(
        artifact_service.read_content, db, _store(request), artifact_id
    )
    return Response(content=content, media_type=artifact.mime)

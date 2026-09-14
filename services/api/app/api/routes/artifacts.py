"""Artifact endpoints: upload/download raw outputs, evidence and files (FR-024)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.artifacts.store import ArtifactStore, mime_for_name
from app.core.errors import DomainError
from app.db.models import Artifact, Project

router = APIRouter(tags=["artifacts"])


class ArtifactOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    name: str
    kind: str
    mime: str
    size: int
    sha256: str


def _artifact_or_404(artifact_id: uuid.UUID, db: Session) -> Artifact:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise DomainError("Artifact not found", 404)
    return artifact


def _out(artifact: Artifact) -> ArtifactOut:
    return ArtifactOut(
        id=artifact.id,
        project_id=artifact.project_id,
        name=artifact.name,
        kind=artifact.kind,
        mime=artifact.mime,
        size=artifact.size,
        sha256=artifact.sha256,
    )


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
    if not data:
        raise DomainError("Empty artifact upload", 422)
    blob = _store(request).put(data)
    artifact = Artifact(
        project_id=project.id,
        name=file.filename or f"artifact-{blob.sha256[:8]}",
        kind="file",
        mime=file.content_type or mime_for_name(file.filename or ""),
        size=blob.size,
        sha256=blob.sha256,
        storage_path=blob.storage_path,
    )
    db.add(artifact)
    db.commit()
    return _out(artifact)


@router.get("/api/artifacts/{artifact_id}", response_model=ArtifactOut)
def get_artifact(artifact_id: uuid.UUID, db: Session = Depends(get_db)) -> ArtifactOut:
    return _out(_artifact_or_404(artifact_id, db))


@router.get("/api/artifacts/{artifact_id}/content")
def get_artifact_content(
    artifact_id: uuid.UUID, request: Request, db: Session = Depends(get_db)
) -> Response:
    artifact = _artifact_or_404(artifact_id, db)
    content = _store(request).open(artifact.storage_path)
    return Response(content=content, media_type=artifact.mime)

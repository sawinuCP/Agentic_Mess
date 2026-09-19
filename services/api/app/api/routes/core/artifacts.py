"""Artifact endpoints: upload/download raw outputs, evidence and files (FR-024)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.artifacts.store import ArtifactStore
from app.core.errors import DomainError
from app.db.models import Artifact, Project
from app.schemas.core.artifacts import ArtifactOut
from app.services.core import artifacts as artifact_service

router = APIRouter(tags=["artifacts"])

_CHUNK_BYTES = 65_536


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
) -> StreamingResponse:
    """Stream blob bytes with single-range support (§31 log viewer).

    Full body streams in constant-memory chunks; ``Range: bytes=start-end``
    returns 206 with ``Content-Range`` (unsatisfiable ranges → 416).
    ``Accept-Ranges: bytes`` is always advertised.
    """
    store = _store(request)
    artifact, size = await asyncio.to_thread(
        artifact_service.describe_content, db, store, artifact_id
    )
    requested = request.headers.get("range")
    if requested is None:
        return StreamingResponse(
            _stream_content(store, artifact, 0, size),
            media_type=artifact.mime,
            headers={"Accept-Ranges": "bytes", "Content-Length": str(size)},
        )
    start, end_exclusive = _parse_range(requested, size)
    return StreamingResponse(
        _stream_content(store, artifact, start, end_exclusive),
        status_code=206,
        media_type=artifact.mime,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(end_exclusive - start),
            "Content-Range": f"bytes {start}-{end_exclusive - 1}/{size}",
        },
    )


def _parse_range(header: str, size: int) -> tuple[int, int]:
    """Single ``bytes=start-end`` (or suffix/open forms) → (start, end_exclusive)."""
    if size == 0:
        raise DomainError("Range unsatisfiable: empty blob", 416)
    value = header.strip()
    if not value.startswith("bytes=") or "," in value:
        raise DomainError("Only single bytes= ranges are supported", 416)
    spec = value[len("bytes=") :].strip()
    if spec.startswith("-"):  # suffix: last N bytes
        if not spec[1:].isdigit() or int(spec[1:]) <= 0:
            raise DomainError("Range unsatisfiable", 416)
        start = max(0, size - int(spec[1:]))
        return start, size
    first, sep, last = spec.partition("-")
    if not sep or not first.isdigit() or (last and not last.isdigit()):
        raise DomainError("Malformed Range header", 416)
    start = int(first)
    if start >= size:
        raise DomainError("Range start beyond blob end", 416)
    end_exclusive = size if not last else min(int(last) + 1, size)
    if end_exclusive <= start:
        raise DomainError("Range unsatisfiable", 416)
    return start, end_exclusive


async def _stream_content(
    store: ArtifactStore, artifact: Artifact, start: int, end_exclusive: int
) -> AsyncIterator[bytes]:
    """Constant-memory chunked read (disk I/O off the event loop)."""
    cursor = start
    while cursor < end_exclusive:
        chunk = await asyncio.to_thread(
            artifact_service.read_content_range,
            store,
            artifact,
            cursor,
            min(_CHUNK_BYTES, end_exclusive - cursor),
        )
        if not chunk:
            break
        cursor += len(chunk)
        yield chunk

"""Project export/import endpoints (Phase 10 hardening): durable-state portability."""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services.workspace import portability

router = APIRouter(tags=["portability"])


class ImportIn(BaseModel):
    bundle: dict = Field(...)
    root_path: str
    name: str | None = None


@router.get("/api/projects/{project_id}/export")
async def export_project(
    project_id: uuid.UUID, request: Request, db: Session = Depends(get_db)
) -> Response:
    """Download the project's durable state as a JSON bundle (hardening: portability)."""
    bundle = await asyncio.to_thread(
        portability.export_bundle, db, project_id, request.app.state.artifacts
    )
    payload = json.dumps(bundle, indent=2, default=str).encode("utf-8")
    return Response(
        content=payload,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="harness-project-{project_id}.json"'
        },
    )


@router.post("/api/projects/import")
async def import_project(body: ImportIn, request: Request) -> dict:
    """Import a bundle as a new project rooted at ``root_path``."""

    def _run() -> dict:
        with request.app.state.session_factory() as session:
            return portability.import_bundle(
                session,
                request.app.state.artifacts,
                body.bundle,
                new_root=body.root_path,
                new_name=body.name,
            )

    return await asyncio.to_thread(_run)

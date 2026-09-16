"""Browser debugging endpoints (Phase 7, FR-020, spec §20).

Sessions are managed in-memory (TerminalManager pattern); every durable piece of
evidence (screenshots, console/network logs) is stored as an artifact with a
BROWSER_* audit event.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.api.deps import get_project
from app.core.errors import DomainError
from app.db.models import Project
from app.services.core.events import record_event

router = APIRouter(tags=["browser"])


class OpenIn(BaseModel):
    url: str | None = None


class NavigateIn(BaseModel):
    url: str


class ScreenshotIn(BaseModel):
    full_page: bool = False


def _manager(request: Request) -> Any:
    if not request.app.state.settings.browser_enabled:
        raise DomainError("Browser debugging is disabled (HARNESS_BROWSER_ENABLED=false)", 503)
    return request.app.state.browsers


def _session(manager: Any, project_id: uuid.UUID, session_id: str) -> Any:
    session = manager.get(session_id)
    if session.project_id != project_id:
        raise DomainError("Browser session not found", 404)
    return session


def _evidence_persister(request: Request, project_id: uuid.UUID) -> Any:
    """Persist browser evidence (screenshots/logs) as durable artifacts."""
    store = request.app.state.artifacts
    factory = request.app.state.session_factory

    def _persist(name: str, mime: str, data: bytes) -> str:
        from app.db.models import Artifact  # noqa: PLC0415

        blob = store.put(data)
        with factory() as session:
            artifact = Artifact(
                project_id=project_id,
                name=name,
                kind="browser_evidence",
                mime=mime,
                size=blob.size,
                sha256=blob.sha256,
                storage_path=blob.storage_path,
            )
            session.add(artifact)
            session.commit()
            return str(artifact.id)

    return _persist


@router.post("/api/projects/{project_id}/browser/sessions", status_code=201)
async def open_session(
    request: Request,
    project_id: uuid.UUID,
    body: OpenIn | None = None,
    project: Project = Depends(get_project),
) -> dict[str, Any]:
    manager = _manager(request)
    session = await manager.open_session(project.id, body.url if body else None)
    return {
        "session_id": session.session_id,
        "title": await session.title() if (body and body.url) else None,
    }


@router.post("/api/projects/{project_id}/browser/sessions/{session_id}/navigate")
async def navigate(
    request: Request, project_id: uuid.UUID, session_id: str, body: NavigateIn
) -> dict[str, Any]:
    session = _session(_manager(request), project_id, session_id)
    return await session.navigate(body.url)


@router.post("/api/projects/{project_id}/browser/sessions/{session_id}/screenshot")
async def screenshot(
    request: Request, project_id: uuid.UUID, session_id: str, body: ScreenshotIn
) -> dict[str, Any]:
    session = _session(_manager(request), project_id, session_id)
    png = await session.screenshot(full_page=body.full_page)
    persist = _evidence_persister(request, project_id)
    artifact_id = await asyncio.to_thread(
        persist, f"browser-{session_id[:8]}.png", "image/png", png
    )
    await record_event(
        request.app.state.session_factory,
        "BROWSER_SCREENSHOT",
        project_id=project_id,
        payload={"session_id": session_id, "artifact_id": artifact_id},
    )
    return {"artifact_id": artifact_id, "bytes": len(png)}


@router.get("/api/projects/{project_id}/browser/sessions/{session_id}/console")
async def console_logs(
    request: Request, project_id: uuid.UUID, session_id: str
) -> list[dict[str, Any]]:
    session = _session(_manager(request), project_id, session_id)
    return session.console_snapshot()


@router.get("/api/projects/{project_id}/browser/sessions/{session_id}/network")
async def network_log(
    request: Request, project_id: uuid.UUID, session_id: str
) -> list[dict[str, Any]]:
    session = _session(_manager(request), project_id, session_id)
    return session.network_snapshot()


@router.delete("/api/projects/{project_id}/browser/sessions/{session_id}", status_code=204)
async def close_session(request: Request, project_id: uuid.UUID, session_id: str) -> None:
    _session(_manager(request), project_id, session_id)
    await request.app.state.browsers.close_session(session_id)

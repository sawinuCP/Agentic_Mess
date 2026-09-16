"""Web research endpoints (Phase 7, FR-022, spec §22)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.api.deps import get_project
from app.core.errors import DomainError
from app.db.models import Project
from app.research import service as research_service

router = APIRouter(tags=["research"])


class SearchIn(BaseModel):
    query: str = Field(min_length=1)
    max_results: int = Field(5, ge=1, le=20)


class FetchIn(BaseModel):
    url: str
    note: str | None = None


def _research_settings(request: Request) -> tuple[float, int, bool]:
    settings = request.app.state.settings
    if not settings.research_enabled:
        raise DomainError("Web research is disabled (HARNESS_RESEARCH_ENABLED=false)", 503)
    return (
        settings.research_timeout_seconds,
        settings.research_max_bytes,
        settings.research_private_hosts_allowed,
    )


@router.post("/api/projects/{project_id}/research/search")
async def search(
    request: Request, project_id: uuid.UUID, body: SearchIn, project: Project = Depends(get_project)
) -> dict[str, Any]:
    timeout, _max_bytes, _private = _research_settings(request)
    results = await research_service.search_web(
        body.query, max_results=body.max_results, timeout=timeout
    )
    return {"query": body.query, "results": results}


@router.post("/api/projects/{project_id}/research/fetch")
async def fetch(
    request: Request, project_id: uuid.UUID, body: FetchIn, project: Project = Depends(get_project)
) -> dict[str, Any]:
    timeout, max_bytes, private = _research_settings(request)
    with request.app.state.session_factory() as session:
        packet = await research_service.fetch_and_record(
            session,
            request.app.state.artifacts,
            project_id,
            body.url,
            timeout=timeout,
            max_bytes=max_bytes,
            private_hosts_allowed=private,
        )
    return {
        "url": packet.url,
        "final_url": packet.final_url,
        "title": packet.title,
        "fetched_at": packet.fetched_at,
        "sha256": packet.sha256,
        "excerpt": packet.excerpt,
        "artifact_id": packet.artifact_id,
        "context_item_id": packet.context_item_id,
        "confidence": packet.confidence,
    }

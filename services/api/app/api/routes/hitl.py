"""HITL endpoints: pending approvals and decisions (FR-014, SEC-004)."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.hitl import DecideIn
from app.services import hitl as hitl_service

router = APIRouter(tags=["hitl"])


@router.get("/api/hitl")
async def list_hitl(
    project_id: uuid.UUID | None = None,
    status: str | None = Query(None),
    db: Session = Depends(get_db),
) -> list[dict]:
    return [
        hitl_service.request_out(r)
        for r in await asyncio.to_thread(hitl_service.list_requests, db, project_id, status)
    ]


@router.get("/api/hitl/{request_id}")
async def get_hitl(request_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    request = await asyncio.to_thread(hitl_service.get_request, db, request_id)
    return hitl_service.request_out(request)


@router.post("/api/projects/{project_id}/hitl/{request_id}/decide")
async def decide_hitl(
    project_id: uuid.UUID,
    request_id: uuid.UUID,
    body: DecideIn,
    db: Session = Depends(get_db),
) -> dict:
    _ = project_id  # scoping only; the request id is globally unique
    request = await asyncio.to_thread(
        hitl_service.decide_request, db, request_id, body.decision, body.decided_by, body.note
    )
    return hitl_service.request_out(request)

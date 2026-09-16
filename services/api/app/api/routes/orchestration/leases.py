"""Resource-lease endpoints (spec §18): TTL leases with heartbeat renewal."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.orchestration.leases import LeaseBatchIn, LeaseIn, LeaseOut, LeaseRenewIn
from app.services.orchestration import leases as lease_service

router = APIRouter(tags=["leases"])


@router.post("/api/projects/{project_id}/leases", response_model=LeaseOut, status_code=201)
async def acquire_lease(
    project_id: uuid.UUID, body: LeaseIn, db: Session = Depends(get_db)
) -> LeaseOut:
    return await asyncio.to_thread(lease_service.acquire, db, project_id, body)


@router.post(
    "/api/projects/{project_id}/leases/batch", response_model=list[LeaseOut], status_code=201
)
async def acquire_lease_batch(
    project_id: uuid.UUID, body: LeaseBatchIn, db: Session = Depends(get_db)
) -> list[LeaseOut]:
    """All-or-nothing multi-lease acquisition in deterministic key order (spec §18)."""
    return await asyncio.to_thread(lease_service.acquire_many, db, project_id, body.leases)


@router.get("/api/projects/{project_id}/leases", response_model=list[LeaseOut])
async def list_leases(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    status: str | None = Query(None, pattern="^(active|expired|released)$"),
    limit: int = Query(100, ge=1, le=500),
) -> list[LeaseOut]:
    return await asyncio.to_thread(lease_service.list_leases, db, project_id, status, limit)


@router.post("/api/leases/expire-stale", response_model=dict[str, int])
async def expire_stale_leases(db: Session = Depends(get_db)) -> dict[str, int]:
    """Supervision pass: expire every past-TTL lease (spec §18: leases expire on failure)."""
    return await asyncio.to_thread(lease_service.expire_stale, db)


@router.post("/api/leases/{lease_id}/renew", response_model=LeaseOut)
async def renew_lease(
    lease_id: uuid.UUID, body: LeaseRenewIn, db: Session = Depends(get_db)
) -> LeaseOut:
    return await asyncio.to_thread(lease_service.renew, db, lease_id, body)


@router.post("/api/leases/{lease_id}/release", response_model=LeaseOut)
async def release_lease(
    lease_id: uuid.UUID,
    db: Session = Depends(get_db),
    holder_agent_id: uuid.UUID | None = Query(None),
) -> LeaseOut:
    return await asyncio.to_thread(lease_service.release, db, lease_id, holder_agent_id)

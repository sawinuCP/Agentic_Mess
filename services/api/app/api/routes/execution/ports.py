"""Port allocator endpoints (spec §19.1): request, renew, release, expire."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.db.models import Project
from app.schemas.execution.execution import PortAllocateIn, PortOut, PortRenewIn
from app.services.execution import ports as port_service

router = APIRouter(tags=["ports"])


def _range(request: Request) -> tuple[int, int]:
    settings = request.app.state.settings
    return settings.port_range_low, settings.port_range_high


@router.post("/api/projects/{project_id}/ports", response_model=PortOut, status_code=201)
async def allocate_port(
    request: Request,
    body: PortAllocateIn,
    project: Project = Depends(get_project),
    db: Session = Depends(get_db),
) -> PortOut:
    """Reserve a free, bindable port for this project (spec §19.1)."""
    low, high = _range(request)
    allocation = await asyncio.to_thread(
        port_service.allocate,
        db,
        project.id,
        purpose=body.purpose,
        holder=body.holder,
        ttl_seconds=body.ttl_seconds,
        port_low=low,
        port_high=high,
        preferred_port=body.preferred_port,
    )
    return PortOut(**allocation)


@router.get("/api/projects/{project_id}/ports", response_model=list[PortOut])
async def list_ports(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    status: str | None = Query(None, pattern="^(active|expired|released)$"),
    limit: int = Query(100, ge=1, le=500),
) -> list[PortOut]:
    rows = await asyncio.to_thread(port_service.list_allocations, db, project_id, status, limit)
    return [PortOut(**row) for row in rows]


@router.post("/api/ports/expire-stale", response_model=dict[str, int])
async def expire_stale_ports(db: Session = Depends(get_db)) -> dict[str, int]:
    return await asyncio.to_thread(port_service.expire_stale, db)


@router.post("/api/ports/{allocation_id}/renew", response_model=PortOut)
async def renew_port(
    allocation_id: uuid.UUID, body: PortRenewIn, db: Session = Depends(get_db)
) -> PortOut:
    return PortOut(
        **(await asyncio.to_thread(port_service.renew, db, allocation_id, body.ttl_seconds))
    )


@router.post("/api/ports/{allocation_id}/release", response_model=PortOut)
async def release_port(
    allocation_id: uuid.UUID,
    db: Session = Depends(get_db),
    holder: str | None = Query(None),
) -> PortOut:
    return PortOut(**(await asyncio.to_thread(port_service.release, db, allocation_id, holder)))

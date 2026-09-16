"""Runtime-manager status endpoints (Phase 6, FR-018/SEC-005).

Execution itself always funnels through the tool gateway; this router exposes
the configured runtime posture so the UI and operators can see what will run
where (backend, isolation limits, quotas).
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.runtime.runtimes import BACKENDS
from app.schemas.execution import RuntimeStatusOut

router = APIRouter(tags=["runtime"])


@router.get("/api/runtime/status", response_model=RuntimeStatusOut)
async def runtime_status(request: Request) -> RuntimeStatusOut:
    settings = request.app.state.settings
    return RuntimeStatusOut(
        backends=list(BACKENDS),
        active_backend=settings.runtime_backend,
        docker_image=settings.docker_image,
        docker_network=settings.docker_network,
        docker_memory=settings.docker_memory,
        docker_cpus=settings.docker_cpus,
        exec_timeout_cap_seconds=settings.exec_timeout_cap_seconds,
        exec_max_concurrent_per_project=settings.exec_max_concurrent_per_project,
        port_range={
            "low": settings.port_range_low,
            "high": settings.port_range_high,
            "ttl_seconds": settings.port_ttl_seconds,
        },
    )

"""Health endpoints: liveness + fail-closed readiness (spec §43)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import nats
import redis.asyncio as aioredis
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.core.config import Settings
from app.schemas.core.health import ComponentHealth, LivenessReport, ReadinessReport

router = APIRouter(tags=["health"])

STATUS_OK = "ok"
STATUS_DOWN = "down"
STATUS_DISABLED = "disabled"


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/healthz", response_model=LivenessReport)
def liveness(request: Request) -> LivenessReport:
    settings = _settings(request)
    return LivenessReport(status=STATUS_OK, version=__version__, environment=settings.environment)


def _build_report(
    settings: Settings, checks: dict[str, ComponentHealth]
) -> tuple[bool, ReadinessReport]:
    required = {"postgres"}
    if settings.require_redis:
        required.add("redis")
    if settings.require_nats:
        required.add("nats")
    if settings.temporal_enabled:
        required.add("temporal")
    ready = all(checks[name].status == STATUS_OK for name in required)
    report = ReadinessReport(
        ready=ready, version=__version__, environment=settings.environment, checks=checks
    )
    return ready, report


@router.get(
    "/readyz",
    response_model=ReadinessReport,
    responses={
        503: {"model": ReadinessReport, "description": "One or more required components down"}
    },
)
async def readiness(request: Request) -> JSONResponse:
    """Report per-component health. Fails closed: HTTP 503 unless everything required is ok."""
    settings = _settings(request)
    checks = {
        "postgres": await _check_postgres(request),
        "redis": await _check_redis(settings),
        "nats": await _check_nats(settings),
        "temporal": await _check_temporal(settings),
        "artifacts": await _check_artifacts(request),
    }
    ready, report = _build_report(settings, checks)
    return JSONResponse(status_code=200 if ready else 503, content=report.model_dump(mode="json"))


async def _check_postgres(request: Request) -> ComponentHealth:
    """Probe the durable store. The sync engine call runs in a worker thread."""
    settings = _settings(request)
    factory = request.app.state.session_factory

    def _probe() -> None:
        with factory() as session:
            session.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(
            asyncio.to_thread(_probe), timeout=settings.readiness_timeout_seconds
        )
    except Exception as exc:
        return ComponentHealth(status=STATUS_DOWN, detail=f"{type(exc).__name__}: {exc}")
    return ComponentHealth(status=STATUS_OK)


async def _check_redis(settings: Settings) -> ComponentHealth:
    client = aioredis.from_url(
        settings.redis_url, socket_connect_timeout=settings.readiness_timeout_seconds
    )
    try:
        await asyncio.wait_for(client.ping(), timeout=settings.readiness_timeout_seconds)
    except Exception as exc:
        return ComponentHealth(status=STATUS_DOWN, detail=f"{type(exc).__name__}: {exc}")
    finally:
        await client.aclose()
    return ComponentHealth(status=STATUS_OK)


async def _check_nats(settings: Settings) -> ComponentHealth:
    try:
        connection = await asyncio.wait_for(
            nats.connect(
                servers=[settings.nats_url],
                connect_timeout=max(1, int(settings.readiness_timeout_seconds)),
                allow_reconnect=False,
            ),
            timeout=settings.readiness_timeout_seconds + 1.0,
        )
    except Exception as exc:
        return ComponentHealth(status=STATUS_DOWN, detail=f"{type(exc).__name__}: {exc}")
    await connection.drain()
    return ComponentHealth(status=STATUS_OK)


async def _check_temporal(settings: Settings) -> ComponentHealth:
    """Durable engine reachability — opt-in, so a disabled integration reports
    ``disabled`` (informational), never ``down``. A TCP open on the frontend
    port proves the server accepts work; workflow health is Temporal's own UI."""
    if not settings.temporal_enabled:
        return ComponentHealth(status=STATUS_DISABLED, detail="temporal integration off")
    host, _, port = settings.temporal_address.rpartition(":")
    host = host or "localhost"

    def _probe() -> None:
        import socket  # noqa: PLC0415 — trivial local import

        with socket.create_connection(
            (host, int(port or 7233)),
            timeout=max(1, int(settings.readiness_timeout_seconds)),
        ):
            return None

    try:
        await asyncio.to_thread(_probe)
    except Exception as exc:
        return ComponentHealth(status=STATUS_DOWN, detail=f"{type(exc).__name__}: {exc}")
    return ComponentHealth(status=STATUS_OK)


async def _check_artifacts(request: Request) -> ComponentHealth:
    """Artifact storage root exists and is writable (evidence depends on it)."""
    store = getattr(request.app.state, "artifacts", None)
    if store is None:
        return ComponentHealth(status=STATUS_DOWN, detail="artifact store not initialised")

    def _probe() -> str | None:
        root = Path(store.root)
        if not root.is_dir() or not os.access(root, os.W_OK):
            return f"not writable: {root}"
        return None

    problem = await asyncio.to_thread(_probe)
    if problem is not None:
        return ComponentHealth(status=STATUS_DOWN, detail=problem)
    return ComponentHealth(status=STATUS_OK)

"""Health endpoints: liveness + fail-closed readiness (spec §43)."""

from __future__ import annotations

import asyncio

import nats
import redis.asyncio as aioredis
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.core.config import Settings
from app.schemas.health import ComponentHealth, LivenessReport, ReadinessReport

router = APIRouter(tags=["health"])

STATUS_OK = "ok"
STATUS_DOWN = "down"


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

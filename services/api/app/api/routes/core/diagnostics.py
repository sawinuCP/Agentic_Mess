"""Diagnostics endpoint (Phase 10): one fail-soft support bundle for operators.

Unlike ``/readyz`` (fail-closed gating), diagnostics never fails: every probe
returns ok/down plus detail so a partially broken deployment can still be
diagnosed from the UI or a single curl.
"""

from __future__ import annotations

import asyncio
import os
import platform
import sys
import tempfile
import time
from typing import Any

import nats
import redis.asyncio as aioredis
from fastapi import APIRouter, Request
from sqlalchemy import text

from app import __version__
from app.core.config import Settings

router = APIRouter(tags=["diagnostics"])

_STARTED_AT = time.time()
STATUS_OK = "ok"
STATUS_DOWN = "down"


async def _probe(timeout: float, fn: Any) -> tuple[str, Any]:
    """Run a sync probe; returns (status, detail) — dict details pass through."""
    try:
        return STATUS_OK, fn()
    except Exception as exc:  # noqa: BLE001 — diagnostics never fails
        return STATUS_DOWN, f"{type(exc).__name__}: {exc}"


async def _aprobe(timeout: float, afunc: Any) -> tuple[str, str]:
    """Run an async probe; returns (status, detail)."""
    try:
        return STATUS_OK, str(await asyncio.wait_for(afunc(), timeout=timeout))
    except Exception as exc:  # noqa: BLE001 — diagnostics never fails
        return STATUS_DOWN, f"{type(exc).__name__}: {exc}"


def _db_probe(factory: Any) -> Any:
    """SELECT 1 as the liveness probe; alembic head is best-effort (tests use metadata)."""

    def _run() -> str:
        with factory() as session:
            session.execute(text("SELECT 1"))
            try:
                return str(
                    session.execute(text("SELECT version_num FROM alembic_version")).scalar()
                )
            except Exception:  # noqa: BLE001 — schema created without alembic_version
                return "connected (schema without alembic_version table)"

    return _run


def _counts_probe(factory: Any) -> Any:
    def _run() -> dict[str, int]:
        with factory() as session:
            counts: dict[str, int] = {}
            for table in ("projects", "requirements", "tasks", "agents", "artifacts", "events"):
                counts[table] = int(
                    session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
                )
            return counts

    return _run


def _artifact_store_probe(store: Any) -> Any:
    def _run() -> str:
        probe = store.put(b"harness-diagnostics-probe")
        return f"writable (probe sha {probe.sha256[:12]})"

    return _run


def _temp_dir_probe() -> Any:
    def _run() -> str:
        with tempfile.NamedTemporaryFile(prefix="harness-diag-", delete=True) as handle:
            return f"temp writable ({handle.name})"

    return _run


@router.get("/api/diagnostics")
async def diagnostics(request: Request) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    factory = request.app.state.session_factory
    timeout = settings.readiness_timeout_seconds

    db_status, db_detail = await _probe(timeout, _db_probe(factory))
    counts_status, counts = await _probe(timeout, _counts_probe(factory))
    store_status, store_detail = await _probe(
        timeout, _artifact_store_probe(request.app.state.artifacts)
    )
    temp_status, temp_detail = await _probe(timeout, _temp_dir_probe())
    redis_status, redis_detail = await _aprobe(timeout, _redis_probe(settings))
    nats_status, nats_detail = await _aprobe(timeout, _nats_probe(settings))

    return {
        "app": {
            "version": __version__,
            "environment": settings.environment,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "pid": os.getpid(),
            "uptime_seconds": round(time.time() - _STARTED_AT, 1),
        },
        "database": {"status": db_status, "alembic_head": str(db_detail)},
        "counts": counts if counts_status == STATUS_OK else {"error": counts},
        "artifact_store": {"status": store_status, "detail": str(store_detail)},
        "temp_dir": {"status": temp_status, "detail": str(temp_detail)},
        "redis": {"status": redis_status, "detail": redis_detail},
        "nats": {"status": nats_status, "detail": nats_detail},
        "config": {
            "temporal_enabled": settings.temporal_enabled,
            "runtime_backend": settings.runtime_backend,
            "scheduler_enabled": settings.scheduler_enabled,
            "browser_enabled": settings.browser_enabled,
            "mcp_enabled": settings.mcp_enabled,
            "research_enabled": settings.research_enabled,
            "nats_delivery_enabled": settings.nats_delivery_enabled,
        },
    }


def _redis_probe(settings: Settings) -> Any:
    async def _run() -> str:
        client = aioredis.from_url(
            settings.redis_url, socket_connect_timeout=settings.readiness_timeout_seconds
        )
        try:
            await client.ping()
            return settings.redis_url
        finally:
            await client.aclose()

    return _run


def _nats_probe(settings: Settings) -> Any:
    async def _run() -> str:
        connection = await nats.connect(
            servers=[settings.nats_url],
            connect_timeout=max(1, int(settings.readiness_timeout_seconds)),
            allow_reconnect=False,
        )
        await connection.drain()
        return settings.nats_url

    return _run

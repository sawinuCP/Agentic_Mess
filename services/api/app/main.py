"""FastAPI application factory for the AI Harness control plane."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.middleware import MetricsMiddleware, RateLimitMiddleware, RequestIDMiddleware
from app.api.routes import (
    browser as browser_routes,
)
from app.api.routes import (
    core as core_routes,
)
from app.api.routes import (
    execution as execution_routes,
)
from app.api.routes import (
    intelligence as intelligence_routes,
)
from app.api.routes import (
    mcp as mcp_routes,
)
from app.api.routes import (
    orchestration as orchestration_routes,
)
from app.api.routes import (
    planning as planning_routes,
)
from app.api.routes import (
    quality as quality_routes,
)
from app.api.routes import (
    research as research_routes,
)
from app.api.routes import (
    workspace as workspace_routes,
)
from app.api.security import AuthMiddleware
from app.artifacts.store import ArtifactStore
from app.browser.manager import BrowserManager
from app.core.config import Settings, get_settings
from app.core.errors import DomainError
from app.core.logging import configure_logging
from app.core.metrics import MetricsRegistry
from app.core.observability import setup_tracing
from app.db.base import build_engine, build_session_factory
from app.realtime import bridge as realtime_bridge
from app.realtime import route as realtime_routes
from app.realtime.bus import EventBus
from app.realtime.gateway import RealtimeGateway
from app.realtime.retention import retention_worker
from app.runtime.env_sandbox import configure_agent_env, parse_name_list
from app.terminal.manager import TerminalManager


def _domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map domain errors carrying status_code/message onto HTTP responses."""
    if isinstance(exc, DomainError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})
    return JSONResponse(status_code=500, content={"detail": "internal error"})


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API app. Tests pass explicit Settings; production uses get_settings()."""
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    configure_agent_env(parse_name_list(settings.agent_env_allow))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Fail-closed security posture (Wave 1): a networked bind without an API
        # token is a misconfiguration, not a warning.
        host = settings.host.strip()
        loopback = host in ("127.0.0.1", "::1", "localhost")
        if not loopback and not settings.api_token:
            raise RuntimeError(
                "Refusing to start: HARNESS_HOST is non-loopback "
                f"({host}) but HARNESS_API_TOKEN is empty. Set a token or bind to 127.0.0.1."
            )
        engine = build_engine(
            settings.database_url, connect_timeout_seconds=settings.readiness_timeout_seconds
        )
        app.state.engine = engine
        app.state.session_factory = build_session_factory(engine)
        app.state.terminals = TerminalManager()
        app.state.artifacts = ArtifactStore(Path(settings.artifacts_dir))
        app.state.browsers = BrowserManager(max_sessions=settings.browser_max_sessions)
        # Wave 3 realtime: event bus, gateway, retention worker.
        bus: EventBus | None = None
        if settings.nats_events_enabled:
            bus = EventBus(settings, app.state.metrics)
            await bus.start()
            realtime_bridge.activate_bus(bus)
        app.state.event_bus = bus
        gateway = RealtimeGateway(settings, app.state.metrics, bus_present=bus is not None)
        await gateway.start()
        app.state.realtime = gateway
        retention_task = asyncio.create_task(retention_worker(settings, app.state.session_factory))
        try:
            yield
        finally:
            retention_task.cancel()
            await gateway.close()
            realtime_bridge.deactivate_bus()
            if bus is not None:
                await bus.close()
            app.state.terminals.close_all()
            await app.state.browsers.close_all()
            engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
        description=(
            "Local-first AI agent control plane. Conventions: bearer auth "
            "(loopback is unauthenticated local-only; non-loopback requires "
            "HARNESS_API_TOKEN), `X-Request-ID` correlation on every response, "
            "per-IP rate limiting with `Retry-After` on 429, `idempotency_key` "
            "on port/worktree creates (replays return the live row), and "
            "`limit`/`offset` pagination on task lists."
        ),
    )
    app.state.settings = settings
    # Metrics registry exists for the whole app lifetime (middleware registers
    # instruments at build time); bus/gateway live in the lifespan.
    app.state.metrics = MetricsRegistry()
    realtime_bridge.install_listeners()
    for router in (
        *core_routes.routers,
        *workspace_routes.routers,
        *planning_routes.routers,
        *orchestration_routes.routers,
        *intelligence_routes.routers,
        *execution_routes.routers,
        *browser_routes.routers,
        *mcp_routes.routers,
        *research_routes.routers,
        *quality_routes.routers,
        realtime_routes.router,
    ):
        app.include_router(router)
    # Wave 3: instrument HTTP latency/duration into the metrics registry.
    app.add_middleware(MetricsMiddleware, registry=app.state.metrics)
    app.add_middleware(AuthMiddleware, token=settings.api_token)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()
        ],
        allow_credentials=False,  # bearer tokens, not cookies
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    # W1-RATE-1: per-IP rate limit runs inside RequestID (so 429s are correlated)
    # but outside auth — rejected requests never reach handlers.
    app.add_middleware(
        RateLimitMiddleware,
        enabled=settings.rate_limit_enabled,
        requests_per_window=settings.rate_limit_requests_per_window,
        window_seconds=settings.rate_limit_window_seconds,
    )
    app.add_middleware(RequestIDMiddleware)
    # DomainError is the shared base (FileServiceError/ToolchainError/GitError subclass it).
    app.add_exception_handler(DomainError, _domain_error_handler)
    setup_tracing(app, settings)
    return app


app = create_app()

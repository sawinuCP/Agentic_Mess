"""FastAPI application factory for the AI Harness control plane."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import __version__
from app.api.middleware import RequestIDMiddleware
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
from app.artifacts.store import ArtifactStore
from app.browser.manager import BrowserManager
from app.core.config import Settings, get_settings
from app.core.errors import DomainError
from app.core.logging import configure_logging
from app.core.observability import setup_tracing
from app.db.base import build_engine, build_session_factory
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

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = build_engine(
            settings.database_url, connect_timeout_seconds=settings.readiness_timeout_seconds
        )
        app.state.engine = engine
        app.state.session_factory = build_session_factory(engine)
        app.state.terminals = TerminalManager()
        app.state.artifacts = ArtifactStore(Path(settings.artifacts_dir))
        app.state.browsers = BrowserManager(max_sessions=settings.browser_max_sessions)
        yield
        app.state.terminals.close_all()
        await app.state.browsers.close_all()
        engine.dispose()

    app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)
    app.state.settings = settings
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
    ):
        app.include_router(router)
    app.add_middleware(RequestIDMiddleware)
    # DomainError is the shared base (FileServiceError/ToolchainError/GitError subclass it).
    app.add_exception_handler(DomainError, _domain_error_handler)
    setup_tracing(app, settings)
    return app


app = create_app()

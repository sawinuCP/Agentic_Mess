"""FastAPI application factory for the AI Harness control plane."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import __version__
from app.api.middleware import RequestIDMiddleware
from app.api.routes import files, git, health, projects, terminal, toolchains
from app.core.config import Settings, get_settings
from app.core.errors import DomainError
from app.core.logging import configure_logging
from app.core.observability import setup_tracing
from app.db.base import build_engine, build_session_factory
from app.files.service import FileServiceError
from app.gitops.client import GitError
from app.terminal.manager import TerminalManager
from app.toolchains.errors import ToolchainError


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
        yield
        app.state.terminals.close_all()
        engine.dispose()

    app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.include_router(health.router)
    app.include_router(projects.router)
    app.include_router(files.router)
    app.include_router(git.router)
    app.include_router(toolchains.router)
    app.include_router(terminal.router)
    app.add_middleware(RequestIDMiddleware)
    for error_class in (FileServiceError, ToolchainError, GitError):
        app.add_exception_handler(error_class, _domain_error_handler)
    setup_tracing(app, settings)
    return app


app = create_app()

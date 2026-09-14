"""FastAPI application factory for the AI Harness control plane."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.middleware import RequestIDMiddleware
from app.api.routes.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.observability import setup_tracing
from app.db.base import build_engine, build_session_factory


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
        yield
        engine.dispose()

    app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.include_router(health_router)
    app.add_middleware(RequestIDMiddleware)
    setup_tracing(app, settings)
    return app


app = create_app()

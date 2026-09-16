"""Core-plane routes: health/readiness, diagnostics, durable event stream, artifacts."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.core import artifacts, diagnostics, events, health

routers: list[APIRouter] = [
    health.router,
    diagnostics.router,
    events.router,
    artifacts.router,
]

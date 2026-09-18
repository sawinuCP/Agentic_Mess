"""Core-plane routes: health/readiness, diagnostics, durable event stream, artifacts,
metrics, retention."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.core import artifacts, diagnostics, events, health, maintenance, metrics

routers: list[APIRouter] = [
    health.router,
    diagnostics.router,
    events.router,
    artifacts.router,
    metrics.router,
    maintenance.router,
]

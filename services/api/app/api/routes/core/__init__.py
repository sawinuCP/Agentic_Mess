"""Core-plane routes: health/readiness, durable event stream, artifact content."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.core import artifacts, events, health

routers: list[APIRouter] = [health.router, events.router, artifacts.router]

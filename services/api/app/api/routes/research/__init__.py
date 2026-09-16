"""Web research routes (Phase 7, FR-022)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.research import research

routers: list[APIRouter] = [research.router]

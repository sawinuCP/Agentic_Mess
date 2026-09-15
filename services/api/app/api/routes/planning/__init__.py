"""Planning routes: requirements, plans, and the durable task graph."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.planning import plans, requirements, tasks

routers: list[APIRouter] = [requirements.router, plans.router, tasks.router]

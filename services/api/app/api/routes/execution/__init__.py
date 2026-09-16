"""Execution-plane routes (Phase 6): port allocator + runtime status."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.execution import ports, runtimes

routers: list[APIRouter] = [ports.router, runtimes.router]

"""Orchestration routes: agents, messages, HITL, leases, scheduler, worktrees."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.orchestration import (
    agents,
    hitl,
    knowledge,
    leases,
    messages,
    scheduler,
    worktrees,
)

routers: list[APIRouter] = [
    agents.router,
    messages.router,
    knowledge.router,
    hitl.router,
    leases.router,
    scheduler.router,
    worktrees.router,
]

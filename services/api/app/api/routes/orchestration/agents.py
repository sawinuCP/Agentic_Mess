"""Agent and agent-session endpoints (FR-008)."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.db.models import Project
from app.schemas.orchestration.agents import AgentIn, AgentOut, SessionOut
from app.services.orchestration import agents as agent_service

router = APIRouter(tags=["agents"])


@router.post("/api/projects/{project_id}/agents", response_model=AgentOut, status_code=201)
async def create_agent(
    body: AgentIn, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> AgentOut:
    return await asyncio.to_thread(agent_service.create_agent, db, project.id, body)


@router.get("/api/projects/{project_id}/agents", response_model=list[AgentOut])
async def list_agents(
    project: Project = Depends(get_project),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[AgentOut]:
    """One stable page (created_at, id)."""
    return await asyncio.to_thread(agent_service.list_agents, db, project.id, limit, offset)


@router.get("/api/agents/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: uuid.UUID, db: Session = Depends(get_db)) -> AgentOut:
    return await asyncio.to_thread(agent_service.get_agent, db, agent_id)


@router.get("/api/agents/{agent_id}/sessions", response_model=list[SessionOut])
async def list_agent_sessions(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
) -> list[SessionOut]:
    """Session history for one agent, newest first (Wave 7 completion).

    Read-only: sessions are runtime-owned. No UI-driven lifecycle
    transitions are offered here by design — the runtime, never the UI,
    controls transitions (see app/agents_runtime/lifecycle.py).
    """
    return await asyncio.to_thread(agent_service.list_sessions, db, agent_id, limit)


@router.post("/api/agents/sessions/supervise")
async def supervise_sessions(request: Request, db: Session = Depends(get_db)) -> dict[str, int]:
    """Mark running sessions with stale heartbeats as lost (spec §12 supervision)."""
    settings = request.app.state.settings
    stale_seconds = int(getattr(settings, "session_stale_seconds", 300) or 300)
    return await asyncio.to_thread(agent_service.supervise_sessions, db, stale_seconds)


@router.post("/api/agents/{agent_id}/sessions", response_model=SessionOut, status_code=201)
async def start_session(agent_id: uuid.UUID, db: Session = Depends(get_db)) -> SessionOut:
    return await asyncio.to_thread(agent_service.start_session, db, agent_id)


@router.post("/api/sessions/{session_id}/heartbeat", response_model=SessionOut)
async def heartbeat(session_id: uuid.UUID, db: Session = Depends(get_db)) -> SessionOut:
    return await asyncio.to_thread(agent_service.heartbeat, db, session_id)


@router.post("/api/sessions/{session_id}/end", response_model=SessionOut)
async def end_session(session_id: uuid.UUID, db: Session = Depends(get_db)) -> SessionOut:
    return await asyncio.to_thread(agent_service.end_session, db, session_id)

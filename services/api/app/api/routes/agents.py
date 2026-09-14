"""Agent and agent-session endpoints (FR-008)."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.db.models import Project
from app.schemas.agents import AgentIn, AgentOut, SessionOut
from app.services import agents as agent_service

router = APIRouter(tags=["agents"])


@router.post("/api/projects/{project_id}/agents", response_model=AgentOut, status_code=201)
async def create_agent(
    body: AgentIn, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> AgentOut:
    return await asyncio.to_thread(agent_service.create_agent, db, project.id, body)


@router.get("/api/projects/{project_id}/agents", response_model=list[AgentOut])
async def list_agents(
    project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> list[AgentOut]:
    return await asyncio.to_thread(agent_service.list_agents, db, project.id)


@router.get("/api/agents/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: uuid.UUID, db: Session = Depends(get_db)) -> AgentOut:
    return await asyncio.to_thread(agent_service.get_agent, db, agent_id)


@router.post("/api/agents/{agent_id}/sessions", response_model=SessionOut, status_code=201)
async def start_session(agent_id: uuid.UUID, db: Session = Depends(get_db)) -> SessionOut:
    return await asyncio.to_thread(agent_service.start_session, db, agent_id)


@router.post("/api/sessions/{session_id}/heartbeat", response_model=SessionOut)
async def heartbeat(session_id: uuid.UUID, db: Session = Depends(get_db)) -> SessionOut:
    return await asyncio.to_thread(agent_service.heartbeat, db, session_id)


@router.post("/api/sessions/{session_id}/end", response_model=SessionOut)
async def end_session(session_id: uuid.UUID, db: Session = Depends(get_db)) -> SessionOut:
    return await asyncio.to_thread(agent_service.end_session, db, session_id)

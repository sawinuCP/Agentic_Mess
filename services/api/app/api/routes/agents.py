"""Agent and agent-session endpoints (durable registry; runtime is Phase 3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.core.errors import DomainError
from app.db.models import Agent, AgentSession, Project

router = APIRouter(tags=["agents"])


class AgentIn(BaseModel):
    name: str
    role: str
    model: str | None = None
    capabilities: list[str] = []


class AgentOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    name: str
    role: str
    model: str | None
    capabilities: list[str]
    state: str


class SessionOut(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID
    runtime: str
    status: str
    started_at: datetime
    heartbeat_at: datetime | None


def _agent_or_404(agent_id: uuid.UUID, db: Session) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise DomainError("Agent not found", 404)
    return agent


def _agent_out(agent: Agent) -> AgentOut:
    return AgentOut(
        id=agent.id,
        project_id=agent.project_id,
        name=agent.name,
        role=agent.role,
        model=agent.model,
        capabilities=[str(c) for c in (agent.capabilities or [])],
        state=agent.state,
    )


@router.post("/api/projects/{project_id}/agents", response_model=AgentOut, status_code=201)
def create_agent(
    body: AgentIn, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> AgentOut:
    agent = Agent(
        project_id=project.id,
        name=body.name,
        role=body.role,
        model=body.model,
        capabilities=body.capabilities,
    )
    db.add(agent)
    db.commit()
    return _agent_out(agent)


@router.get("/api/projects/{project_id}/agents", response_model=list[AgentOut])
def list_agents(
    project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> list[AgentOut]:
    rows = db.scalars(
        select(Agent).where(Agent.project_id == project.id).order_by(Agent.created_at)
    ).all()
    return [_agent_out(a) for a in rows]


@router.get("/api/agents/{agent_id}", response_model=AgentOut)
def get_agent(agent_id: uuid.UUID, db: Session = Depends(get_db)) -> AgentOut:
    return _agent_out(_agent_or_404(agent_id, db))


@router.post("/api/agents/{agent_id}/sessions", response_model=SessionOut, status_code=201)
def create_session(agent_id: uuid.UUID, db: Session = Depends(get_db)) -> SessionOut:
    agent = _agent_or_404(agent_id, db)
    agent.state = "running"
    session = AgentSession(agent_id=agent.id, heartbeat_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    return SessionOut(
        id=session.id,
        agent_id=session.agent_id,
        runtime=session.runtime,
        status=session.status,
        started_at=session.started_at,
        heartbeat_at=session.heartbeat_at,
    )


@router.post("/api/sessions/{session_id}/heartbeat", response_model=SessionOut)
def heartbeat(session_id: uuid.UUID, db: Session = Depends(get_db)) -> SessionOut:
    session = db.get(AgentSession, session_id)
    if session is None:
        raise DomainError("Session not found", 404)
    session.heartbeat_at = datetime.now(UTC)
    db.commit()
    return SessionOut(
        id=session.id,
        agent_id=session.agent_id,
        runtime=session.runtime,
        status=session.status,
        started_at=session.started_at,
        heartbeat_at=session.heartbeat_at,
    )


@router.post("/api/sessions/{session_id}/end", response_model=SessionOut)
def end_session(session_id: uuid.UUID, db: Session = Depends(get_db)) -> SessionOut:
    session = db.get(AgentSession, session_id)
    if session is None:
        raise DomainError("Session not found", 404)
    session.status = "ended"
    session.finished_at = datetime.now(UTC)
    agent = db.get(Agent, session.agent_id)
    if agent is not None and agent.state == "running":
        agent.state = "waiting"
    db.commit()
    return SessionOut(
        id=session.id,
        agent_id=session.agent_id,
        runtime=session.runtime,
        status=session.status,
        started_at=session.started_at,
        heartbeat_at=session.heartbeat_at,
    )

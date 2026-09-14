"""Agent registry and session service (FR-008; runtime wiring lands in Phase 3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.models import Agent, AgentSession
from app.schemas.agents import AgentIn, AgentOut, SessionOut


def _agent_or_404(agent_id: uuid.UUID, db: Session) -> Agent:
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise DomainError("Agent not found", 404)
    return agent


def agent_out(agent: Agent) -> AgentOut:
    return AgentOut(
        id=agent.id,
        project_id=agent.project_id,
        name=agent.name,
        role=agent.role,
        model=agent.model,
        capabilities=[str(c) for c in (agent.capabilities or [])],
        state=agent.state,
    )


def session_out(session: AgentSession) -> SessionOut:
    return SessionOut(
        id=session.id,
        agent_id=session.agent_id,
        runtime=session.runtime,
        status=session.status,
        started_at=session.started_at,
        heartbeat_at=session.heartbeat_at,
    )


def create_agent(db: Session, project_id: uuid.UUID, body: AgentIn) -> AgentOut:
    agent = Agent(
        project_id=project_id,
        name=body.name,
        role=body.role,
        model=body.model,
        capabilities=body.capabilities,
    )
    db.add(agent)
    db.commit()
    return agent_out(agent)


def list_agents(db: Session, project_id: uuid.UUID) -> list[AgentOut]:
    rows = db.scalars(
        select(Agent).where(Agent.project_id == project_id).order_by(Agent.created_at)
    ).all()
    return [agent_out(a) for a in rows]


def get_agent(db: Session, agent_id: uuid.UUID) -> AgentOut:
    return agent_out(_agent_or_404(agent_id, db))


def start_session(db: Session, agent_id: uuid.UUID) -> SessionOut:
    agent = _agent_or_404(agent_id, db)
    agent.state = "running"
    session = AgentSession(agent_id=agent.id, heartbeat_at=datetime.now(UTC))
    db.add(session)
    db.commit()
    return session_out(session)


def heartbeat(db: Session, session_id: uuid.UUID) -> SessionOut:
    session = db.get(AgentSession, session_id)
    if session is None:
        raise DomainError("Session not found", 404)
    session.heartbeat_at = datetime.now(UTC)
    db.commit()
    return session_out(session)


def end_session(db: Session, session_id: uuid.UUID) -> SessionOut:
    session = db.get(AgentSession, session_id)
    if session is None:
        raise DomainError("Session not found", 404)
    session.status = "ended"
    session.finished_at = datetime.now(UTC)
    agent = db.get(Agent, session.agent_id)
    if agent is not None and agent.state == "running":
        agent.state = "waiting"
    db.commit()
    return session_out(session)

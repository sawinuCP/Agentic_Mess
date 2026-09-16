"""Agent and agent-session entities (spec §11, §12). Agents are disposable."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (Index("ix_agents_project_state", "project_id", "state"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), default=None
    )
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(50))  # supervisor|planner|implementer|reviewer|...
    model: Mapped[str | None] = mapped_column(
        String(200), default=None
    )  # registry key; never hard-coded
    capabilities: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default=func.jsonb_build_array()
    )
    state: Mapped[str] = mapped_column(String(30), default="created")  # spec §12 lifecycle states
    parent_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentSession(Base):
    """Runtime execution session for an agent (heartbeats mandatory while running)."""

    __tablename__ = "agent_sessions"
    __table_args__ = (Index("ix_agent_sessions_agent", "agent_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    runtime: Mapped[str] = mapped_column(
        String(50), default="local"
    )  # local|docker|browser|temporal-worker
    status: Mapped[str] = mapped_column(String(30), default="running")  # running|ended|lost
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

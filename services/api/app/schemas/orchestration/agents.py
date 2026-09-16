"""Agent and session DTOs."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AgentIn(BaseModel):
    name: str
    role: str
    model: str | None = None
    capabilities: list[str] = []


class AgentOut(BaseModel):
    id: UUID
    project_id: UUID | None
    name: str
    role: str
    model: str | None
    capabilities: list[str]
    state: str


class SessionOut(BaseModel):
    id: UUID
    agent_id: UUID
    runtime: str
    status: str
    started_at: datetime
    heartbeat_at: datetime | None

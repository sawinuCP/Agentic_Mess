"""Knowledge DTOs: typed memories and context references (spec §15, §31)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class MemoryIn(BaseModel):
    kind: str  # FACT | EVIDENCE | DECISION | OPINION | APPROVAL
    content: str
    scope: str = "project"  # execution | project | agent
    agent_id: UUID | None = None
    provenance: str | None = None
    freshness_at: datetime | None = None


class MemoryOut(BaseModel):
    id: UUID
    scope: str
    kind: str
    content: str
    provenance: str | None
    freshness_at: datetime | None
    agent_id: UUID | None


class ContextItemIn(BaseModel):
    tier: int = 5  # T0..T6 (spec §15)
    kind: str  # code | evidence | message | artifact | memory | plan
    ref: str
    summary: str | None = None
    tokens_est: int | None = None
    confidence: float | None = None
    task_id: UUID | None = None


class ContextItemOut(BaseModel):
    id: UUID
    tier: int
    kind: str
    ref: str
    summary: str | None
    tokens_est: int | None
    confidence: float | None
    task_id: UUID | None

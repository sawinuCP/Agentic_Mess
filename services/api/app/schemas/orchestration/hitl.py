"""HITL DTOs (spec §25)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class HitlRequestOut(BaseModel):
    id: UUID
    project_id: UUID | None
    task_id: UUID | None
    kind: str
    question: str
    choices: list[str]
    risk: str
    status: str
    decided_by: str | None
    decision_note: str | None
    created_at: datetime
    decided_at: datetime | None


class DecideIn(BaseModel):
    decision: str  # approved | rejected | modified
    decided_by: str = "user"
    note: str | None = None
    payload_patch: dict[str, Any] | None = None


class CancelIn(BaseModel):
    decided_by: str = "user"

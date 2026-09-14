"""Message DTOs (spec §14 envelope)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class MessageIn(BaseModel):
    conversation_id: UUID | None = None
    sender_agent_id: UUID | None = None
    recipient_agent_id: UUID | None = None
    task_id: UUID | None = None
    type: str  # request|response|progress|artifact|question|broadcast
    payload: dict[str, Any] = {}
    payload_ref: UUID | None = None
    priority: int = 5
    correlation_id: str | None = None
    reply_to: UUID | None = None
    ttl_seconds: int | None = None


class MessageOut(BaseModel):
    id: UUID
    conversation_id: UUID
    sender_agent_id: UUID | None
    recipient_agent_id: UUID | None
    task_id: UUID | None
    type: str
    payload: dict[str, Any]
    payload_ref: UUID | None
    priority: int
    correlation_id: str | None
    reply_to: UUID | None
    created_at: datetime
    expires_at: datetime | None

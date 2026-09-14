"""Durable inter-agent messages (spec §14). Delivery fan-out via NATS lands in Phase 4."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.db.models import Message

router = APIRouter(tags=["messages"])


class MessageIn(BaseModel):
    conversation_id: uuid.UUID | None = None
    sender_agent_id: uuid.UUID | None = None
    recipient_agent_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    type: str  # request|response|progress|artifact|question|broadcast
    payload: dict[str, Any] = {}
    payload_ref: uuid.UUID | None = None
    priority: int = 5
    correlation_id: str | None = None
    reply_to: uuid.UUID | None = None
    ttl_seconds: int | None = None


class MessageOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_agent_id: uuid.UUID | None
    recipient_agent_id: uuid.UUID | None
    task_id: uuid.UUID | None
    type: str
    payload: dict[str, Any]
    payload_ref: uuid.UUID | None
    priority: int
    correlation_id: str | None
    reply_to: uuid.UUID | None
    created_at: datetime
    expires_at: datetime | None


def _out(message: Message) -> MessageOut:
    return MessageOut(
        id=message.id,
        conversation_id=message.conversation_id,
        sender_agent_id=message.sender_agent_id,
        recipient_agent_id=message.recipient_agent_id,
        task_id=message.task_id,
        type=message.type,
        payload=message.payload or {},
        payload_ref=message.payload_ref,
        priority=message.priority,
        correlation_id=message.correlation_id,
        reply_to=message.reply_to,
        created_at=message.created_at,
        expires_at=message.expires_at,
    )


@router.post("/api/messages", response_model=MessageOut, status_code=201)
def send_message(body: MessageIn, db: Session = Depends(get_db)) -> MessageOut:
    expires_at = (
        datetime.now(UTC) + timedelta(seconds=body.ttl_seconds) if body.ttl_seconds else None
    )
    message = Message(
        conversation_id=body.conversation_id or uuid.uuid4(),
        sender_agent_id=body.sender_agent_id,
        recipient_agent_id=body.recipient_agent_id,
        task_id=body.task_id,
        type=body.type,
        payload=body.payload,
        payload_ref=body.payload_ref,
        priority=body.priority,
        correlation_id=body.correlation_id,
        reply_to=body.reply_to,
        expires_at=expires_at,
    )
    db.add(message)
    db.commit()
    return _out(message)


@router.get("/api/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def conversation_messages(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
) -> list[MessageOut]:
    """Replay a conversation in order (messages are durable and replayable)."""
    rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
        .limit(limit)
    ).all()
    return [_out(m) for m in rows]


@router.get("/api/agents/{agent_id}/messages", response_model=list[MessageOut])
def agent_inbox(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
) -> list[MessageOut]:
    rows = db.scalars(
        select(Message)
        .where(Message.recipient_agent_id == agent_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    ).all()
    return [_out(m) for m in reversed(rows)]

"""Message service: durable, replayable inter-agent envelopes (spec §14)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Message
from app.schemas.messages import MessageIn, MessageOut


def message_out(message: Message) -> MessageOut:
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


def send_message(db: Session, body: MessageIn) -> MessageOut:
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
    return message_out(message)


def conversation_messages(db: Session, conversation_id: uuid.UUID, limit: int) -> list[MessageOut]:
    """Replay a conversation in order (messages are durable and replayable)."""
    rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
        .limit(limit)
    ).all()
    return [message_out(m) for m in rows]


def agent_inbox(db: Session, agent_id: uuid.UUID, limit: int) -> list[MessageOut]:
    rows = db.scalars(
        select(Message)
        .where(Message.recipient_agent_id == agent_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    ).all()
    return [message_out(m) for m in reversed(rows)]

"""Inter-agent messages (spec §14 envelope). Durable and replayable."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation", "conversation_id"),
        Index("ix_messages_recipient", "recipient_agent_id", "created_at"),
        Index("ix_messages_correlation", "correlation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        index=False
    )  # covered by ix_messages_conversation
    sender_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), default=None
    )
    recipient_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), default=None
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), default=None
    )
    type: Mapped[str] = mapped_column(
        String(50)
    )  # request|response|progress|artifact|question|broadcast
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=func.jsonb_build_object()
    )
    payload_ref: Mapped[uuid.UUID | None] = mapped_column(
        default=None
    )  # artifact id for large payloads
    priority: Mapped[int] = mapped_column(Integer, default=5)
    correlation_id: Mapped[str | None] = mapped_column(String(64), default=None)
    reply_to: Mapped[uuid.UUID | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    # Delivery bookkeeping (FR-010): PG is the source of truth; NATS JetStream is an
    # at-least-once transport. ``delivered_at`` stays NULL until a broker ack.
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    delivery_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

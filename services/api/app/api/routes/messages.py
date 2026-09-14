"""Durable message endpoints (spec §14). NATS delivery fan-out lands in Phase 4."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.messages import MessageIn, MessageOut
from app.services import messages as message_service

router = APIRouter(tags=["messages"])


@router.post("/api/messages", response_model=MessageOut, status_code=201)
async def send_message(body: MessageIn, db: Session = Depends(get_db)) -> MessageOut:
    return await asyncio.to_thread(message_service.send_message, db, body)


@router.get("/api/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def conversation_messages(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
) -> list[MessageOut]:
    """Replay a conversation in order (messages are durable and replayable)."""
    return await asyncio.to_thread(
        message_service.conversation_messages, db, conversation_id, limit
    )


@router.get("/api/agents/{agent_id}/messages", response_model=list[MessageOut])
async def agent_inbox(
    agent_id: uuid.UUID,
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=500),
) -> list[MessageOut]:
    return await asyncio.to_thread(message_service.agent_inbox, db, agent_id, limit)

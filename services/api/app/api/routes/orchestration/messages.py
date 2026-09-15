"""Durable message endpoints (spec §14) with NATS JetStream fan-out (FR-010)."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.errors import DomainError
from app.messaging.broker import BrokerUnavailable, build_broker
from app.schemas.messages import DeliveryOut, MessageIn, MessageOut
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


@router.post("/api/messages/deliver-pending", response_model=DeliveryOut)
async def deliver_pending(
    request: Request,
    db: Session = Depends(get_db),
    limit: int = Query(200, ge=1, le=1000),
) -> DeliveryOut:
    """One at-least-once fan-out pass over undelivered durable messages (FR-010).

    Fail-closed: with delivery disabled (or the broker unreachable on every message)
    this returns 503 and nothing is marked delivered — the durable record is intact.
    """
    broker = build_broker(request.app.state.settings)
    try:
        pending = await asyncio.to_thread(message_service.pending_messages, db, limit)
        delivered_ids: list[uuid.UUID] = []
        errors: dict[str, str] = {}
        attempted: list[uuid.UUID] = []
        for message in pending:
            envelope = message_service.envelope_from(message)
            attempted.append(envelope.message_id)
            try:
                await broker.publish(envelope)
            except BrokerUnavailable as exc:
                errors[str(envelope.message_id)] = exc.message
            else:
                delivered_ids.append(envelope.message_id)
        await asyncio.to_thread(message_service.record_attempts, db, attempted)
        delivered_count = await asyncio.to_thread(message_service.mark_delivered, db, delivered_ids)
    finally:
        await broker.close()

    if not delivered_ids and errors:
        # Every publish failed — surface the transport failure (fail-closed 503).
        raise DomainError(next(iter(errors.values())), 503)
    return DeliveryOut(
        pending_count=len(pending),
        delivered_count=delivered_count,
        failed_count=len(errors),
        errors=errors,
    )

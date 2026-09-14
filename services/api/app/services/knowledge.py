"""Knowledge service: typed memories and durable context references (spec §15, §31)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.models import ContextItem, Memory
from app.schemas.knowledge import ContextItemIn, MemoryIn

MEMORY_KINDS = ("FACT", "EVIDENCE", "DECISION", "OPINION", "APPROVAL")


def create_memory(db: Session, project_id: uuid.UUID, body: MemoryIn) -> Memory:
    if body.kind not in MEMORY_KINDS:
        raise DomainError(f"kind must be one of {MEMORY_KINDS}", 422)
    memory = Memory(
        project_id=project_id,
        scope=body.scope,
        agent_id=body.agent_id,
        kind=body.kind,
        content=body.content,
        provenance=body.provenance,
        freshness_at=body.freshness_at,
    )
    db.add(memory)
    db.commit()
    return memory


def list_memories(db: Session, project_id: uuid.UUID, kind: str | None) -> list[Memory]:
    query = select(Memory).where(Memory.project_id == project_id)
    if kind:
        query = query.where(Memory.kind == kind)
    return list(db.scalars(query.order_by(Memory.created_at.desc())).all())


def create_context_item(db: Session, project_id: uuid.UUID, body: ContextItemIn) -> ContextItem:
    if not 0 <= body.tier <= 6:
        raise DomainError("tier must be 0..6 (spec §15)", 422)
    item = ContextItem(
        project_id=project_id,
        task_id=body.task_id,
        tier=body.tier,
        kind=body.kind,
        ref=body.ref,
        summary=body.summary,
        tokens_est=body.tokens_est,
        confidence=body.confidence,
    )
    db.add(item)
    db.commit()
    return item


def list_context_items(
    db: Session, project_id: uuid.UUID, tier: int | None, kind: str | None
) -> list[ContextItem]:
    query = select(ContextItem).where(ContextItem.project_id == project_id)
    if tier is not None:
        query = query.where(ContextItem.tier == tier)
    if kind:
        query = query.where(ContextItem.kind == kind)
    return list(db.scalars(query.order_by(ContextItem.created_at.desc())).all())

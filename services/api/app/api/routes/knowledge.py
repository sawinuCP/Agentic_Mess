"""Knowledge endpoints: typed memories and durable context references (spec §15, §31)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.core.errors import DomainError
from app.db.models import ContextItem, Memory, Project

router = APIRouter(tags=["knowledge"])

MEMORY_KINDS = ("FACT", "EVIDENCE", "DECISION", "OPINION", "APPROVAL")


class MemoryIn(BaseModel):
    kind: str  # FACT | EVIDENCE | DECISION | OPINION | APPROVAL
    content: str
    scope: str = "project"  # execution | project | agent
    agent_id: uuid.UUID | None = None
    provenance: str | None = None
    freshness_at: datetime | None = None


class MemoryOut(BaseModel):
    id: uuid.UUID
    scope: str
    kind: str
    content: str
    provenance: str | None
    freshness_at: datetime | None
    agent_id: uuid.UUID | None


class ContextItemIn(BaseModel):
    tier: int = 5  # T0..T6 (spec §15)
    kind: str  # code | evidence | message | artifact | memory | plan
    ref: str
    summary: str | None = None
    tokens_est: int | None = None
    confidence: float | None = None
    task_id: uuid.UUID | None = None


class ContextItemOut(BaseModel):
    id: uuid.UUID
    tier: int
    kind: str
    ref: str
    summary: str | None
    tokens_est: int | None
    confidence: float | None
    task_id: uuid.UUID | None


@router.post("/api/projects/{project_id}/memories", response_model=MemoryOut, status_code=201)
def create_memory(
    body: MemoryIn, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> MemoryOut:
    if body.kind not in MEMORY_KINDS:
        raise DomainError(f"kind must be one of {MEMORY_KINDS}", 422)
    memory = Memory(
        project_id=project.id,
        scope=body.scope,
        agent_id=body.agent_id,
        kind=body.kind,
        content=body.content,
        provenance=body.provenance,
        freshness_at=body.freshness_at,
    )
    db.add(memory)
    db.commit()
    return MemoryOut(
        id=memory.id,
        scope=memory.scope,
        kind=memory.kind,
        content=memory.content,
        provenance=memory.provenance,
        freshness_at=memory.freshness_at,
        agent_id=memory.agent_id,
    )


@router.get("/api/projects/{project_id}/memories", response_model=list[MemoryOut])
def list_memories(
    project: Project = Depends(get_project),
    kind: str | None = None,
    db: Session = Depends(get_db),
) -> list[MemoryOut]:
    query = select(Memory).where(Memory.project_id == project.id)
    if kind:
        query = query.where(Memory.kind == kind)
    rows = db.scalars(query.order_by(Memory.created_at.desc())).all()
    return [
        MemoryOut(
            id=m.id,
            scope=m.scope,
            kind=m.kind,
            content=m.content,
            provenance=m.provenance,
            freshness_at=m.freshness_at,
            agent_id=m.agent_id,
        )
        for m in rows
    ]


@router.post(
    "/api/projects/{project_id}/context-items", response_model=ContextItemOut, status_code=201
)
def create_context_item(
    body: ContextItemIn, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> ContextItemOut:
    if not 0 <= body.tier <= 6:
        raise DomainError("tier must be 0..6 (spec §15)", 422)
    item = ContextItem(
        project_id=project.id,
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
    return ContextItemOut(
        id=item.id,
        tier=item.tier,
        kind=item.kind,
        ref=item.ref,
        summary=item.summary,
        tokens_est=item.tokens_est,
        confidence=item.confidence,
        task_id=item.task_id,
    )


@router.get("/api/projects/{project_id}/context-items", response_model=list[ContextItemOut])
def list_context_items(
    project: Project = Depends(get_project),
    tier: int | None = Query(None, ge=0, le=6),
    kind: str | None = None,
    db: Session = Depends(get_db),
) -> list[ContextItemOut]:
    query = select(ContextItem).where(ContextItem.project_id == project.id)
    if tier is not None:
        query = query.where(ContextItem.tier == tier)
    if kind:
        query = query.where(ContextItem.kind == kind)
    rows = db.scalars(query.order_by(ContextItem.created_at.desc())).all()
    return [
        ContextItemOut(
            id=c.id,
            tier=c.tier,
            kind=c.kind,
            ref=c.ref,
            summary=c.summary,
            tokens_est=c.tokens_est,
            confidence=c.confidence,
            task_id=c.task_id,
        )
        for c in rows
    ]

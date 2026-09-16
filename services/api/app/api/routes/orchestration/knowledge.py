"""Knowledge endpoints: typed memories and durable context references (spec §15, §31)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.db.models import ContextItem, Memory, Project
from app.schemas.orchestration.knowledge import ContextItemIn, ContextItemOut, MemoryIn, MemoryOut
from app.services.orchestration import knowledge as knowledge_service

router = APIRouter(tags=["knowledge"])


def _memory_out(memory: Memory) -> MemoryOut:
    return MemoryOut(
        id=memory.id,
        scope=memory.scope,
        kind=memory.kind,
        content=memory.content,
        provenance=memory.provenance,
        freshness_at=memory.freshness_at,
        agent_id=memory.agent_id,
    )


def _item_out(item: ContextItem) -> ContextItemOut:
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


@router.post("/api/projects/{project_id}/memories", response_model=MemoryOut, status_code=201)
async def create_memory(
    body: MemoryIn, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> MemoryOut:
    memory = await asyncio.to_thread(knowledge_service.create_memory, db, project.id, body)
    return _memory_out(memory)


@router.get("/api/projects/{project_id}/memories", response_model=list[MemoryOut])
async def list_memories(
    project: Project = Depends(get_project),
    kind: str | None = None,
    db: Session = Depends(get_db),
) -> list[MemoryOut]:
    rows = await asyncio.to_thread(knowledge_service.list_memories, db, project.id, kind)
    return [_memory_out(m) for m in rows]


@router.post(
    "/api/projects/{project_id}/context-items",
    response_model=ContextItemOut,
    status_code=201,
)
async def create_context_item(
    body: ContextItemIn, project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> ContextItemOut:
    item = await asyncio.to_thread(knowledge_service.create_context_item, db, project.id, body)
    return _item_out(item)


@router.get("/api/projects/{project_id}/context-items", response_model=list[ContextItemOut])
async def list_context_items(
    project: Project = Depends(get_project),
    tier: int | None = Query(None, ge=0, le=6),
    kind: str | None = None,
    db: Session = Depends(get_db),
) -> list[ContextItemOut]:
    rows = await asyncio.to_thread(knowledge_service.list_context_items, db, project.id, tier, kind)
    return [_item_out(i) for i in rows]

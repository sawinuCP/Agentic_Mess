"""Code-intelligence DTOs (Phase 5): index status, symbols, retrieval, costs."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class IndexRequestIn(BaseModel):
    full: bool = False  # false = incremental (hash-driven), true = re-extract everything


class IndexStatsOut(BaseModel):
    files: int
    indexed: int
    updated: int
    skipped: int
    removed: int
    symbols: int


class IntelligenceStatusOut(BaseModel):
    engines: dict[str, str]  # language -> ast | tree-sitter | regex
    files: int
    symbols: int
    by_language: dict[str, int]
    by_kind: dict[str, int]
    last_indexed_at: datetime | None


class SymbolOut(BaseModel):
    id: UUID
    path: str
    name: str
    kind: str
    parent: str | None
    start_line: int
    end_line: int
    signature: str | None
    doc: str | None
    language: str


class RetrievalHitOut(BaseModel):
    path: str
    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str
    score: float
    matched: str  # lexical | semantic | hybrid


class RetrievalOut(BaseModel):
    query: str
    hits: list[RetrievalHitOut]


class CostsOut(BaseModel):
    invocations: int
    total_tokens: int
    by_model: dict[str, int]
    by_role: dict[str, int]
    task_id: UUID | None = Field(
        None, description="Present when the summary was scoped to one task"
    )
    budget_tokens_per_task: int
    extra: dict[str, Any] = {}

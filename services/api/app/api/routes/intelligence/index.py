"""Code-intelligence index endpoints (Phase 5): run/inspect the symbol index."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.codeintel import indexer, parser
from app.db.models import Project, Symbol, SymbolFile
from app.schemas.intelligence.intelligence import (
    IndexRequestIn,
    IndexStatsOut,
    IntelligenceStatusOut,
)

router = APIRouter(tags=["intelligence"])


def _stats(db: Session, project_id: uuid.UUID) -> dict:
    file_rows = db.scalars(select(SymbolFile).where(SymbolFile.project_id == project_id)).all()
    by_language: dict[str, int] = {}
    for row in file_rows:
        by_language[row.language] = by_language.get(row.language, 0) + 1
    kind_rows = db.execute(
        select(Symbol.kind, func.count())
        .where(Symbol.project_id == project_id)
        .group_by(Symbol.kind)
    ).all()
    last_indexed = max((row.indexed_at for row in file_rows), default=None)
    return {
        "engines": parser.engines(),
        "files": len(file_rows),
        "symbols": sum(row.symbol_count for row in file_rows),
        "by_language": by_language,
        "by_kind": {kind: int(count) for kind, count in kind_rows},
        "last_indexed_at": last_indexed,
    }


@router.post("/api/projects/{project_id}/intelligence/index", response_model=IndexStatsOut)
async def run_index(
    request: Request,
    project_id: uuid.UUID,
    body: IndexRequestIn | None = None,
    project: Project = Depends(get_project),
    db: Session = Depends(get_db),
) -> IndexStatsOut:
    """Index the project's code — incremental (hash-driven) by default;
    ``{"full": true}`` re-extracts every file (PERF-008)."""
    settings = request.app.state.settings
    stats = await asyncio.to_thread(
        indexer.update_index,
        db,
        project.id,
        Path(project.root_path),
        full=bool(body.full) if body is not None else False,
        max_files=settings.index_max_files,
        max_file_bytes=settings.index_max_file_bytes,
    )
    return IndexStatsOut(**stats)


@router.get("/api/projects/{project_id}/intelligence/status", response_model=IntelligenceStatusOut)
async def status(project_id: uuid.UUID, db: Session = Depends(get_db)) -> IntelligenceStatusOut:
    """Extraction engines per language + index size/shape for this project."""
    return IntelligenceStatusOut(**_stats(db, project_id))

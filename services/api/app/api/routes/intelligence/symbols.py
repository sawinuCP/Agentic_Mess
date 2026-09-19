"""Symbol search, document symbols, hybrid retrieval, and SCIP export (Phase 5)."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import __version__
from app.api.deps import get_db, get_project
from app.codeintel import indexer
from app.codeintel.retrieval import retrieve
from app.codeintel.scip import build_scip_index
from app.db.models import Project, Symbol
from app.schemas.intelligence.intelligence import RetrievalHitOut, RetrievalOut, SymbolOut

router = APIRouter(tags=["symbols"])


def _to_out(symbol: Symbol, path: str, language: str) -> SymbolOut:
    return SymbolOut(
        id=symbol.id,
        path=path,
        name=symbol.name,
        kind=symbol.kind,
        parent=symbol.parent,
        start_line=symbol.start_line,
        end_line=symbol.end_line,
        signature=symbol.signature,
        doc=symbol.doc,
        language=language,
    )


@router.get("/api/projects/{project_id}/symbols", response_model=list[SymbolOut])
async def search_symbols(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    q: str = Query("", description="Substring/prefix match on the symbol name"),
    kind: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[SymbolOut]:
    """Search the durable symbol index (workspace-symbol style)."""
    rows = indexer.search_symbols(db, project_id, q=q, kind=kind, limit=limit)
    return [_to_out(symbol, file.path, file.language) for symbol, file in rows]


@router.get("/api/projects/{project_id}/symbols/file", response_model=list[SymbolOut])
async def file_symbols(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    path: str = Query(..., description="Project-relative file path"),
) -> list[SymbolOut]:
    """Document symbols for one file (LSP documentSymbol style)."""
    rows = indexer.file_symbols(db, project_id, path=path)
    return [_to_out(symbol, file.path, file.language) for symbol, file in rows]


@router.get("/api/projects/{project_id}/intelligence/retrieve", response_model=RetrievalOut)
async def retrieve_hits(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    q: str = Query(..., min_length=1, description="Natural-language or symbol query"),
    k: int = Query(6, ge=1, le=25),
) -> RetrievalOut:
    """Hybrid retrieval (lexical + embeddings) — the same ranking agents see in T3."""
    hits = retrieve(db, project_id, q, k=k)
    return RetrievalOut(
        query=q,
        hits=[
            RetrievalHitOut(
                path=hit.path,
                name=hit.name,
                kind=hit.kind,
                start_line=hit.start_line,
                end_line=hit.end_line,
                signature=hit.signature,
                score=hit.score,
                matched=hit.matched,
            )
            for hit in hits
        ],
    )


@router.get("/api/projects/{project_id}/intelligence/scip")
async def scip_export(
    project: Project = Depends(get_project), db: Session = Depends(get_db)
) -> dict:
    """SCIP-JSON export (documented subset: metadata + documents + occurrences)."""
    return build_scip_index(
        db,
        project_root=str(Path(project.root_path)),
        project_name=project.name,
        tool_name="ai-harness",
        tool_version=__version__,
        project_id=project.id,
    )

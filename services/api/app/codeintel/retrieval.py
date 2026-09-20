"""Hybrid retrieval (Phase 5): lexical ranking first, pgvector embeddings as one ranker.

Per ARCHITECTURE §8 the answer to "what is relevant" must not be embedding-only:
lexical symbol matching (exact/prefix/token overlap/signature hits, with kind
boosts) is combined with cosine similarity over the stored symbol embeddings.
Returns path:line anchored chunks ready for context injection (T3) or the UI.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.codeintel.embeddings import embed_text
from app.db.models import Symbol, SymbolFile

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

_SEMANTIC_CANDIDATES = 60
_SCAN_LIMIT = 5000


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    path: str
    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str
    score: float
    matched: str  # lexical|semantic|hybrid


def _tokens(text: str) -> set[str]:
    """Lexical tokens with the same snake_case/camelCase split as the
    embedding tokenizer — identifiers like ``process_payload_1999`` must
    match on every constituent (including digit parts), or digit-suffixed
    symbols become invisible to exact search."""
    out: set[str] = set()
    for raw in _TOKEN_RE.findall(text):
        for chunk in raw.split("_"):
            for part in _CAMEL_RE.split(chunk):
                part = part.lower()
                if len(part) >= 2:
                    out.add(part)
    return out


def _lexical_scores(symbols: Sequence[Symbol], query: str) -> dict[uuid.UUID, float]:
    query_lower = query.strip().lower()
    query_tokens = _tokens(query)
    scores: dict[uuid.UUID, float] = {}
    for symbol in symbols:
        name_lower = symbol.name.lower()
        name_tokens = _tokens(symbol.name)
        score = 0.0
        if query_lower and name_lower == query_lower:
            score += 10.0
        elif query_lower and name_lower.startswith(query_lower):
            score += 6.0
        overlap = len(query_tokens & name_tokens)
        if overlap:
            score += 2.0 * overlap
        signature = (symbol.signature or "").lower()
        for token in query_tokens:
            if token in signature:
                score += 0.5
        if symbol.kind in ("class", "function", "method"):
            score += 0.5
        if score > 0:
            scores[symbol.id] = score
    return scores


def retrieve(
    db: Session,
    project_id: object,
    query: str,
    *,
    k: int = 6,
) -> list[RetrievedChunk]:
    """Hybrid symbol retrieval for ``query`` (empty query returns the newest symbols)."""
    symbols = db.scalars(
        select(Symbol)
        .where(Symbol.project_id == project_id)
        .order_by(Symbol.start_line)
        .limit(_SCAN_LIMIT)
    ).all()
    paths = {
        row.id: row.path
        for row in db.scalars(select(SymbolFile).where(SymbolFile.project_id == project_id)).all()
    }

    lexical = _lexical_scores(symbols, query)
    max_lexical = max(lexical.values()) if lexical else 0.0

    semantic: dict[uuid.UUID, float] = {}
    query_vector = embed_text(query) if query.strip() else None
    if query_vector:
        distance = Symbol.embedding.cosine_distance(query_vector)
        rows = db.execute(
            select(Symbol.id, distance)
            .where(Symbol.project_id == project_id, Symbol.embedding.is_not(None))
            .order_by(distance)
            .limit(_SEMANTIC_CANDIDATES)
        ).all()
        for symbol_id, dist in rows:
            semantic[symbol_id] = max(0.0, 1.0 - float(dist))

    combined: dict[uuid.UUID, tuple[float, str]] = {}
    for symbol in symbols:
        lex = lexical.get(symbol.id, 0.0)
        sem = semantic.get(symbol.id, 0.0)
        lex_norm = lex / max_lexical if max_lexical else 0.0
        if lex > 0 and sem > 0:
            # Hybrid, but an exact lexical match is never outranked by
            # embedding noise: with uninformative vectors (offline default)
            # the semantic term is arbitrary, while identifiers are precise.
            score, matched = max(lex_norm, 0.6 * lex_norm + 0.4 * sem), "hybrid"
        elif lex > 0:
            score, matched = lex_norm, "lexical"
        elif sem > 0:
            score, matched = sem, "semantic"
        else:
            continue
        combined[symbol.id] = (score, matched)

    ranked_ids = sorted(combined, key=lambda sid: combined[sid][0], reverse=True)[:k]
    by_id = {symbol.id: symbol for symbol in symbols}
    out: list[RetrievedChunk] = []
    for symbol_id in ranked_ids:
        symbol = by_id[symbol_id]
        out.append(
            RetrievedChunk(
                path=paths.get(symbol.file_id, ""),
                name=symbol.name,
                kind=symbol.kind,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                signature=symbol.signature or "",
                score=round(combined[symbol_id][0], 4),
                matched=combined[symbol_id][1],
            )
        )
    return out

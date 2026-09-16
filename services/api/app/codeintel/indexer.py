"""Symbol indexer (PERF-008): full + incremental, hash-driven, embedding-backed.

Walks a project (skipping dependency/asset directories), extracts symbols with the
best engine per language, and stores them with embeddings. A file is re-indexed
only when its content hash changed; deleted files are pruned. Every mutation is
one transaction per file so a crash mid-index leaves a consistent partial index.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.codeintel import embeddings as embedding_module
from app.codeintel.parser import detect_language, extract_symbols
from app.db.models import Symbol, SymbolFile

IGNORED_DIRS = {
    ".git",
    ".hg",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".harness",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".idea",
    ".vscode",
    "dist",
    "build",
    "target",
    "coverage",
    "data",
}

DEFAULT_MAX_FILES = 5000
DEFAULT_MAX_FILE_BYTES = 512_000


def collect_files(root: Path, *, max_files: int) -> list[tuple[Path, str]]:
    """All indexable (path, language) pairs under ``root``, deterministic order."""
    found: list[tuple[Path, str]] = []
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS and not d.startswith("."))
        for name in sorted(files):
            path = Path(base) / name
            language = detect_language(name)
            if language is None:
                continue
            found.append((path, language))
            if len(found) >= max_files:
                return found
    return found


def _file_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _embedding_for(name: str, kind: str, signature: str, doc: str, parent: str) -> list[float]:
    return embedding_module.embed_text(f"{kind} {parent} {name} {signature} {doc}")


def update_index(
    db: Session,
    project_id: Any,
    root: Path,
    *,
    full: bool = False,
    max_files: int = DEFAULT_MAX_FILES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
) -> dict[str, int]:
    """Incrementally index ``root`` for ``project_id``. Returns run statistics."""
    root = Path(root)
    candidates = collect_files(root, max_files=max_files)

    rows = db.scalars(select(SymbolFile).where(SymbolFile.project_id == project_id)).all()
    existing: dict[str, SymbolFile] = {row.path: row for row in rows}
    seen_paths: set[str] = set()

    indexed = updated = skipped = removed = 0
    for path, language in candidates:
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:  # pragma: no cover — walk is rooted at `root`
            continue
        seen_paths.add(rel)
        try:
            content = path.read_bytes()
        except OSError:
            continue
        if len(content) > max_file_bytes:
            continue
        sha = _file_sha256(content)
        row = existing.get(rel)
        if row is not None and row.sha256 == sha and not full:
            skipped += 1
            continue

        spans = extract_symbols(content.decode("utf-8", errors="replace"), language)
        if row is None:
            row = SymbolFile(project_id=project_id, path=rel, language=language)
            db.add(row)
            indexed += 1
        else:
            updated += 1
            db.execute(delete(Symbol).where(Symbol.file_id == row.id))
        row.language = language
        row.sha256 = sha
        row.symbol_count = len(spans)
        db.flush()  # assign row.id before inserting symbols

        for span in spans:
            db.add(
                Symbol(
                    project_id=project_id,
                    file_id=row.id,
                    name=span.name,
                    kind=span.kind,
                    parent=span.parent,
                    start_line=span.start_line,
                    end_line=span.end_line,
                    signature=span.signature,
                    doc=span.doc,
                    embedding=_embedding_for(
                        span.name, span.kind, span.signature, span.doc, span.parent
                    ),
                )
            )
        db.commit()

    for existing_path, row in existing.items():
        if existing_path not in seen_paths:
            db.execute(delete(Symbol).where(Symbol.file_id == row.id))
            db.execute(delete(SymbolFile).where(SymbolFile.id == row.id))
            removed += 1
    db.commit()

    return {
        "files": len(candidates),
        "indexed": indexed,
        "updated": updated,
        "skipped": skipped,
        "removed": removed,
        "symbols": sum(
            row.symbol_count
            for row in db.scalars(
                select(SymbolFile).where(SymbolFile.project_id == project_id)
            ).all()
        ),
    }


def clear_index(db: Session, project_id: Any) -> int:
    """Remove every indexed file (and cascade its symbols) for a project."""
    rows = db.scalars(select(SymbolFile).where(SymbolFile.project_id == project_id)).all()
    count = len(rows)
    db.execute(delete(SymbolFile).where(SymbolFile.project_id == project_id))
    db.commit()
    return count

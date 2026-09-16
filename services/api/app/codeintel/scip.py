"""SCIP-JSON export (Phase 5): a language-neutral symbol index from our tables.

This emits a documented **subset** of SCIP-JSON (metadata + documents + symbol
occurrences with ranges) built from the durable symbol index. Monikers follow the
SCIP ``<scheme> ' ' <package> ' ' <descriptor>`` shape with a harness scheme so
consumers can prototype tooling today; full binary-protocol interop with the scip
CLI lands with the Phase-8 tooling work.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Symbol, SymbolFile

SCIP_LANGUAGES = {
    "python": "python",
    "javascript": "javascript",
    "typescript": "typescript",
    "go": "go",
    "rust": "rust",
    "csharp": "c_sharp",
}


def _moniker(language: str, path: str, name: str, kind: str, parent: str) -> str:
    """SCIP-shaped symbol string (harness scheme, documented subset).

    Descriptors follow the SCIP conventions: callables end with ``().`` (call +
    term), types with ``.``; methods are attached to their owner with ``#``.
    """
    qualifiers = {"class": "", "interface": "#", "struct": "!", "enum": "$", "trait": "~"}
    delimiter = "#" if (kind in ("method",) and parent) else "/"
    owner = f"{parent}{delimiter}" if parent else ""
    suffix = "()." if kind in ("function", "method") else "."
    scheme = SCIP_LANGUAGES.get(language, language)
    return f"{scheme} . {path}/{owner}{name}{qualifiers.get(kind, '')}{suffix}"


def build_scip_index(
    db: Session,
    *,
    project_root: str,
    project_name: str,
    tool_name: str,
    tool_version: str,
    project_id: object,
) -> dict[str, Any]:
    """Build a SCIP-JSON document set from the project's symbol index."""
    file_rows = db.scalars(
        select(SymbolFile).where(SymbolFile.project_id == project_id).order_by(SymbolFile.path)
    ).all()
    symbols = (
        db.scalars(
            select(Symbol).where(Symbol.project_id == project_id).order_by(Symbol.start_line)
        ).all()
        if file_rows
        else []
    )

    documents: list[dict[str, Any]] = []
    for file_row in file_rows:
        file_symbols = [s for s in symbols if s.file_id == file_row.id]
        documents.append(
            {
                "relativePath": file_row.path,
                "language": SCIP_LANGUAGES.get(file_row.language, file_row.language),
                "symbols": [
                    _moniker(
                        file_row.language,
                        file_row.path,
                        s.name,
                        s.kind,
                        s.parent or "",
                    )
                    for s in file_symbols
                ],
                "occurrences": [
                    {
                        # SCIP ranges are zero-based [startLine, startChar, endLine].
                        "range": [s.start_line - 1, 0, s.end_line - 1],
                        "symbol": _moniker(
                            file_row.language,
                            file_row.path,
                            s.name,
                            s.kind,
                            s.parent or "",
                        ),
                        "symbolRoles": 1,  # 1 = definition
                    }
                    for s in file_symbols
                ],
            }
        )

    return {
        "metadata": {
            "projectRoot": project_root,
            "projectName": project_name,
            "textDocumentEncoding": "UTF-8",
            "toolInfo": {"name": tool_name, "version": tool_version},
        },
        "documents": documents,
    }

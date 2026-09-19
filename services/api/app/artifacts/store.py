"""Content-addressed artifact store.

Raw bytes live on disk under ``{root}/{sha[:2]}/{sha[2:4]}/{sha}`` so identical
content is stored once; the ``artifacts`` table holds metadata (name, kind, mime,
size, sha256, project). Large outputs must never live in relational rows (spec §30).
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from app.core.errors import DomainError


class ArtifactStoreError(DomainError):
    """Store failures map directly onto HTTP responses (400/404/416)."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message, status_code)
        self.message = message
        self.status_code = status_code


@dataclass(slots=True)
class StoredBlob:
    sha256: str
    storage_path: str  # relative to the store root
    size: int


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _blob_path(self, sha: str) -> Path:
        return self.root / sha[:2] / sha[2:4] / sha

    def put(self, data: bytes) -> StoredBlob:
        sha = hashlib.sha256(data).hexdigest()
        path = self._blob_path(sha)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)
        return StoredBlob(
            sha256=sha, storage_path=path.relative_to(self.root).as_posix(), size=len(data)
        )

    def open(self, storage_path: str) -> bytes:
        resolved = (self.root / storage_path).resolve()
        if self.root not in resolved.parents:
            raise ArtifactStoreError("Invalid artifact storage path", 400)
        if not resolved.is_file():
            raise ArtifactStoreError("Artifact content missing on disk", 404)
        return resolved.read_bytes()

    def _resolve(self, storage_path: str) -> Path:
        resolved = (self.root / storage_path).resolve()
        if self.root not in resolved.parents:
            raise ArtifactStoreError("Invalid artifact storage path", 400)
        if not resolved.is_file():
            raise ArtifactStoreError("Artifact content missing on disk", 404)
        return resolved

    def blob_size(self, storage_path: str) -> int:
        """Size on disk without reading (pruned blobs raise 404 like open)."""
        return self._resolve(storage_path).stat().st_size

    def read_range(self, storage_path: str, start: int, length: int) -> bytes:
        """Read ``length`` bytes at ``start`` (constant memory for the slice)."""
        resolved = self._resolve(storage_path)
        size = resolved.stat().st_size
        if start < 0 or length < 0 or start > size:
            raise ArtifactStoreError("Range start beyond blob end", 416)
        length = min(length, size - start)
        with resolved.open("rb") as handle:
            handle.seek(start)
            return handle.read(length)

    def delete(self, storage_path: str) -> None:
        resolved = (self.root / storage_path).resolve()
        if self.root not in resolved.parents:
            raise ArtifactStoreError("Invalid artifact storage path", 400)
        if resolved.is_file():
            resolved.unlink()


def mime_for_name(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return {
        ".txt": "text/plain",
        ".log": "text/plain",
        ".json": "application/json",
        ".md": "text/markdown",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".svg": "image/svg+xml",
        ".pdf": "application/pdf",
        ".zip": "application/zip",
        ".csv": "text/csv",
        ".html": "text/html",
    }.get(suffix, "application/octet-stream")

"""Filesystem operations for a project root.

Security boundary: every path from the client is validated to resolve *inside* the
project root (SEC-002 posture; this is the same enforcement style the tool gateway
will reuse in Phase 3).
"""

from __future__ import annotations

import base64
import os
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from app.core.errors import DomainError

# Directories never shown or searched (editor noise; keep in sync with frontend).
IGNORED_DIR_NAMES = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        "target",
        ".next",
        ".idea",
        ".vscode",
        "coverage",
        ".eggs",
        "site-packages",
    }
)
MAX_READ_BYTES = 2_000_000
MAX_TREE_ENTRIES = 2000


class FileServiceError(DomainError):
    """Filesystem operation failed; status_code maps onto HTTP responses."""


@dataclass(slots=True)
class TreeEntry:
    name: str
    path: str  # relative, forward slashes
    kind: str  # "file" | "directory"
    size: int = 0
    has_children: bool = False


@dataclass(slots=True)
class FileContent:
    path: str
    content: str
    is_binary: bool
    size: int
    mtime_ms: int


class ProjectFiles:
    """All paths are project-root-relative with forward slashes on the wire."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    # --- path safety -------------------------------------------------------

    def resolve(self, rel: str, *, must_exist: bool = False) -> Path:
        """Resolve a client-supplied relative path, rejecting anything unsafe.

        Checks absoluteness in *both* path flavors (POSIX and Windows, including
        UNC) BEFORE normalization — otherwise '\\\\server\\share\\x' or 'C:/x' could
        masquerade as relative after separator conversion.
        """
        raw = (rel or "").strip()
        if not raw or raw == ".":
            candidate = self.root
        else:
            if PureWindowsPath(raw).is_absolute() or PurePosixPath(raw).is_absolute():
                raise FileServiceError(f"Absolute paths are not allowed: {rel!r}", 400)
            candidate = self.root / raw.replace("\\", "/").strip("/")
        resolved = candidate.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise FileServiceError(f"Path escapes the project root: {rel!r}", 400)
        if must_exist and not resolved.exists():
            raise FileServiceError(f"Path not found: {rel!r}", 404)
        return resolved

    def to_rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    # --- tree --------------------------------------------------------------

    def _children(self, directory: Path) -> list[os.DirEntry[str]]:
        try:
            entries = list(os.scandir(directory))
        except OSError:
            return []
        entries.sort(key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
        return [e for e in entries if e.name not in IGNORED_DIR_NAMES or not e.is_dir()]

    def tree(self, rel_dir: str = "") -> list[TreeEntry]:
        directory = self.resolve(rel_dir, must_exist=True)
        if not directory.is_dir():
            raise FileServiceError(f"Not a directory: {rel_dir!r}", 400)
        result: list[TreeEntry] = []
        for entry in self._children(directory)[:MAX_TREE_ENTRIES]:
            is_dir = entry.is_dir(follow_symlinks=False)
            has_children = bool(self._children(Path(entry.path))) if is_dir else False
            result.append(
                TreeEntry(
                    name=entry.name,
                    path=self.to_rel(Path(entry.path)),
                    kind="directory" if is_dir else "file",
                    size=0 if is_dir else entry.stat(follow_symlinks=False).st_size,
                    has_children=has_children,
                )
            )
        return result

    # --- read/write ----------------------------------------------------------

    def read(self, rel: str) -> FileContent:
        path = self.resolve(rel, must_exist=True)
        if not path.is_file():
            raise FileServiceError(f"Not a file: {rel!r}", 400)
        size = path.stat().st_size
        if size > MAX_READ_BYTES:
            raise FileServiceError(
                f"File too large to open ({size} bytes, limit {MAX_READ_BYTES})", 413
            )
        raw = path.read_bytes()
        is_binary = b"\x00" in raw[:8192]
        content = (
            base64.b64encode(raw).decode("ascii")
            if is_binary
            else raw.decode("utf-8", errors="replace")
        )
        return FileContent(
            path=self.to_rel(path),
            content=content,
            is_binary=is_binary,
            size=size,
            mtime_ms=int(path.stat().st_mtime * 1000),
        )

    def write(self, rel: str, content: str) -> FileContent:
        path = self.resolve(rel)
        if path == self.root:
            raise FileServiceError("Cannot write to the project root", 400)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".harness-tmp")
        tmp.write_text(content, encoding="utf-8", newline="")
        os.replace(tmp, path)
        return self.read(rel)

    # --- create/delete/rename ------------------------------------------------

    def create(self, rel: str, kind: str) -> TreeEntry:
        path = self.resolve(rel)
        if path == self.root or path.exists():
            raise FileServiceError(f"Already exists: {rel!r}", 409)
        if kind == "directory":
            path.mkdir(parents=True)
        elif kind == "file":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        else:
            raise FileServiceError(f"Unknown kind: {kind!r}", 422)
        return TreeEntry(name=path.name, path=self.to_rel(path), kind=kind)

    def delete(self, rel: str) -> None:
        path = self.resolve(rel, must_exist=True)
        if path == self.root:
            raise FileServiceError("Refusing to delete the project root", 400)
        if path.name == ".git" and path.is_dir():
            raise FileServiceError("Refusing to delete .git via the editor", 400)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()

    def rename(self, rel: str, new_rel: str) -> TreeEntry:
        src = self.resolve(rel, must_exist=True)
        dst = self.resolve(new_rel)
        if src == self.root or dst == self.root:
            raise FileServiceError("Cannot rename the project root", 400)
        if dst.exists():
            raise FileServiceError(f"Target already exists: {new_rel!r}", 409)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        kind = "directory" if dst.is_dir() else "file"
        return TreeEntry(name=dst.name, path=self.to_rel(dst), kind=kind)

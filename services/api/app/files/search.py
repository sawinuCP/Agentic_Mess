"""Full-text search and flat file listing across a project (FR-001, quick-open)."""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from app.files.service import IGNORED_DIR_NAMES, FileServiceError, ProjectFiles

MAX_SEARCH_RESULTS = 200
MAX_MATCHES_PER_FILE = 20
MAX_SEARCH_FILE_BYTES = 1_000_000
MAX_LIST_FILES = 5000
MAX_LIST_RESULTS = 200
MAX_WALKED_FILES = 20_000


@dataclass(slots=True)
class SearchMatch:
    path: str
    line: int
    column: int
    text: str


def _iter_files(root: Path, sub: str, glob: str | None) -> Iterator[tuple[str, Path]]:
    base = root / sub if sub else root
    walked = 0
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIR_NAMES]
        dirnames.sort()
        for name in sorted(filenames):
            walked += 1
            if walked > MAX_WALKED_FILES:
                raise FileServiceError("Search scope too large; narrow the path", 413)
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if glob and not fnmatch.fnmatch(name, glob) and not fnmatch.fnmatch(rel, glob):
                continue
            yield rel, path


class ProjectSearch:
    def __init__(self, files: ProjectFiles) -> None:
        self.files = files
        self.root = files.root

    def search(
        self,
        query: str,
        *,
        sub_path: str = "",
        is_regex: bool = False,
        case_sensitive: bool = False,
        glob: str | None = None,
    ) -> list[SearchMatch]:
        if not query:
            return []
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(query if is_regex else re.escape(query), flags)
        except re.error as exc:
            raise FileServiceError(f"Invalid regular expression: {exc}", 422) from None

        matches: list[SearchMatch] = []
        for rel, path in _iter_files(self.root, sub_path, glob):
            if len(matches) >= MAX_SEARCH_RESULTS:
                break
            try:
                if path.stat().st_size > MAX_SEARCH_FILE_BYTES:
                    continue
                raw = path.read_bytes()
            except OSError:
                continue
            if b"\x00" in raw[:8192]:
                continue  # binary
            per_file = 0
            for line_no, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
                match = pattern.search(line)
                if match is None:
                    continue
                matches.append(
                    SearchMatch(
                        path=rel,
                        line=line_no,
                        column=match.start() + 1,
                        text=line.strip()[:200],
                    )
                )
                per_file += 1
                if per_file >= MAX_MATCHES_PER_FILE or len(matches) >= MAX_SEARCH_RESULTS:
                    break
        return matches

    def list_files(self, query: str = "") -> list[str]:
        """Flat relative path list for quick-open; best-effort ranking."""
        q = query.strip().lower()
        scored: list[tuple[int, str]] = []
        count = 0
        for rel, _path in _iter_files(self.root, "", None):
            count += 1
            if count > MAX_LIST_FILES:
                break
            if not q:
                scored.append((2, rel))
                continue
            lowered = rel.lower()
            name = lowered.rsplit("/", 1)[-1]
            if name.startswith(q):
                scored.append((0, rel))
            elif q in name:
                scored.append((1, rel))
            elif q in lowered:
                scored.append((3, rel))
        scored.sort(key=lambda item: (item[0], item[1]))
        return [rel for _, rel in scored[:MAX_LIST_RESULTS]]

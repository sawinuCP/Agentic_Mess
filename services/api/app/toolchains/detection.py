"""Project language detection (FR-003): manifests + file extensions, bounded scan."""

from __future__ import annotations

import fnmatch
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.files.service import IGNORED_DIR_NAMES
from app.toolchains.registry import BUILTIN_LANGUAGES

MAX_SCAN_FILES = 5000
MAX_SCAN_DEPTH = 4


@dataclass(slots=True)
class DetectedLanguage:
    id: str
    name: str
    monaco_language: str
    manifests: list[str] = field(default_factory=list)
    file_count: int = 0
    tools: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _ScanResult:
    extension_counts: Counter[str] = field(default_factory=Counter)
    manifest_hits: Counter[str] = field(default_factory=Counter)


def _scan(root: Path) -> _ScanResult:
    result = _ScanResult()
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth >= MAX_SCAN_DEPTH:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIR_NAMES]
        for name in filenames:
            scanned += 1
            if scanned > MAX_SCAN_FILES:
                return result
            ext = os.path.splitext(name)[1].lower()
            if ext:
                result.extension_counts[ext] += 1
            for lang in BUILTIN_LANGUAGES.values():
                for manifest in lang.manifests:
                    if "*" in manifest:
                        if fnmatch.fnmatch(name, manifest):
                            result.manifest_hits[manifest] += 1
                    elif name == manifest:
                        result.manifest_hits[manifest] += 1
    return result


def detect_languages(root: Path) -> list[DetectedLanguage]:
    scan = _scan(root)
    detected: list[DetectedLanguage] = []
    for lang in BUILTIN_LANGUAGES.values():
        manifests = [m for m in lang.manifests if scan.manifest_hits.get(m, 0) > 0]
        file_count = sum(scan.extension_counts.get(ext, 0) for ext in lang.extensions)
        if manifests or file_count > 0:
            detected.append(
                DetectedLanguage(
                    id=lang.id,
                    name=lang.name,
                    monaco_language=lang.monaco_language,
                    manifests=manifests,
                    file_count=file_count,
                    tools=sorted(lang.tools),
                )
            )
    detected.sort(key=lambda d: (len(d.manifests) == 0, -d.file_count, d.id))
    return detected

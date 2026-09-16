"""Credential scanner (Phase 8 security gate): bounded, dependency-free secret detection.

The scanner looks for high-confidence credential patterns in text and project
files. Findings are advisory evidence for the security validation gate — the
gate fails on findings, and a human (HITL) can acknowledge false positives via
the normal approval flow. Redacted snippets only: secrets must never be copied
into logs, events or model context (SEC-003).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

MAX_SCAN_BYTES = 512_000
MAX_FILES = 2000
SNIPPET_CONTEXT = 24  # chars of context around a finding, redacted

# High-confidence patterns; each entry: (kind, compiled regex).
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_secret_key_context", re.compile(r"(?i)aws.{0,20}['\"][A-Za-z0-9/+=]{40}['\"]")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("openai_style_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    (
        "generic_api_key_assignment",
        re.compile(
            r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*['\"][^'\"]{8,}['\"]"
        ),
    ),
    ("bearer_token_literal", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{24,}")),
)

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "data",
    ".harness",
    "dist",
    "build",
}
BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".whl",
    ".exe",
    ".dll",
    ".so",
    ".pyc",
}


@dataclass(frozen=True, slots=True)
class SecretFinding:
    kind: str
    line: int
    snippet: str  # redacted — the match itself is never included

    def as_dict(self) -> dict[str, str | int]:
        return {"kind": self.kind, "line": self.line, "snippet": self.snippet}


class ScanSummary(TypedDict):
    """Gate-ready summary of a directory scan."""

    scanned_files: int
    finding_count: int
    findings: list[dict[str, str | int]]
    skipped: list[str]


def redact(line: str, start: int, end: int) -> str:
    """Context around a match with the match itself replaced by a mask."""
    prefix = line[max(0, start - SNIPPET_CONTEXT) : start]
    suffix = line[end : end + SNIPPET_CONTEXT]
    return f"{prefix}«redacted»{suffix}".strip()


def scan_text(text: str) -> list[SecretFinding]:
    findings: list[SecretFinding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in _PATTERNS:
            match = pattern.search(line)
            if match:
                findings.append(
                    SecretFinding(
                        kind=kind, line=lineno, snippet=redact(line, match.start(), match.end())
                    )
                )
    return findings


def scan_paths(root: Path, *, extra_excludes: set[str] | None = None) -> ScanSummary:
    """Scan a directory tree (bounded). Returns a gate-ready summary."""
    excludes = SKIP_DIRS | (extra_excludes or set())
    scanned = 0
    findings: list[dict[str, str | int]] = []
    skipped: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or scanned >= MAX_FILES:
            continue
        relative = path.relative_to(root)
        if any(part in excludes for part in relative.parts):
            continue
        if path.suffix.lower() in BINARY_EXTENSIONS:
            skipped.append(str(relative))
            continue
        try:
            if path.stat().st_size > MAX_SCAN_BYTES:
                skipped.append(str(relative))
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped.append(str(relative))
            continue
        scanned += 1
        for finding in scan_text(text):
            findings.append({"file": str(relative), **finding.as_dict()})
    return {
        "scanned_files": scanned,
        "finding_count": len(findings),
        "findings": findings,
        "skipped": skipped[:50],
    }

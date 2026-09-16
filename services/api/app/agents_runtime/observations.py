"""RTK-style observation compression (FR-023, spec §15).

Raw tool output is never injected into model context. The normalizer produces a
compact observation: status, exit code, bounded summary, relevant error lines and
a reference to the stored evidence artifact (PERF-004).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SUMMARY_MAX_CHARS = 400
RELEVANT_ERROR_LINES = 8
LINE_MAX_CHARS = 240

_ERROR_PATTERNS = re.compile(
    r"(error|failed|failure|exception|traceback|fatal|denied|cannot|not found|timeout)",
    flags=re.IGNORECASE,
)


@dataclass(slots=True)
class Observation:
    tool: str
    status: str  # success | failed | timeout
    exit_code: int | None
    summary: str
    relevant_errors: list[str] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    duration_ms: int = 0
    security_flags: list[str] = field(default_factory=list)  # SEC-006/007

    def to_json(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "status": self.status,
            "exit_code": self.exit_code,
            "summary": self.summary,
            "relevant_errors": self.relevant_errors,
            "artifact_ids": self.artifact_ids,
            "duration_ms": self.duration_ms,
            "security_flags": self.security_flags,
        }


def _relevant_errors(stderr: str, stdout: str) -> list[str]:
    lines = (stderr + "\n" + stdout).splitlines()
    hits = [ln.strip() for ln in lines if _ERROR_PATTERNS.search(ln)]
    if not hits and stderr.strip():
        hits = [ln.strip() for ln in stderr.splitlines() if ln.strip()]
    trimmed = []
    for line in hits[-RELEVANT_ERROR_LINES:]:
        trimmed.append(line[:LINE_MAX_CHARS])
    return trimmed


def _summary(stdout: str) -> str:
    text = stdout.strip() or "(no stdout)"
    if len(text) <= SUMMARY_MAX_CHARS:
        return text
    return text[: SUMMARY_MAX_CHARS - 3] + "..."


def normalize_tool_observation(
    *,
    tool: str,
    exit_code: int | None,
    timed_out: bool,
    stdout: str,
    stderr: str,
    duration_ms: int,
    artifact_ids: list[str] | None = None,
) -> Observation:
    if timed_out:
        status = "timeout"
    elif exit_code == 0:
        status = "success"
    else:
        status = "failed"
    from app.services.quality.security import (
        prompt_injection_scan,  # noqa: PLC0415 — no cycle at load
    )

    return Observation(
        tool=tool,
        status=status,
        exit_code=exit_code,
        summary=_summary(stdout),
        relevant_errors=_relevant_errors(stderr, stdout),
        artifact_ids=list(artifact_ids or []),
        duration_ms=duration_ms,
        security_flags=prompt_injection_scan(f"{stdout}\n{stderr}"),
    )


def observation_prompt_text(observation: Observation) -> str:
    """Compact single-block text for model context — never the raw log."""
    import json  # noqa: PLC0415 — local, tiny

    return json.dumps(observation.to_json())

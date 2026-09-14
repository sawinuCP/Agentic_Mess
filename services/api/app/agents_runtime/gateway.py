"""Tool gateway: policy enforcement + normalized observations (SEC-001/002, FR-023).

Every agent tool invocation passes through here — never around it. Policy:
task allowlist, global deny patterns, approval-required patterns (surfaced to the
HITL gate), and per-call timeouts. Raw output goes to artifacts; the model sees
only the compressed observation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.agents_runtime.observations import Observation, normalize_tool_observation
from app.core.errors import DomainError
from app.runtime.runner import run_process

_EVIDENCE_MIN_BYTES = 512

EvidenceStore = Callable[[str, bytes], Awaitable[str | None]]

# Commands always denied for agent execution, regardless of allowlist.
GLOBAL_DENY_PATTERNS: tuple[str, ...] = (
    "rm -rf /",
    "format c:",
    "shutdown",
    "reg delete",
    "vssadmin delete",
    "fork bomb",
)

# Commands that require HITL approval before execution (SEC-004).
APPROVAL_PATTERNS: tuple[str, ...] = (
    "drop table",
    "delete from",
    "git push --force",
    "docker rm",
    "npm publish",
)


class PolicyViolation(Exception):
    """Raised when a tool invocation violates policy; fail-closed."""

    def __init__(self, reason: str, *, needs_approval: bool = False) -> None:
        super().__init__(reason)
        self.reason = reason
        self.needs_approval = needs_approval
        self.message = reason


@dataclass(slots=True)
class ToolInvocation:
    tool: str
    command: list[str]
    cwd: str
    timeout_seconds: float = 120.0
    allowed_tools: frozenset[str] = frozenset()
    pre_approved: bool = False  # HITL gate approved this exact command (SEC-004)


@dataclass(slots=True)
class RawOutcome:
    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str
    duration_ms: int
    artifact_ids: list[str] = field(default_factory=list)


def check_policy(invocation: ToolInvocation, command: list[str]) -> None:
    """Validate allowlist + deny/approval patterns. Raises PolicyViolation (fail-closed)."""
    joined = " ".join(command).lower()
    for pattern in GLOBAL_DENY_PATTERNS:
        if pattern in joined:
            raise PolicyViolation(f"Command denied by global policy: matches '{pattern}'")
    if invocation.allowed_tools and invocation.tool not in invocation.allowed_tools:
        raise PolicyViolation(
            f"Tool '{invocation.tool}' is not in the task allowlist "
            f"({sorted(invocation.allowed_tools)})"
        )
    for pattern in APPROVAL_PATTERNS:
        if pattern in joined and not invocation.pre_approved:
            raise PolicyViolation(
                f"Command requires human approval: matches '{pattern}'", needs_approval=True
            )


def normalize_outcome(invocation: ToolInvocation, outcome: RawOutcome) -> Observation:
    """Compress a raw execution outcome into a model-safe observation (FR-023)."""
    return normalize_tool_observation(
        tool=invocation.tool,
        exit_code=outcome.exit_code,
        timed_out=outcome.timed_out,
        stdout=outcome.stdout,
        stderr=outcome.stderr,
        duration_ms=outcome.duration_ms,
        artifact_ids=outcome.artifact_ids,
    )


async def invoke(
    invocation: ToolInvocation,
    command: list[str],
    *,
    store_evidence: EvidenceStore,
) -> Observation:
    """Policy-checked, timed execution returning a compressed observation.

    ``store_evidence`` persists raw output as an artifact and returns its id
    (wired to the artifact service by the caller).
    """
    check_policy(invocation, command)
    if not command:
        raise DomainError("Empty tool command", 422)
    result = await run_process(
        [str(arg) for arg in command],
        invocation.cwd,
        timeout_seconds=invocation.timeout_seconds,
    )
    evidence_ids: list[str] = []
    for name, text in (("stdout.log", result.stdout), ("stderr.log", result.stderr)):
        if len(text.encode("utf-8")) >= _EVIDENCE_MIN_BYTES:
            artifact_id = await store_evidence(name, text.encode("utf-8"))
            if artifact_id:
                evidence_ids.append(artifact_id)
    return normalize_outcome(
        invocation,
        RawOutcome(
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=result.duration_ms,
            artifact_ids=evidence_ids,
        ),
    )

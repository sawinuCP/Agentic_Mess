"""Failure classification + bounded recovery (FR-016, REC-001..003, spec §26).

Recovery rules (spec §26 table), kept machine-checkable:
- Classify a failure detail into one of the eleven spec classes.
- Produce a bounded recovery plan: retries are bounded (REC-002), repeated
  failure escalates to replanning/escalation instead of looping (REC-003), and
  the previous attempt's identity/evidence is always preserved (REC-001 — the
  durable attempt rows are never rewritten).

This module is pure: no I/O, no clock — the workflow decides whether to act.
"""

from __future__ import annotations

import re

FAILURE_CLASSES = (
    "MODEL_FAILURE",
    "TOOL_FAILURE",
    "ENVIRONMENT_FAILURE",
    "CONTEXT_FAILURE",
    "TASK_FAILURE",
    "TIMEOUT",
    "DEPENDENCY_FAILURE",
    "MERGE_CONFLICT",
    "RESOURCE_LIMIT",
    "HITL_TIMEOUT",
    "SECURITY_BLOCK",
)

# Class -> highest-priority regex hints over the failure detail (case-insensitive).
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "SECURITY_BLOCK",
        re.compile(r"security|policy|hitl .*(denied|rejected|timeout)|allowlist|deny", re.I),
    ),
    (
        "RESOURCE_LIMIT",
        re.compile(r"quota|budget|resource limit|too many|exhausted|rate limit", re.I),
    ),
    (
        "MODEL_FAILURE",
        re.compile(r"model|provider|openai|completion|token limit|context length", re.I),
    ),
    (
        "TOOL_FAILURE",
        re.compile(r"toolchain|formatter|linter|tool .* missing|tool .* not found", re.I),
    ),
    (
        "ENVIRONMENT_FAILURE",
        re.compile(r"docker|container|runtime|daemon|no such file|not installed|winpty|pty", re.I),
    ),
    (
        "DEPENDENCY_FAILURE",
        re.compile(
            r"dependenc|upstream|blocked by|merge base|missing module|importerror|modulenotfound",
            re.I,
        ),
    ),
    ("MERGE_CONFLICT", re.compile(r"merge conflict|conflict|both modified|<<<<<<<", re.I)),
    (
        "CONTEXT_FAILURE",
        re.compile(r"context|retrieval|token budget of the prompt|empty context", re.I),
    ),
    ("TIMEOUT", re.compile(r"timed out|timeout after|deadline exceeded", re.I)),
)

# Recovery actions per class (spec §26 "Recovery" column).
_CLASS_ACTIONS: dict[str, str] = {
    "MODEL_FAILURE": "retry_alternate_model",
    "TOOL_FAILURE": "retry_if_safe",
    "ENVIRONMENT_FAILURE": "recreate_runtime",
    "CONTEXT_FAILURE": "rebuild_context",
    "TASK_FAILURE": "retry_then_replan",
    "TIMEOUT": "retry_then_replan",
    "DEPENDENCY_FAILURE": "wait_for_dependency",
    "MERGE_CONFLICT": "create_integration_task",
    "RESOURCE_LIMIT": "throttle_then_retry",
    "HITL_TIMEOUT": "stop",
    "SECURITY_BLOCK": "stop",
}


def classify_failure(detail: str, *, timed_out: bool = False) -> str:
    """Classify a failure detail into a spec §26 class (TASK_FAILURE as fallback)."""
    if timed_out:
        return "TIMEOUT"
    for failure_class, pattern in _PATTERNS:
        if pattern.search(detail or ""):
            return failure_class
    return "TASK_FAILURE"


def recovery_plan(
    failure_class: str,
    attempt_number: int,
    *,
    max_attempts: int = 3,
) -> dict[str, object]:
    """Bounded recovery decision for a classified failure (REC-002/REC-003).

    ``attempt_number`` is 1-based. While attempts remain, retryable classes get
    their class-specific retry action; on the last attempt every class escalates
    to ``escalate_or_replan`` except the hard stops. Non-retryable classes stop
    immediately.
    """
    if failure_class not in _CLASS_ACTIONS:
        failure_class = "TASK_FAILURE"
    action = _CLASS_ACTIONS[failure_class]
    hard_stop = action == "stop"
    attempts_left = max(0, max_attempts - attempt_number)

    if hard_stop or attempts_left == 0:
        return {
            "action": "stop" if hard_stop else "escalate_or_replan",
            "retryable": False,
            "attempts_left": attempts_left,
            "failure_class": failure_class,
        }
    return {
        "action": action,
        "retryable": True,
        "attempts_left": attempts_left,
        "failure_class": failure_class,
    }

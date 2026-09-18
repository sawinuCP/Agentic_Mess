"""Failure classification + bounded recovery (FR-016, REC-001..003, spec §26).

Wave 2: this module is the deterministic POLICY CORE of recovery. The Temporal
task workflow is the authoritative executor: it calls :func:`recovery_decision`
(pure, workflow-deterministic) and executes the decided action through durable
activities. A recovery decision therefore always results in a real bounded
action or an explicit terminal/HITL state (never "advisory").

Recovery rules kept machine-checkable:
- Classify a failure detail into one of the eleven spec classes (plus the two
  policy classes the executor itself emits: BUDGET_EXCEEDED, QUOTA_EXCEEDED).
- Produce a bounded decision: retries are bounded (REC-002), repeated failure
  escalates to replanning instead of looping (REC-003), and the previous
  attempt's identity/evidence is never rewritten (REC-001).
- Non-retryable classes (SECURITY_BLOCK, HITL_TIMEOUT, BUDGET_EXCEEDED) never
  auto-retry — hard policy signals outrank any heuristic.
- Backoff is bounded exponential with deterministic (hash-free) jitter so the
  workflow stays deterministic and the curve is unit-testable.

Action vocabulary: existing names are preserved (retry_if_safe,
retry_alternate_model, recreate_runtime, rebuild_context, retry_then_replan,
wait_for_dependency, create_integration_task, throttle_then_retry,
escalate_or_replan, stop); last-attempt specializations make the remaining
executor actions reachable (escalate_model, replace_agent, spawn_debugger,
request_hitl). See docs/RECOVERY.md for the decision table and executor
semantics.

This module is pure: no I/O, no clock, no RNG.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

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

#: Policy classes emitted by the execution activity itself (cost/slot gates).
#: Distinction (spec §26 + §32): RESOURCE_LIMIT = infrastructure resource
#: exhaustion; BUDGET_EXCEEDED = task token-budget policy; QUOTA_EXCEEDED =
#: per-project concurrency-slot policy.
POLICY_CLASSES = ("BUDGET_EXCEEDED", "QUOTA_EXCEEDED")

#: Classes whose failures must never be retried automatically (spec §26/§31:
#: deterministic, security or cost-policy failures).
NON_RETRYABLE_CLASSES = frozenset({"SECURITY_BLOCK", "HITL_TIMEOUT", "BUDGET_EXCEEDED"})

#: Last-retry escalation for MODEL_FAILURE: spend the final attempt on the
#: configured higher-capability route (registry fallback_role) before the
#: terminal ladder.
_ESCALATED_ACTION = "escalate_model"

#: Every retryable class ends its ladder here (REC-003): a durable replan task
#: with structured evidence plus a terminal failure of the original task.
_LADDER_END = "escalate_or_replan"

#: Last-attempt specializations: when exactly one attempt remains, these classes
#: switch to a structurally different recovery instead of repeating the same
#: action. Every other retryable class repeats its action until the ladder end.
#: (REC-003 still holds: attempts_left == 0 always ends at escalate_or_replan,
#: and non-retryable classes always stop.)
_LAST_ATTEMPT_ACTIONS: dict[str, str] = {
    # Final model attempt spends the configured higher-capability route.
    "MODEL_FAILURE": _ESCALATED_ACTION,
    # Same-agent retries failed: a fresh agent carries the durable context.
    "TOOL_FAILURE": "replace_agent",
    # Task failure resists retries: spawn a debugger with the evidence, then
    # terminate the parent with a reference to it (no dead wait).
    "TASK_FAILURE": "spawn_debugger",
    # Resource exhaustion may need an operator (quota/provisioning decision).
    "RESOURCE_LIMIT": "request_hitl",
}


#: Recovery actions whose cost must be checked against the remaining task
#: budget BEFORE execution (spec §32; prompt §9). Insufficient budget routes
#: the decision through the durable HITL gate instead of executing.
BUDGET_SENSITIVE_ACTIONS = frozenset(
    {
        "retry_alternate_model",
        "escalate_model",
        "replace_agent",
        "spawn_debugger",
        "escalate_or_replan",
    }
)

# Recovery actions per class while attempts remain (spec §26 "Recovery" column;
# names preserved from the pre-Wave-2 policy).
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
    "QUOTA_EXCEEDED": "throttle_then_retry",
    "BUDGET_EXCEEDED": "stop",
    "HITL_TIMEOUT": "stop",
    "SECURITY_BLOCK": "stop",
}


# Class -> highest-priority regex hints over the failure detail (case-insensitive).
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "SECURITY_BLOCK",
        re.compile(
            r"security|policy|capabilit|hitl .*(denied|rejected|timeout)|allowlist|deny", re.I
        ),
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

_DEFAULT_BASE_BACKOFF = 2.0
_DEFAULT_FACTOR = 2.0
_DEFAULT_MAX_BACKOFF = 60.0
_DEFAULT_JITTER_RATIO = 0.25


def classify_failure(detail: str, *, timed_out: bool = False) -> str:
    """Classify a failure detail into a spec §26 class (TASK_FAILURE as fallback)."""
    if timed_out:
        return "TIMEOUT"
    for failure_class, pattern in _PATTERNS:
        if pattern.search(detail or ""):
            return failure_class
    return "TASK_FAILURE"


def is_retryable(failure_class: str) -> bool:
    """True while the class may be retried under policy (hard stops never are)."""
    if failure_class in NON_RETRYABLE_CLASSES:
        return False
    return _CLASS_ACTIONS.get(failure_class, "retry_then_replan") != "stop"


def backoff_seconds(
    attempt: int,
    *,
    base: float = _DEFAULT_BASE_BACKOFF,
    factor: float = _DEFAULT_FACTOR,
    max_delay: float = _DEFAULT_MAX_BACKOFF,
    jitter_ratio: float = _DEFAULT_JITTER_RATIO,
    seed: str = "",
) -> float:
    """Bounded exponential backoff with deterministic jitter (prompt §6).

    ``delay = min(base * factor**(attempt-1), max_delay)`` perturbed by ±
    ``jitter_ratio`` of itself. The jitter derives deterministically from
    ``seed`` (workflow code must never use RNG), so the curve is testable and
    Temporal-replay safe.
    """
    attempt = max(1, attempt)
    delay = min(base * (factor ** (attempt - 1)), max_delay)
    if jitter_ratio <= 0 or not seed:
        return round(delay, 3)
    digest = uuid.uuid5(uuid.NAMESPACE_URL, seed).int
    perturbation = (digest % 2001 - 1000) / 1000.0  # [-1.0, 1.0]
    return round(max(0.0, delay * (1.0 + jitter_ratio * perturbation)), 3)


def _reason_for(action: str, failure_class: str, attempts_left: int) -> str:
    if failure_class in NON_RETRYABLE_CLASSES:
        return f"{failure_class} is non-retryable under policy; terminal failure with evidence"
    if action == "escalate_model":
        return "Repeated model failures; escalating to the configured higher-capability route"
    if action == "replace_agent":
        return "Repeated tool failures with this agent; replacing it with a fresh agent"
    if action == "spawn_debugger":
        return "Task failure resists retries; spawning a debugger with the evidence"
    if action == "request_hitl":
        return "Resource exhaustion may need an operator; requesting human guidance"
    if action == "escalate_or_replan":
        return "Retry budget exhausted; durable replan task created and attempt marked terminal"
    if action == "wait_for_dependency":
        return "Blocked on an unfinished dependency; waiting durably for its completion"
    if action == "create_integration_task":
        return "Merge conflict; integration work delegated to the worktree integration queue"
    if action == "rebuild_context":
        return "Context failure; next attempt runs with a compacted context budget"
    if action == "retry_alternate_model":
        return "Model/provider failure; next attempt routes to the configured alternate model"
    if action == "recreate_runtime":
        return "Environment failure; next attempt runs on a freshly resolved runtime"
    if action == "throttle_then_retry":
        return "Resource/quota pressure; backing off before the next attempt"
    return f"Transient {failure_class}; retrying within the attempt budget ({attempts_left} left)"


def recovery_decision(
    failure_class: str,
    attempt_number: int,
    *,
    max_attempts: int = 3,
    task_id: str = "",
    attempt_id: str = "",
    base_backoff: float = _DEFAULT_BASE_BACKOFF,
    factor: float = _DEFAULT_FACTOR,
    max_backoff: float = _DEFAULT_MAX_BACKOFF,
    jitter_ratio: float = _DEFAULT_JITTER_RATIO,
) -> dict[str, Any]:
    """Deterministic, bounded recovery decision for one failure (REC-002/003).

    The Temporal task workflow executes the returned ``action`` through durable
    activities; ``recovery_id`` derives deterministically from the task and
    attempt so activity replays deduplicate naturally.
    """
    if failure_class not in _CLASS_ACTIONS:
        failure_class = "TASK_FAILURE"
    attempt_number = max(1, attempt_number)
    attempts_left = max(0, max_attempts - attempt_number)
    retryable = is_retryable(failure_class)

    if not retryable:
        action = _CLASS_ACTIONS[failure_class]  # hard stop for every non-retryable class
    elif attempts_left == 0:
        action = _LADDER_END
    elif attempts_left == 1 and failure_class in _LAST_ATTEMPT_ACTIONS:
        action = _LAST_ATTEMPT_ACTIONS[failure_class]
    else:
        action = _CLASS_ACTIONS[failure_class]

    parameters: dict[str, Any] = {}
    if action == "rebuild_context":
        parameters["context_budget_scale"] = 0.5
    elif action in ("retry_alternate_model", "escalate_model"):
        parameters["model_route"] = "fallback"
    elif action == "recreate_runtime":
        parameters["runtime_recreate"] = True
    elif action == "create_integration_task":
        parameters["child_kind"] = "integration_task"
    elif action == "spawn_debugger":
        parameters["child_kind"] = "debug"
    elif action == "escalate_or_replan":
        parameters["child_kind"] = "replan"
    elif action == "throttle_then_retry":
        parameters["backoff_multiplier"] = 2.0

    seed = f"{task_id}:{attempt_id}:{failure_class}:{attempt_number}"
    backoff = backoff_seconds(
        attempt_number,
        base=base_backoff,
        factor=factor,
        max_delay=max_backoff,
        jitter_ratio=jitter_ratio,
        seed=seed,
    ) * float(parameters.get("backoff_multiplier", 1.0))

    return {
        "recovery_id": str(uuid.uuid5(uuid.NAMESPACE_URL, seed)),
        "action": action,
        # spawn_debugger always terminates the parent (with a child reference),
        # so it never continues even though the class is retryable.
        "retryable": retryable and action not in (_LADDER_END, "spawn_debugger"),
        "attempts_left": attempts_left,
        "failure_class": failure_class,
        "action_reason": _reason_for(action, failure_class, attempts_left),
        "parameters": parameters,
        "backoff_seconds": round(backoff, 3),
        "budget_sensitive": action in BUDGET_SENSITIVE_ACTIONS,
        "attempt_number": attempt_number,
        "max_attempts": max_attempts,
    }


def recovery_plan(
    failure_class: str,
    attempt_number: int,
    *,
    max_attempts: int = 3,
) -> dict[str, object]:
    """Backward-compatible bounded plan (legacy shape consumed by activities)."""
    decision = recovery_decision(failure_class, attempt_number, max_attempts=max_attempts)
    return {
        "action": decision["action"],
        "retryable": decision["retryable"],
        "attempts_left": decision["attempts_left"],
        "failure_class": decision["failure_class"],
    }

"""Failure classification + bounded recovery units (FR-016, REC-002/003)."""

from __future__ import annotations

import pytest

from app.services.orchestration.recovery import classify_failure, recovery_plan


@pytest.mark.parametrize(
    ("detail", "expected"),
    [
        ("provider openai returned 500 on completion", "MODEL_FAILURE"),
        ("docker daemon not reachable", "ENVIRONMENT_FAILURE"),
        ("ImportError: no module named 'requests'", "DEPENDENCY_FAILURE"),
        ("merge conflict in src/app.py", "MERGE_CONFLICT"),
        ("execution quota exhausted for project", "RESOURCE_LIMIT"),
        ("model budget exhausted (tokens/task)", "RESOURCE_LIMIT"),
        ("command timed out after 120s", "TIMEOUT"),
        ("HITL rejected: allowlist violation", "SECURITY_BLOCK"),
        ("formatter tool not found on PATH", "TOOL_FAILURE"),
        ("payload.command is missing", "TASK_FAILURE"),
        ("exit code 1: 3 tests failed", "TASK_FAILURE"),  # plain command failures stay task-level
    ],
)
def test_classify_failure_maps_spec_classes(detail: str, expected: str) -> None:
    assert classify_failure(detail) == expected


def test_timed_out_flag_wins() -> None:
    assert classify_failure("some odd error", timed_out=True) == "TIMEOUT"


def test_unknown_details_default_to_task_failure() -> None:
    assert classify_failure("something completely unclassifiable") == "TASK_FAILURE"


def test_recovery_plan_is_bounded_and_escalates() -> None:
    first = recovery_plan("TOOL_FAILURE", 1, max_attempts=3)
    assert first["action"] == "retry_if_safe"
    assert first["retryable"] is True
    assert first["attempts_left"] == 2

    last = recovery_plan("TOOL_FAILURE", 3, max_attempts=3)
    assert last["action"] == "escalate_or_replan"
    assert last["retryable"] is False


def test_security_blocks_never_retry() -> None:
    plan = recovery_plan("SECURITY_BLOCK", 1, max_attempts=5)
    assert plan["action"] == "stop"
    assert plan["retryable"] is False


def test_merge_conflicts_become_integration_tasks() -> None:
    assert recovery_plan("MERGE_CONFLICT", 1)["action"] == "create_integration_task"


# --- Wave 2: deterministic decisions (prompt §3/§6/§16) -----------------------

from app.services.orchestration.recovery import (  # noqa: E402
    BUDGET_SENSITIVE_ACTIONS,
    NON_RETRYABLE_CLASSES,
    backoff_seconds,
    recovery_decision,
)


@pytest.mark.parametrize(
    "failure_class",
    ["SECURITY_BLOCK", "HITL_TIMEOUT", "BUDGET_EXCEEDED"],
)
def test_hard_policy_failures_never_retry(failure_class: str) -> None:
    decision = recovery_decision(failure_class, 1, max_attempts=5)
    assert decision["action"] == "stop"
    assert decision["retryable"] is False
    assert decision["budget_sensitive"] is False


def test_tool_failure_ladder_retries_then_replaces_then_replans() -> None:
    first = recovery_decision("TOOL_FAILURE", 1, max_attempts=3)
    assert first["action"] == "retry_if_safe"
    assert first["retryable"] is True
    assert first["budget_sensitive"] is False
    assert first["backoff_seconds"] > 0

    last_retry = recovery_decision("TOOL_FAILURE", 2, max_attempts=3)
    assert last_retry["action"] == "replace_agent"
    assert last_retry["retryable"] is True
    assert last_retry["budget_sensitive"] is True  # a fresh agent costs tokens

    exhausted = recovery_decision("TOOL_FAILURE", 3, max_attempts=3)
    assert exhausted["action"] == "escalate_or_replan"
    assert exhausted["retryable"] is False
    assert exhausted["parameters"]["child_kind"] == "replan"
    assert exhausted["budget_sensitive"] is True  # replanning costs tokens


def test_task_failure_spawns_debugger_on_final_retry() -> None:
    first = recovery_decision("TASK_FAILURE", 1, max_attempts=3)
    assert first["action"] == "retry_then_replan"
    assert first["retryable"] is True

    last_retry = recovery_decision("TASK_FAILURE", 2, max_attempts=3)
    assert last_retry["action"] == "spawn_debugger"
    assert last_retry["parameters"]["child_kind"] == "debug"
    assert last_retry["retryable"] is False  # parent terminates with a child reference
    assert last_retry["budget_sensitive"] is True


def test_resource_limit_requests_hitl_on_final_retry() -> None:
    first = recovery_decision("RESOURCE_LIMIT", 1, max_attempts=3)
    assert first["action"] == "throttle_then_retry"
    assert first["retryable"] is True

    last_retry = recovery_decision("RESOURCE_LIMIT", 2, max_attempts=3)
    assert last_retry["action"] == "request_hitl"
    assert last_retry["retryable"] is True

    exhausted = recovery_decision("RESOURCE_LIMIT", 3, max_attempts=3)
    assert exhausted["action"] == "escalate_or_replan"
    assert exhausted["retryable"] is False


def test_model_failure_escalates_on_the_final_retry() -> None:
    first = recovery_decision("MODEL_FAILURE", 1, max_attempts=3)
    assert first["action"] == "retry_alternate_model"
    assert first["parameters"]["model_route"] == "fallback"

    last_retry = recovery_decision("MODEL_FAILURE", 2, max_attempts=3)
    assert last_retry["action"] == "escalate_model"
    assert last_retry["budget_sensitive"] is True


def test_context_failure_compacts_and_dependency_failure_waits() -> None:
    context = recovery_decision("CONTEXT_FAILURE", 1)
    assert context["action"] == "rebuild_context"
    assert context["parameters"]["context_budget_scale"] == 0.5

    dependency = recovery_decision("DEPENDENCY_FAILURE", 1)
    assert dependency["action"] == "wait_for_dependency"
    assert dependency["budget_sensitive"] is False


def test_quota_failures_throttle_with_doubled_backoff() -> None:
    throttled = recovery_decision("QUOTA_EXCEEDED", 1, max_attempts=3)
    plain = recovery_decision("TOOL_FAILURE", 1, max_attempts=3)
    assert throttled["action"] == "throttle_then_retry"
    assert throttled["backoff_seconds"] >= plain["backoff_seconds"] * 2


def test_unknown_classes_fall_back_to_task_failure() -> None:
    decision = recovery_decision("SOMETHING_NEW", 1, max_attempts=3)
    assert decision["failure_class"] == "TASK_FAILURE"
    assert decision["action"] == "retry_then_replan"


def test_recovery_ids_are_deterministic_and_scoped() -> None:
    one = recovery_decision("TOOL_FAILURE", 1, max_attempts=3, task_id="t1", attempt_id="a1")
    two = recovery_decision("TOOL_FAILURE", 1, max_attempts=3, task_id="t1", attempt_id="a1")
    other = recovery_decision("TOOL_FAILURE", 2, max_attempts=3, task_id="t1", attempt_id="a2")
    assert one["recovery_id"] == two["recovery_id"]
    assert one["recovery_id"] != other["recovery_id"]


def test_backoff_is_bounded_exponential_with_deterministic_jitter() -> None:
    base = backoff_seconds(1, base=2, factor=2, max_delay=60, jitter_ratio=0)
    assert base == 2.0
    assert backoff_seconds(2, base=2, factor=2, max_delay=60, jitter_ratio=0) == 4.0
    assert backoff_seconds(3, base=2, factor=2, max_delay=60, jitter_ratio=0) == 8.0
    assert backoff_seconds(10, base=2, factor=2, max_delay=60, jitter_ratio=0) == 60.0

    seeded = backoff_seconds(1, base=2, factor=2, max_delay=60, jitter_ratio=0.25, seed="s")
    assert 1.5 <= seeded <= 2.5  # bounded jitter
    assert seeded == backoff_seconds(1, base=2, factor=2, max_delay=60, jitter_ratio=0.25, seed="s")


def test_budget_sensitive_action_set_covers_expensive_recoveries() -> None:
    for action in ("retry_alternate_model", "escalate_model", "replace_agent"):
        assert action in BUDGET_SENSITIVE_ACTIONS
    assert "retry_if_safe" not in BUDGET_SENSITIVE_ACTIONS
    assert "stop" not in BUDGET_SENSITIVE_ACTIONS


def test_non_retryable_registry_is_the_policy_source() -> None:
    assert frozenset({"SECURITY_BLOCK", "HITL_TIMEOUT", "BUDGET_EXCEEDED"}) == NON_RETRYABLE_CLASSES

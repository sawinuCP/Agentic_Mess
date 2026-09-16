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

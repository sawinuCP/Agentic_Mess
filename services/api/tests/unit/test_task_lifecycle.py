"""Task lifecycle transitions (G6): lawful moves pass, all else 422s."""

from __future__ import annotations

import pytest

from app.core.errors import DomainError
from app.services.planning.tasks import TASK_TRANSITIONS, assert_task_transition


def test_all_spec_states_have_a_row() -> None:
    assert set(TASK_TRANSITIONS) == {
        "pending",
        "ready",
        "running",
        "blocked",
        "failed",
        "completed",
        "cancelled",
    }
    assert TASK_TRANSITIONS["completed"] == ()
    assert TASK_TRANSITIONS["cancelled"] == ()


def test_happy_path_transitions_are_lawful() -> None:
    for current, target in [
        ("pending", "ready"),
        ("ready", "running"),
        ("running", "blocked"),
        ("blocked", "running"),
        ("running", "completed"),
        ("running", "failed"),
        ("failed", "ready"),  # retry re-enters
        ("failed", "running"),
        ("pending", "cancelled"),
        ("running", "cancelled"),
        ("failed", "cancelled"),
    ]:
        assert_task_transition(current, target)


def test_terminal_and_unknown_transitions_are_rejected() -> None:
    for current, target in [
        ("completed", "running"),
        ("completed", "ready"),
        ("cancelled", "running"),
        ("failed", "completed"),  # must go through execution, not jump
        ("pending", "completed"),
        ("pending", "failed"),
        ("ready", "failed"),
        ("nope", "running"),
        ("running", "nope"),
    ]:
        with pytest.raises(DomainError, match="Invalid task transition"):
            assert_task_transition(current, target)

"""Agent lifecycle state machine (spec §12)."""

from __future__ import annotations

import pytest

from app.agents_runtime import lifecycle


def test_happy_path_transitions_are_valid() -> None:
    for path in (
        ("created", "planning", "running", "verifying", "completed"),
        ("created", "running"),
        ("running", "pause_requested", "paused", "resuming", "running"),
        ("running", "failed", "recovering", "running"),
    ):
        for current, target in zip(path, path[1:], strict=False):
            assert lifecycle.can_transition(current, target)


def test_invalid_transitions_are_rejected() -> None:
    assert not lifecycle.can_transition("completed", "running")  # terminal
    assert not lifecycle.can_transition("created", "completed")  # must run/verify first
    assert not lifecycle.can_transition("paused", "verifying")  # must resume first
    with pytest.raises(lifecycle.InvalidTransition):
        lifecycle.assert_transition("completed", "running")


def test_unknown_states_are_rejected() -> None:
    with pytest.raises(lifecycle.InvalidTransition):
        lifecycle.assert_transition("dreaming", "running")


def test_all_states_have_transition_table() -> None:
    for state in lifecycle.ALL_STATES:
        assert state in lifecycle.TRANSITIONS


def test_next_work_state() -> None:
    assert lifecycle.next_work_state("paused") == "running"
    assert lifecycle.next_work_state("resuming") == "running"
    assert lifecycle.next_work_state("recovering") == "running"
    assert lifecycle.next_work_state("running") == "running"

"""Dynamic spawn policy: bounded recursion + role gating (FR-007, spec §9/§11)."""

from __future__ import annotations

import pytest

from app.agents_runtime.spawn_policy import (
    child_spawn_depth,
    evaluate_spawn,
    may_schedule_depth,
)


def test_spawn_allowed_within_recursion_bound() -> None:
    decision = evaluate_spawn("implementer", 0, max_depth=2)
    assert decision.allowed and decision.child_depth == 1
    assert evaluate_spawn("implementer", 1, max_depth=2).allowed


def test_spawn_denied_at_recursion_bound() -> None:
    decision = evaluate_spawn("implementer", 2, max_depth=2)
    assert not decision.allowed
    assert "maximum" in decision.reason


def test_spawn_denied_for_non_spawning_role() -> None:
    decision = evaluate_spawn("adjudicator", 0, max_depth=3)
    assert not decision.allowed
    assert "spawning role" in decision.reason


def test_negative_max_depth_rejected() -> None:
    with pytest.raises(ValueError):
        evaluate_spawn("planner", 0, max_depth=-1)


def test_child_depth_increments_without_clamping() -> None:
    assert child_spawn_depth({}) == 1
    assert child_spawn_depth({"spawn_depth": 1}) == 2
    # No clamping: depth records reality; the bound is enforced by evaluation.
    assert child_spawn_depth({"spawn_depth": 5}) == 6


def test_may_schedule_depth_matches_bound() -> None:
    assert may_schedule_depth(0, 2)
    assert may_schedule_depth(2, 2)
    assert not may_schedule_depth(3, 2)
    assert not may_schedule_depth(-1, 2)

"""Failure-injection harness: parsing, budgets, and safe defaults."""

from __future__ import annotations

from app.chaos.faults import FaultState
from app.core.config import Settings


def test_disabled_by_default() -> None:
    faults = FaultState.from_settings(Settings())
    assert faults.enabled is False
    assert faults.armed("model_unavailable", "rehearsal") is False
    assert faults.armed("tool_fail", "shell") is False


def test_points_parse_and_gate_on_master_switch() -> None:
    settings = Settings(failure_injection=True, failure_injection_points="model_flaky:2, tool_fail")
    faults = FaultState.from_settings(settings)
    assert faults.enabled is True
    assert faults.points == {"model_flaky": "2", "tool_fail": ""}
    # Master switch off ignores even configured points.
    off = FaultState.from_settings(Settings())
    assert off.armed("tool_fail") is False


def test_flaky_budget_fires_exactly_n_times_then_stops() -> None:
    faults = FaultState(enabled=True, points={"model_flaky": "2"})
    assert [faults.armed("model_flaky", "glm") for _ in range(4)] == [True, True, False, False]


def test_flaky_budgets_are_scoped_per_route() -> None:
    faults = FaultState(enabled=True, points={"model_flaky": "1"})
    assert faults.armed("model_flaky", "primary") is True
    assert faults.armed("model_flaky", "primary") is False
    assert faults.armed("model_flaky", "fallback") is True  # separate budget


def test_bare_points_always_fire_when_enabled() -> None:
    faults = FaultState(enabled=True, points={"tool_fail": ""})
    assert faults.armed("tool_fail") is True
    assert faults.armed("tool_fail") is True


def test_unknown_points_never_fire() -> None:
    faults = FaultState(enabled=True, points={"tool_fail": ""})
    assert faults.armed("model_unavailable") is False

"""Observation normalizer (FR-023) and gateway policy (SEC-001/002)."""

from __future__ import annotations

import pytest

from app.agents_runtime.gateway import (
    PolicyViolation,
    ToolInvocation,
    check_policy,
    normalize_outcome,
)
from app.agents_runtime.observations import normalize_tool_observation


def _invocation(allowed: frozenset[str] = frozenset()) -> ToolInvocation:
    return ToolInvocation(tool="shell", command=["echo", "hi"], cwd=".", allowed_tools=allowed)


def test_normalizer_success_observation_is_compact() -> None:
    observation = normalize_tool_observation(
        tool="pytest",
        exit_code=1,
        timed_out=False,
        stdout="x" * 5000,
        stderr="FAILED tests/test_auth.py::test_login\nshort detail",
        duration_ms=1500,
        artifact_ids=["a-1"],
    )
    data = observation.to_json()
    assert data["tool"] == "pytest"
    assert data["status"] == "failed"
    assert data["exit_code"] == 1
    assert len(data["summary"]) <= 400  # compressed, never the raw 5000 chars
    assert any("test_login" in e for e in data["relevant_errors"])
    assert data["artifact_ids"] == ["a-1"]


def test_normalizer_timeout_status() -> None:
    observation = normalize_tool_observation(
        tool="shell", exit_code=None, timed_out=True, stdout="", stderr="", duration_ms=1
    )
    assert observation.status == "timeout"


def test_gateway_denies_dangerous_commands() -> None:
    with pytest.raises(PolicyViolation) as excinfo:
        check_policy(_invocation(), ["rm", "-rf", "/"])
    assert not excinfo.value.needs_approval


def test_gateway_enforces_task_allowlist() -> None:
    with pytest.raises(PolicyViolation) as excinfo:
        check_policy(_invocation(allowed=frozenset({"format"})), ["python", "evil.py"])
    assert "allowlist" in excinfo.value.message


def test_gateway_flags_commands_needing_approval() -> None:
    with pytest.raises(PolicyViolation) as excinfo:
        check_policy(_invocation(), ["psql", "-c", "DROP TABLE users"])
    assert excinfo.value.needs_approval  # fail-closed: HITL gate required


def test_gateway_permits_normal_commands() -> None:
    check_policy(_invocation(allowed=frozenset({"shell"})), ["pytest", "-q"])


def test_normalize_outcome_bridge() -> None:
    from app.agents_runtime.gateway import RawOutcome

    invocation = _invocation(frozenset({"shell"}))
    observation = normalize_outcome(
        invocation,
        RawOutcome(exit_code=0, timed_out=False, stdout="done", stderr="", duration_ms=10),
    )
    assert observation.status == "success"

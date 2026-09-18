"""Quality gates cannot turn missing evidence or hard failures into success."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.evaluation.scorecard import Check, EvaluationEvidence, evaluate_evidence


def evidence(**overrides: object) -> EvaluationEvidence:
    data: dict[str, object] = {
        "checks": [
            {
                "key": "criterion-1",
                "dimension": "requirement_coverage",
                "passed": True,
                "evidence_refs": ["artifact://validation-1"],
            },
            {
                "key": "tests",
                "dimension": "validation",
                "passed": True,
                "evidence_refs": ["artifact://test-run-1"],
            },
        ],
        "execution_completed": True,
        "security_violation": False,
        "duration_ms": 100,
        "model_calls": 0,
        "cost_usd": 0,
    }
    data.update(overrides)
    return EvaluationEvidence.model_validate(data)


def test_known_budget_failure_outranks_missing_cost() -> None:
    assert evaluate_evidence(evidence(model_calls=1, cost_usd=None)).status == "FAIL"
    assert evaluate_evidence(evidence(model_calls=None, cost_usd=1)).status == "FAIL"


def test_known_pass_and_unmeasured_dimensions() -> None:
    result = evaluate_evidence(evidence())
    assert result.status == "PASS"
    assert result.requirement_coverage == 1
    assert result.dimensions["planning"] == "UNKNOWN"
    assert result.failures == ()


@pytest.mark.parametrize("dimension", ["requirement_coverage", "validation", "security"])
def test_failed_mandatory_check_blocks_completion(dimension: str) -> None:
    result = evaluate_evidence(
        evidence(
            checks=[
                Check(key="failed", dimension=dimension, passed=False),
            ]
        )
    )
    assert result.status == "FAIL"
    assert result.dimensions[dimension] == "FAIL"


def test_claim_without_evidence_cannot_pass() -> None:
    result = evaluate_evidence(
        evidence(
            checks=[
                Check(key="claim", dimension="requirement_coverage", passed=True),
            ]
        )
    )
    assert result.status == "FAIL"
    assert result.requirement_coverage == 0
    assert result.failures == ("claim: UNKNOWN",)


def test_empty_input_cannot_pass() -> None:
    assert evaluate_evidence(EvaluationEvidence()).status == "UNKNOWN"
    assert evaluate_evidence(evidence(checks=[])).status == "UNKNOWN"


@pytest.mark.parametrize(
    "overrides",
    [
        {"security_violation": True},
        {"execution_completed": False},
        {"duration_ms": 60001},
        {"model_calls": 1},
        {"cost_usd": 0.01},
    ],
)
def test_hard_gates(overrides: dict[str, object]) -> None:
    assert evaluate_evidence(evidence(**overrides)).status == "FAIL"


@pytest.mark.parametrize("field", ["security_violation", "model_calls", "cost_usd", "duration_ms"])
def test_missing_telemetry_is_not_zero(field: str) -> None:
    assert evaluate_evidence(evidence(**{field: None})).status == "UNKNOWN"


def test_partial_coverage_does_not_hide_failure() -> None:
    checks = [
        Check(
            key=str(i),
            dimension="requirement_coverage",
            passed=i < 4,
            evidence_refs=("artifact://test",),
        )
        for i in range(5)
    ]
    result = evaluate_evidence(evidence(checks=checks))
    assert result.requirement_coverage == 0.8
    assert result.status == "FAIL"


def test_duplicate_check_rejected() -> None:
    check = Check(key="duplicate", dimension="validation", passed=False)
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate_evidence(evidence(checks=[check, check]))


def test_unsupported_dimension_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported"):
        evaluate_evidence(evidence(checks=[Check(key="x", dimension="quality_score")]))


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
def test_invalid_cost_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        evidence(cost_usd=value)


def test_model_judgment_is_not_an_override() -> None:
    with pytest.raises(ValidationError):
        evidence(model_verdict="PASS")


def test_deterministic_and_json_serializable() -> None:
    first = evaluate_evidence(evidence())
    assert first == evaluate_evidence(evidence())
    assert '"status":"PASS"' in first.model_dump_json()

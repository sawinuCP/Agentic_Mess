"""Comparison gates are interpretable and do not treat missing observations as success."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.evaluation.comparison import compare, repeatability
from app.evaluation.runner import AuditReport, AuditRequest
from app.evaluation.scorecard import evaluate_evidence


def report(passed: bool = True) -> AuditReport:
    request = AuditRequest.model_validate(
        {
            "project_id": str(uuid.uuid4()),
            "definition": {
                "case_id": "c1",
                "case_version": "1",
                "dataset_version": "1",
                "requirement": "a behavior",
                "mandatory_check_keys": ["test"],
            },
            "code_revision": "revision1",
            "dirty_worktree": False,
            "configuration_version": "1",
            "evidence": {
                "checks": [
                    {
                        "key": "test",
                        "dimension": "validation",
                        "passed": passed,
                        "evidence_refs": ["artifact://test"],
                    }
                ],
                "execution_completed": True,
                "security_violation": False,
                "duration_ms": 100,
                "cost_usd": 0,
                "model_calls": 0,
            },
        }
    )
    return AuditReport(
        run_id=uuid.uuid4(),
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        audit_duration_ms=1,
        request=request,
        scorecard=evaluate_evidence(request.evidence),
        artifact_hashes={},
    )


def test_flaky_outcomes() -> None:
    assert repeatability([report(), report(False), report()]) == "FLAKY"
    assert repeatability([report(), report()]) == "PASS"
    assert repeatability([report(False), report(False)]) == "FAIL"


def test_repeatability_needs_multiple_observations() -> None:
    with pytest.raises(ValueError):
        repeatability([report()])


def test_regression_and_improvement() -> None:
    assert compare(report(), report(False))["regressions"]
    assert compare(report(False), report())["improvements"]
    assert compare(report(), report())["status"] == "PASS"


def test_changed_dataset_is_not_comparable() -> None:
    first, second = report(), report()
    second = second.model_copy(
        update={
            "request": second.request.model_copy(
                update={
                    "configuration_version": "changed",
                }
            )
        }
    )
    with pytest.raises(ValueError, match="Cannot compare"):
        compare(first, second)


def test_dirty_revision_cannot_claim_repeatability() -> None:
    first, second = report(), report()
    second = second.model_copy(
        update={
            "request": second.request.model_copy(
                update={
                    "dirty_worktree": True,
                }
            )
        }
    )
    with pytest.raises(ValueError, match="clean code"):
        repeatability([first, second])

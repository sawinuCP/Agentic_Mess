"""Persisted audit evidence must reproduce the scorecard that was issued."""

from __future__ import annotations

from app.evaluation.runner import AuditReport, AuditRequest, run_audit
from app.evaluation.scorecard import evaluate_evidence


def test_saved_audit_reproduces_missing_mandatory_check_failure(project: tuple) -> None:
    _app, client, project_id, _root = project
    request = AuditRequest.model_validate(
        {
            "project_id": project_id,
            "definition": {
                "case_id": "missing-validation",
                "case_version": "1",
                "dataset_version": "audit-regression-v1",
                "requirement": "Completion requires a passing validation record.",
                "mandatory_check_keys": ["required-test"],
            },
            "code_revision": "controlled-fixture",
            "dirty_worktree": False,
            "configuration_version": "1",
            "evidence": {
                "checks": [],
                "execution_completed": True,
                "security_violation": False,
                "duration_ms": 1,
                "model_calls": 0,
                "cost_usd": 0,
            },
        }
    )

    result = run_audit(client, request)
    assert result["status"] == "FAIL"
    response = client.get(f"/api/artifacts/{result['artifact_id']}/content")
    response.raise_for_status()
    saved = AuditReport.model_validate(response.json())

    assert evaluate_evidence(saved.request.evidence) == saved.scorecard
    assert "required-test: FAIL" in saved.scorecard.failures
    assert request.evidence.checks == ()  # Reconciliation must not mutate the caller.

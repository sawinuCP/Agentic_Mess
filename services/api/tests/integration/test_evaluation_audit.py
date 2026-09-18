"""Evidence audit -> authenticated API -> Postgres artifact metadata -> retrieval."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.evaluation.runner import AuditRequest, run_audit
from app.main import create_app


def _request(project_id: str, ref: str, **updates: Any) -> AuditRequest:
    data: dict[str, Any] = {
        "project_id": project_id,
        "definition": {
            "case_id": "audit-fixture",
            "case_version": "1",
            "dataset_version": "audit-v1",
            "requirement": "Validate fixture",
            "mandatory_check_keys": ["test"],
        },
        "code_revision": "test-fixture",
        "dirty_worktree": False,
        "configuration_version": "1",
        "evidence": {
            "checks": [
                {"key": "test", "dimension": "validation", "passed": True, "evidence_refs": [ref]}
            ],
            "execution_completed": True,
            "security_violation": False,
            "model_calls": 0,
            "cost_usd": 0,
            "duration_ms": 1,
        },
    }
    data.update(updates)
    return AuditRequest.model_validate(data)


def test_audit_persists_and_retrieves_scorecard(project: tuple) -> None:
    _app, client, project_id, _root = project
    artifact = client.post(
        f"/api/projects/{project_id}/artifacts",
        files={"file": ("test.txt", b"fixture test passed")},
    )
    artifact.raise_for_status()
    ref = "artifact://" + artifact.json()["id"]
    result = run_audit(client, _request(project_id, ref))
    assert result["status"] == "PASS"
    persisted = client.get(f"/api/artifacts/{result['artifact_id']}/content").json()
    assert persisted["scorecard"]["status"] == "PASS"
    assert persisted["mode"] == "supplied_evidence_audit"
    assert persisted["artifact_hashes"][ref] == artifact.json()["sha256"]
    assert persisted["request"]["definition"]["case_version"] == "1"


def test_audit_missing_declared_check_persists_failure(project: tuple) -> None:
    _app, client, project_id, _root = project
    request = _request(
        project_id,
        "artifact://" + str(uuid.uuid4()),
        evidence={
            "execution_completed": True,
            "security_violation": False,
            "model_calls": 0,
            "cost_usd": 0,
            "duration_ms": 1,
        },
    )
    result = run_audit(client, request)
    assert result["status"] == "FAIL"
    report = client.get(f"/api/artifacts/{result['artifact_id']}/content").json()
    assert "test: FAIL" in report["scorecard"]["failures"]


def test_audit_rejects_cross_project_reference(project: tuple) -> None:
    _app, client, project_id, _root = project
    response = client.post(
        f"/api/projects/{project_id}/artifacts", files={"file": ("evidence.txt", b"evidence")}
    )
    ref = "artifact://" + response.json()["id"]
    with pytest.raises(ValueError, match="another project"):
        run_audit(client, _request(str(uuid.uuid4()), ref))


def test_audit_uses_existing_authentication() -> None:
    app = create_app(
        Settings(
            environment="test",
            api_token="audit-test-token",
            nats_events_enabled=False,
            otel_enabled=False,
        )
    )
    # Authentication rejects before DB dependencies; no infrastructure/startup needed.
    with TestClient(app, raise_server_exceptions=False) as client:
        with pytest.raises(httpx.HTTPStatusError) as error:
            run_audit(client, _request(str(uuid.uuid4()), "artifact://" + str(uuid.uuid4())))
        assert error.value.response.status_code == 401

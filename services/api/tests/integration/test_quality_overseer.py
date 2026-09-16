"""Requirement overseer integration (FR-026/027, AC-011/015): traceability + gates."""

from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.models import Artifact, Task, TaskAttempt


def _requirement_with_criteria(client: TestClient, project_id: str) -> tuple[str, list[str]]:
    created = client.post(
        f"/api/projects/{project_id}/requirements",
        json={
            "title": "Search must work",
            "description": "Users can search the project",
            "priority": "must",
            "criteria": [
                {"description": "search returns matches", "kind": "manual", "mandatory": True},
                {"description": "search is fast", "kind": "manual", "mandatory": False},
            ],
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    return body["id"], [c["id"] for c in body["criteria"]]


def _make_evidence_artifact(app: FastAPI, project_id: str) -> str:
    with app.state.session_factory() as session:
        blob = app.state.artifacts.put(b"test evidence output")
        artifact = Artifact(
            project_id=uuid.UUID(project_id),
            name="evidence",
            kind="raw_output",
            mime="text/plain",
            size=blob.size,
            sha256=blob.sha256,
            storage_path=blob.storage_path,
        )
        session.add(artifact)
        session.commit()
        return str(artifact.id)


def test_completion_blocked_until_evidence_backed(
    app: FastAPI, project: tuple, tmp_path: object
) -> None:
    _app, client, project_id, _tmp = project
    requirement_id, criteria = _requirement_with_criteria(client, project_id)

    # 1. Unimplemented must-requirement blocks completion.
    blocked = client.post(f"/api/projects/{project_id}/oversight/completion")
    assert blocked.status_code == 409
    assert any("unimplemented" in b for b in blocked.json()["report"]["blockers"])

    # 2. With tasks but unverified criteria: still blocked.
    planned = client.post(
        f"/api/requirements/{requirement_id}/plans",
        json={"tasks": [{"title": "Implement search", "request": "add search"}]},
    )
    assert planned.status_code == 201, planned.text
    blocked = client.post(f"/api/projects/{project_id}/oversight/completion")
    assert blocked.status_code == 409
    assert any("is unknown" in b for b in blocked.json()["report"]["blockers"])

    # 3. Verification without evidence is rejected — the gate cannot be gamed (FR-026).
    no_evidence = client.post(
        f"/api/requirements/{requirement_id}/criteria/{criteria[0]}/verify",
        json={"evidence_artifact_id": str(uuid.uuid4())},
    )
    assert no_evidence.status_code == 404

    # 4. Evidence-backed verification flips the criterion and unblocks completion.
    artifact_id = _make_evidence_artifact(_app, project_id)
    verified = client.post(
        f"/api/requirements/{requirement_id}/criteria/{criteria[0]}/verify",
        json={"evidence_artifact_id": artifact_id, "detail": {"test": "search_spec"}},
    )
    assert verified.status_code == 200
    assert verified.json()["state"] == "verified"

    completed = client.post(f"/api/projects/{project_id}/oversight/completion")
    assert completed.status_code == 200, completed.text
    assert completed.json()["completion_allowed"] is True
    assert completed.json()["artifact_id"]  # FR-027 durable report

    trace = client.get(f"/api/projects/{project_id}/oversight/traceability")
    assert trace.json()["coverage"]["verified"] == 1
    (entry,) = trace.json()["requirements"]
    assert entry["status"] == "VERIFIED"
    assert artifact_id in entry["validation_evidence_artifact_ids"]


def test_scope_drift_creates_warning_not_blocker(app: FastAPI, project: tuple) -> None:
    _app, client, project_id, _tmp = project
    with app.state.session_factory() as session:
        session.add(
            Task(
                project_id=uuid.UUID(project_id),
                title="Out-of-band task",
                request="appeared from nowhere",
            )
        )
        session.commit()

    report = client.post(f"/api/projects/{project_id}/oversight/completion").json()["report"]
    assert report["scope_drift"] is True
    assert report["orphan_task_ids"]
    assert any(
        "scope drift" in warning or "requirement linkage" in warning
        for warning in report["warnings"]
    )


def test_task_completion_gate_requires_evidence(app: FastAPI, project: tuple) -> None:
    _app, client, project_id, _tmp = project
    requirement_id, _criteria = _requirement_with_criteria(client, project_id)
    planned = client.post(
        f"/api/requirements/{requirement_id}/plans",
        json={"tasks": [{"title": "T1", "request": "r1"}]},
    )
    task_id = str(planned.json()["task_ids"][0])

    # No evidence yet -> blocked with the FR-026 message.
    gate = client.post(f"/api/tasks/{task_id}/completion-gate")
    assert gate.status_code == 409
    assert any("FR-026" in b for b in gate.json()["report"]["blockers"])

    # A successful attempt with evidence satisfies the gate.
    with app.state.session_factory() as session:
        session.add(
            TaskAttempt(
                task_id=uuid.UUID(task_id),
                attempt_number=1,
                outcome="success",
                evidence_artifact_ids=[_make_evidence_artifact(app, project_id)],
            )
        )
        session.commit()
    gate = client.post(f"/api/tasks/{task_id}/completion-gate")
    assert gate.status_code == 200
    assert gate.json()["completion_allowed"] is True

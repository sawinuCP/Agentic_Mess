"""Quality gates integration (FR-026, AC-005): security scan + task gate via API."""

from __future__ import annotations

import uuid

from fastapi import FastAPI

from app.db.models import Artifact, Task, TaskAttempt


def _make_artifact(app: FastAPI, project_id: str, content: bytes) -> str:
    with app.state.session_factory() as session:
        blob = app.state.artifacts.put(content)
        artifact = Artifact(
            project_id=uuid.UUID(project_id),
            name="gate-evidence",
            kind="raw_output",
            mime="text/plain",
            size=blob.size,
            sha256=blob.sha256,
            storage_path=blob.storage_path,
        )
        session.add(artifact)
        session.commit()
        return str(artifact.id)


def test_security_scan_fails_on_planted_secret_and_passes_when_clean(
    app: FastAPI, project: tuple
) -> None:
    _app, client, project_id, tmp_path = project
    (tmp_path / "settings.py").write_text(
        "AWS_ACCESS_KEY_ID = 'AKIAIOSFODNN7EXAMPLE'\n", encoding="utf-8"
    )

    failed = client.post(f"/api/projects/{project_id}/quality/security-scan", json={})
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    assert failed.json()["findings"][0]["kind"] == "aws_access_key"
    assert "AKIA" not in failed.json()["findings"][0]["snippet"]  # redacted

    (tmp_path / "settings.py").write_text("x = 1\n", encoding="utf-8")
    passed = client.post(f"/api/projects/{project_id}/quality/security-scan", json={})
    assert passed.json()["status"] == "passed"
    assert passed.json()["validation_id"]


def test_task_gate_blocked_by_failed_security_scan(app: FastAPI, project: tuple) -> None:
    _app, client, project_id, _tmp = project
    requirement = client.post(
        f"/api/projects/{project_id}/requirements",
        json={
            "title": "R",
            "description": "D",
            "priority": "must",
            "criteria": [{"description": "criterion", "kind": "manual"}],
        },
    ).json()
    planned = client.post(
        f"/api/requirements/{requirement['id']}/plans",
        json={"tasks": [{"title": "T", "request": "R"}]},
    ).json()
    task_id = str(planned["task_ids"][0])

    # Failed security validation on the task -> blocker even with evidence.
    client.post(f"/api/projects/{project_id}/quality/security-scan", json={"task_id": task_id})
    evidence_id = _make_artifact(_app, project_id, b"evidence")
    with _app.state.session_factory() as session:
        session.add(
            TaskAttempt(
                task_id=uuid.UUID(task_id),
                attempt_number=1,
                outcome="success",
                evidence_artifact_ids=[evidence_id],
            )
        )
        session.commit()

    gate = client.post(f"/api/tasks/{task_id}/completion-gate")
    assert gate.status_code == 200  # scan passed after cleanup; evidence present

    # Now plant a failed security validation directly and confirm the blocker.
    with _app.state.session_factory() as session:
        task = session.get(Task, uuid.UUID(task_id))
        assert task is not None
        from app.db.models import Validation  # noqa: PLC0415

        session.add(
            Validation(
                project_id=uuid.UUID(project_id),
                task_id=task.id,
                kind="security",
                status="failed",
                detail={"reason": "planted"},
            )
        )
        session.commit()
    gate = client.post(f"/api/tasks/{task_id}/completion-gate")
    assert gate.status_code == 409
    assert any("security" in blocker for blocker in gate.json()["report"]["blockers"])

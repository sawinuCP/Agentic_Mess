"""Hardening integration (Phase 10): restart recovery, diagnostics, portability."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.models import Artifact, TaskAttempt
from app.main import create_app

pytestmark = pytest.mark.integration


def _seed_project(app: FastAPI, tmp_path: Path) -> tuple[str, str]:
    """Create a project with requirement/plan/task/attempt/artifact; returns (project, root)."""
    root = tmp_path / "restart-src"
    root.mkdir(exist_ok=True)
    with TestClient(app) as client:
        project_id = client.post("/api/projects/open", json={"root_path": str(root)}).json()["id"]
        requirement = client.post(
            f"/api/projects/{project_id}/requirements",
            json={
                "title": "Restart proof",
                "description": "State survives restarts",
                "priority": "must",
                "criteria": [{"description": "state readable", "kind": "manual"}],
            },
        ).json()
        planned = client.post(
            f"/api/requirements/{requirement['id']}/plans",
            json={"tasks": [{"title": "T", "request": "R"}]},
        ).json()
        task_id = planned["task_ids"][0]
        with app.state.session_factory() as session:
            blob = app.state.artifacts.put(b"restart evidence")
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
            session.flush()
            session.add(
                TaskAttempt(
                    task_id=uuid.UUID(str(task_id)),
                    attempt_number=1,
                    outcome="success",
                    evidence_artifact_ids=[str(artifact.id)],
                )
            )
            session.commit()
        return project_id, str(root)


def test_redis_failure_degrades_health_without_touching_durable_paths(
    project: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Redis carries no durable or leased workload (leases are PostgreSQL):
    with Redis dead, readiness reports it, but durable reads keep serving."""
    app, client, project_id, _tmp = project
    monkeypatch.setattr(app.state.settings, "redis_url", "redis://127.0.0.1:9/0")
    monkeypatch.setattr(app.state.settings, "require_redis", True)
    readiness = client.get("/readyz")
    assert readiness.status_code == 503
    assert readiness.json()["checks"]["redis"]["status"] == "down"
    # Durable paths are unaffected by the Redis outage.
    assert client.get("/healthz").status_code == 200
    listed = client.get(f"/api/projects/{project_id}/tasks?limit=5")
    assert listed.status_code == 200
    monkeypatch.setattr(app.state.settings, "require_redis", False)
    assert client.get("/readyz").status_code == 200  # informational only now


def test_durable_state_survives_an_application_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-016/PERF-005: a second app instance on the same DB sees everything."""
    monkeypatch.setenv("HARNESS_TEMPORAL_ENABLED", "false")
    first = create_app(Settings(environment="test", readiness_timeout_seconds=2.0))
    project_id, root = _seed_project(first, tmp_path)

    # "Restart": a brand-new app + engine on the same durable database.
    second = create_app(Settings(environment="test", readiness_timeout_seconds=2.0))
    with TestClient(second) as client:
        # Idempotent re-open returns the same durable project (PERF-005).
        reopened = client.post("/api/projects/open", json={"root_path": root}).json()
        assert reopened["id"] == project_id

        # Requirements/tasks/attempts/events all readable from the fresh engine.
        requirements = client.get(f"/api/projects/{project_id}/requirements").json()
        assert len(requirements) == 1
        tasks = client.get(f"/api/projects/{project_id}/tasks").json()
        assert len(tasks) == 1
        attempts = tasks[0]["attempts"]
        assert attempts and attempts[0]["outcome"] == "success"

        # Artifact content is content-addressed and still readable.
        artifact_id = attempts[0]["evidence_artifact_ids"][0]
        content = client.get(f"/api/artifacts/{artifact_id}/content")
        assert content.status_code == 200
        assert content.content == b"restart evidence"

        # Events survived too.
        events = client.get("/api/events", params={"project_id": project_id}).json()
        assert any(e["event_type"] == "REQUIREMENT_CREATED" for e in events)


def test_diagnostics_reports_components_fail_soft(tmp_path: Path) -> None:
    app = create_app(Settings(environment="test", readiness_timeout_seconds=1.0))
    with TestClient(app) as client:
        report = client.get("/api/diagnostics").json()

    assert report["app"]["version"]
    assert report["app"]["environment"] == "test"
    assert "uptime_seconds" in report["app"]
    # Postgres is up in the integration environment; alembic head is a string.
    assert report["database"]["status"] == "ok"
    assert (
        isinstance(report["database"]["alembic_head"], str) and report["database"]["alembic_head"]
    )
    assert report["counts"]["projects"] >= 0
    # Fail-soft: every probe answers ok or down with detail — never a 500.
    for component in ("redis", "nats", "artifact_store", "temp_dir"):
        assert report[component]["status"] in ("ok", "down")
    assert report["config"]["runtime_backend"] in ("local", "docker")


def test_export_import_round_trip_preserves_durable_state(tmp_path: Path) -> None:
    first = create_app(Settings(environment="test", readiness_timeout_seconds=2.0))
    source_root = tmp_path / "export-src"
    source_root.mkdir()
    with TestClient(first) as client:
        project_id = client.post("/api/projects/open", json={"root_path": str(source_root)}).json()[
            "id"
        ]
        client.post(
            f"/api/projects/{project_id}/requirements",
            json={
                "title": "Portable",
                "description": "Survives export/import",
                "priority": "must",
                "criteria": [{"description": "round trips", "kind": "manual"}],
            },
        )
        requirement_id = client.get(f"/api/projects/{project_id}/requirements").json()[0]["id"]
        client.post(
            f"/api/requirements/{requirement_id}/plans",
            json={"tasks": [{"title": "Carry me", "request": "R"}]},
        )
        evidence = client.post(
            f"/api/projects/{project_id}/artifacts",
            files={"file": ("evidence.txt", b"portable bytes")},
        )
        assert evidence.status_code == 201

        bundle_response = client.get(f"/api/projects/{project_id}/export")
        assert bundle_response.status_code == 200
        bundle = bundle_response.json()
        assert bundle["bundle_version"] == 1

    # Import into a brand-new app + fresh workspace root.
    second = create_app(Settings(environment="test", readiness_timeout_seconds=2.0))
    import_root = tmp_path / "import-src"
    import_root.mkdir()
    with TestClient(second) as client:
        imported = client.post(
            "/api/projects/import",
            json={
                "bundle": bundle,
                "root_path": str(import_root),
                "name": f"round-trip-{uuid.uuid4().hex[:8]}",
            },
        )
        assert imported.status_code == 200, imported.text
        summary = imported.json()
        new_project_id = summary["project_id"]
        assert summary["requirements"] == 1
        assert summary["tasks"] == 1
        assert summary["artifacts_restored"] == 1

        requirements = client.get(f"/api/projects/{new_project_id}/requirements").json()
        assert requirements[0]["title"] == "Portable"
        tasks = client.get(f"/api/projects/{new_project_id}/tasks").json()
        assert tasks[0]["title"] == "Carry me"

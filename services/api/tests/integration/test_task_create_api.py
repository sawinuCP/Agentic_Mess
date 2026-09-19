"""Human task-creation endpoint against live PostgreSQL (integration).

Covers: minimal creation (201, pending, listed), requirement/dependency
linking, unknown and foreign-project dependency rejection, empty-title
rejection, and the TASK_CREATED event record. Mirrors the conventions of
test_durable_core_api.py.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

REQUIREMENT_BODY = {
    "title": "Search feature",
    "description": "Users must be able to search indexed symbols.",
    "desired_outcome": "Working symbol search with tests",
    "priority": "must",
    "criteria": [
        {"description": "Symbol lookup returns ranked results", "kind": "automated_test"},
    ],
}


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _open_project(client: TestClient, root: Path) -> str:
    response = client.post("/api/projects/open", json={"root_path": str(root)})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_create_minimal_task(client: TestClient, repo_root: Path) -> None:
    with client:
        project_id = _open_project(client, repo_root)
        created = client.post(f"/api/projects/{project_id}/tasks", json={"title": "Write docs"})
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["title"] == "Write docs"
        assert body["status"] == "pending"
        assert body["depends_on"] == []
        assert body["attempts"] == []

        listed = client.get(f"/api/projects/{project_id}/tasks").json()
        assert body["id"] in [t["id"] for t in listed]

        events = client.get(f"/api/events?project_id={project_id}&limit=50").json()
        created_events = [e for e in events if e["event_type"] == "TASK_CREATED"]
        assert len(created_events) == 1
        assert created_events[0]["task_id"] == body["id"]


def test_create_task_accepts_executable_payload(client: TestClient, repo_root: Path) -> None:
    with client:
        project_id = _open_project(client, repo_root)
        created = client.post(
            f"/api/projects/{project_id}/tasks",
            json={
                "title": "Run the probe",
                "payload": {"command": ["python", "probe.py"], "timeout_seconds": 60},
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["payload"]["command"] == ["python", "probe.py"]


def test_create_task_rejects_malformed_payload(client: TestClient, repo_root: Path) -> None:
    with client:
        project_id = _open_project(client, repo_root)
        for bad in (
            {"command": "not-a-list"},
            {"command": []},
            {"command": [1, 2]},
            {"timeout_seconds": 0},
            {"timeout_seconds": 99999},
        ):
            response = client.post(
                f"/api/projects/{project_id}/tasks",
                json={"title": "Bad payload", "payload": bad},
            )
            assert response.status_code == 422, bad


def test_create_linked_task(client: TestClient, repo_root: Path) -> None:
    with client:
        project_id = _open_project(client, repo_root)
        requirement = client.post(f"/api/projects/{project_id}/requirements", json=REQUIREMENT_BODY)
        assert requirement.status_code == 201, requirement.text
        requirement_id = requirement.json()["id"]

        first = client.post(
            f"/api/projects/{project_id}/tasks", json={"title": "Index symbols"}
        ).json()
        second = client.post(
            f"/api/projects/{project_id}/tasks",
            json={
                "title": "Search UI",
                "request": "Add the palette command",
                "requirement_id": requirement_id,
                "priority": 2,
                "depends_on": [first["id"]],
            },
        )
        assert second.status_code == 201, second.text
        body = second.json()
        assert body["requirement_id"] == requirement_id
        assert body["priority"] == 2
        assert body["depends_on"] == [first["id"]]


def test_create_rejects_bad_links(client: TestClient, repo_root: Path) -> None:
    import uuid

    with client:
        project_id = _open_project(client, repo_root)
        other_root = repo_root / "other"
        other_root.mkdir(exist_ok=True)
        other_id = _open_project(client, other_root)
        foreign = client.post(f"/api/projects/{other_id}/tasks", json={"title": "Foreign"}).json()

        unknown = client.post(
            f"/api/projects/{project_id}/tasks",
            json={"title": "Bad dep", "depends_on": [str(uuid.uuid4())]},
        )
        assert unknown.status_code == 422, unknown.text

        cross = client.post(
            f"/api/projects/{project_id}/tasks",
            json={"title": "Cross-project dep", "depends_on": [foreign["id"]]},
        )
        assert cross.status_code == 422, cross.text

        missing_requirement = client.post(
            f"/api/projects/{project_id}/tasks",
            json={"title": "Bad req", "requirement_id": str(uuid.uuid4())},
        )
        assert missing_requirement.status_code == 404, missing_requirement.text

        empty = client.post(f"/api/projects/{project_id}/tasks", json={"title": ""})
        assert empty.status_code == 422, empty.text

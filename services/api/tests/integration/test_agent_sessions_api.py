"""Agent session-history endpoint against live PostgreSQL (integration).

Covers: empty history for a fresh agent, session listing newest-first with
finished_at distinguishing ended sessions, unknown-agent 404, and the
read-only contract (listing never mutates agent state).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _open_project(client: TestClient, root: Path) -> str:
    response = client.post("/api/projects/open", json={"root_path": str(root)})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _spawn(client: TestClient, project_id: str) -> str:
    response = client.post(
        f"/api/projects/{project_id}/agents",
        json={"name": "worker-1", "role": "worker"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_session_history_flow(client: TestClient, repo_root: Path) -> None:
    with client:
        project_id = _open_project(client, repo_root)
        agent_id = _spawn(client, project_id)

        assert client.get(f"/api/agents/{agent_id}/sessions").json() == []

        first = client.post(f"/api/agents/{agent_id}/sessions")
        assert first.status_code == 201, first.text
        first_id = first.json()["id"]

        second = client.post(f"/api/agents/{agent_id}/sessions")
        assert second.status_code == 201, second.text

        history = client.get(f"/api/agents/{agent_id}/sessions").json()
        assert [s["id"] for s in history] == [second.json()["id"], first_id]
        assert all(s["runtime"] for s in history)
        assert all(s["status"] == "running" for s in history)
        assert all(s["finished_at"] is None for s in history)

        ended = client.post(f"/api/sessions/{first_id}/end")
        assert ended.status_code == 200, ended.text
        assert ended.json()["status"] == "ended"
        assert ended.json()["finished_at"] is not None

        reread = client.get(f"/api/agents/{agent_id}/sessions").json()
        by_id = {s["id"]: s for s in reread}
        assert by_id[first_id]["status"] == "ended"
        assert by_id[first_id]["finished_at"] is not None

        # Read-only: listing never mutates agent state or sessions.
        agent = client.get(f"/api/agents/{agent_id}").json()
        assert agent["state"] == "waiting"  # end_session moved running -> waiting
        assert client.get(f"/api/agents/{agent_id}/sessions").json() == reread


def test_session_history_unknown_agent(client: TestClient, repo_root: Path) -> None:
    import uuid

    with client:
        _open_project(client, repo_root)
        missing = client.get(f"/api/agents/{uuid.uuid4()}/sessions")
        assert missing.status_code == 404, missing.text

"""Event-history query params against live PostgreSQL (integration).

Covers the additive Wave 9 reads: backward cursor paging via ``before_seq``,
task scoping via ``task_id``, and ``correlation_id`` exposure. Default
ordering and existing callers are unchanged.
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


def _seqs(rows: list[dict]) -> list[int]:
    return [r["project_seq"] for r in rows if r["project_seq"] is not None]


def test_backward_paging_and_task_scope(client: TestClient, repo_root: Path) -> None:
    with client:
        project_id = _open_project(client, repo_root)
        first = client.post(f"/api/projects/{project_id}/tasks", json={"title": "History probe"})
        assert first.status_code == 201, first.text
        task_id = first.json()["id"]

        full = client.get(f"/api/events?project_id={project_id}&order=asc&limit=500").json()
        assert len(full) >= 2
        seqs = _seqs(full)
        assert seqs == sorted(seqs)

        newest_first = client.get(f"/api/events?project_id={project_id}&limit=2").json()
        assert len(newest_first) == 2
        oldest_seq = min(_seqs(newest_first))

        older = client.get(
            f"/api/events?project_id={project_id}&before_seq={oldest_seq}&limit=500"
        ).json()
        for row in older:
            if row["project_seq"] is not None:
                assert row["project_seq"] < oldest_seq
        assert {r["id"] for r in older}.isdisjoint({r["id"] for r in newest_first})

        scoped = client.get(
            f"/api/events?project_id={project_id}&task_id={task_id}&limit=500"
        ).json()
        assert len(scoped) >= 1
        assert all(r["task_id"] == task_id for r in scoped)
        assert all("correlation_id" in r for r in scoped)


def test_default_ordering_unchanged(client: TestClient, repo_root: Path) -> None:
    with client:
        project_id = _open_project(client, repo_root)
        rows = client.get(f"/api/events?project_id={project_id}&limit=5").json()
        times = [r["occurred_at"] for r in rows]
        assert times == sorted(times, reverse=True)

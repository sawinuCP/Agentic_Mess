"""Phase-4 worktree isolation + controlled integration queue (FR-012, spec Â§17)."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("git") is None, reason="git not installed"),
]


@pytest.fixture()
def wired(app: FastAPI, repo_root: Path) -> Iterator[tuple[FastAPI, TestClient, str, Path]]:
    """A project whose root is a real git repository with one commit."""
    root = repo_root
    for args in (
        ["init"],
        ["config", "user.email", "test@example.com"],
        ["config", "user.name", "Test"],
    ):
        subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)
    (root / "README.md").write_text("canonical\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=root, capture_output=True, check=True)

    with TestClient(app) as client:
        response = client.post("/api/projects/open", json={"root_path": str(root)})
        yield app, client, response.json()["id"], root


def _commit_in(repo: Path, filename: str, content: str, message: str) -> None:
    (repo / filename).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, capture_output=True, check=True)


def _status_clean(repo: Path) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, check=True
    )
    return result.stdout.decode().strip() == ""


def test_create_worktree_gives_the_agent_an_isolated_copy(wired: tuple) -> None:
    _app, client, project_id, root = wired
    response = client.post(
        f"/api/projects/{project_id}/worktrees", json={"branch": "agent/task-abc"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["branch"] == "agent/task-abc"
    assert body["status"] == "active"
    assert body["integration_status"] == "none"
    assert (root / ".harness" / "worktrees" / "agent-task-abc" / "README.md").exists()

    listed = client.get(f"/api/projects/{project_id}/worktrees?status=active").json()
    assert [w["branch"] for w in listed] == ["agent/task-abc"]


def test_an_active_branch_cannot_be_taken_twice(wired: tuple) -> None:
    _app, client, project_id, _root = wired
    first = client.post(f"/api/projects/{project_id}/worktrees", json={"branch": "agent/task-1"})
    assert first.status_code == 201
    second = client.post(f"/api/projects/{project_id}/worktrees", json={"branch": "agent/task-1"})
    assert second.status_code == 409
    assert "active worktree" in second.json()["detail"]


def test_create_with_idempotency_key_replays_without_touching_git(wired: tuple) -> None:
    _app, client, project_id, _root = wired
    key = f"op-{uuid.uuid4().hex}"
    first = client.post(
        f"/api/projects/{project_id}/worktrees",
        json={"branch": "agent/task-idem", "idempotency_key": key},
    )
    assert first.status_code == 201
    second = client.post(
        f"/api/projects/{project_id}/worktrees",
        json={"branch": "agent/task-idem", "idempotency_key": key},
    )
    assert second.status_code == 200  # replay, not a second git worktree
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["path"] == first.json()["path"]

    from app.db.models import Worktree

    with _app.state.session_factory() as session:
        rows = (
            session.query(Worktree)
            .filter_by(project_id=uuid.UUID(project_id), branch="agent/task-idem")
            .all()
        )
        assert len(rows) == 1
        assert rows[0].idempotency_key == key


def test_invalid_branch_names_rejected(wired: tuple) -> None:
    _app, client, project_id, _root = wired
    for branch in ("   ", "has space", "colon:x", "-leading-dash"):
        response = client.post(f"/api/projects/{project_id}/worktrees", json={"branch": branch})
        assert response.status_code == 422, branch


def test_clean_worktree_integrates_via_the_queue(wired: tuple) -> None:
    _app, client, project_id, root = wired
    worktree = client.post(
        f"/api/projects/{project_id}/worktrees", json={"branch": "agent/task-clean"}
    ).json()
    worktree_dir = Path(worktree["path"])
    _commit_in(worktree_dir, "feature.txt", "from agent\n", "agent work")

    enqueued = client.post(f"/api/worktrees/{worktree['id']}/integration/enqueue")
    assert enqueued.status_code == 200
    assert enqueued.json()["integration_status"] == "queued"
    assert enqueued.json()["integration_position"] == 1

    result = client.post(f"/api/projects/{project_id}/integration/process").json()
    assert result["merged"] is True
    assert result["commit"]
    assert (root / "feature.txt").read_text(encoding="utf-8") == "from agent\n"
    assert result["worktree"]["integration_status"] == "merged"
    assert result["worktree"]["status"] == "merged"
    assert _status_clean(root)

    empty = client.post(f"/api/projects/{project_id}/integration/process").json()
    assert empty["worktree"] is None and "empty" in empty["message"]


def test_conflicting_worktree_becomes_an_explicit_task(wired: tuple) -> None:
    app, client, project_id, root = wired
    worktree = client.post(
        f"/api/projects/{project_id}/worktrees", json={"branch": "agent/task-conflict"}
    ).json()
    worktree_dir = Path(worktree["path"])

    # Diverge: canonical and worktree both change the same file.
    _commit_in(root, "README.md", "canonical edited\n", "canonical change")
    _commit_in(worktree_dir, "README.md", "agent edited\n", "agent change")

    client.post(f"/api/worktrees/{worktree['id']}/integration/enqueue")
    result = client.post(f"/api/projects/{project_id}/integration/process").json()
    assert result["merged"] is False
    assert result["conflict_task_id"] is not None
    assert result["worktree"]["integration_status"] == "conflict"
    assert (root / "README.md").read_text(encoding="utf-8") == "canonical edited\n"
    assert _status_clean(root)  # merge aborted cleanly â€” canonical never left dirty

    task = client.get(f"/api/tasks/{result['conflict_task_id']}").json()
    assert task["payload"]["role"] == "integration"
    assert task["payload"]["branch"] == "agent/task-conflict"
    assert task["status"] == "ready"

    # A conflicted worktree stays out of the queue until its conflict task resolves.
    requeue = client.post(f"/api/worktrees/{worktree['id']}/integration/enqueue")
    assert requeue.status_code == 409
    assert "conflict" in requeue.json()["detail"]


def test_dirty_worktree_release_requires_explicit_force(wired: tuple) -> None:
    _app, client, project_id, _root = wired
    worktree = client.post(
        f"/api/projects/{project_id}/worktrees", json={"branch": "agent/task-dirty"}
    ).json()
    (Path(worktree["path"]) / "uncommitted.txt").write_text("draft", encoding="utf-8")

    refused = client.post(f"/api/worktrees/{worktree['id']}/release")
    assert refused.status_code == 400  # failed attempts remain inspectable (spec Â§17)

    forced = client.post(f"/api/worktrees/{worktree['id']}/release?force=true")
    assert forced.status_code == 200
    assert forced.json()["status"] == "abandoned"

    requeue = client.post(f"/api/worktrees/{worktree['id']}/integration/enqueue")
    assert requeue.status_code == 409  # only active worktrees can be queued

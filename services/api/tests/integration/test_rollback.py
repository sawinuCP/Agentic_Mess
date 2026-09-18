"""Evidence-preserving rollback: snapshot anchors + worktree restore (Wave 2 §7).

ROLLBACK restores code state *without* deleting history: the pre-reset HEAD is
kept on a recovery branch and referenced from ROLLBACK_COMPLETED. Anything that
cannot be restored (no repo, no snapshot) is a graceful no-op, never an error.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Event, Task
from app.durable.activities import (
    init_refs,
    rollback_attempt_activity,
    snapshot_attempt_activity,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("git") is None, reason="git not installed"),
]


@pytest.fixture()
def git_project(app: FastAPI, tmp_path: Path) -> Iterator[tuple[FastAPI, str, str, Path]]:
    """A project whose root is a real git repo with one commit; returns app, project, task, root."""
    root = tmp_path / f"repo-{uuid.uuid4().hex[:8]}"
    root.mkdir()
    for args in (["init"], ["config", "user.email", "t@e.c"], ["config", "user.name", "T"]):
        subprocess.run(["git", *args], cwd=root, capture_output=True, check=True)
    (root / "victim.txt").write_text("committed\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=root, capture_output=True, check=True)
    with TestClient(app):
        init_refs(app.state.session_factory, app.state.artifacts, app.state.settings)
        project_id = (
            TestClient(app).post("/api/projects/open", json={"root_path": str(root)}).json()["id"]
        )
        with app.state.session_factory() as session:
            task = Task(
                project_id=uuid.UUID(project_id),
                title="rollback target",
                request="dirty the repo",
                payload={},
                allowed_tools=["shell"],
            )
            session.add(task)
            session.commit()
            task_id = str(task.id)
        yield app, project_id, task_id, root


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _snapshot(app: FastAPI, task_id: str, attempt_id: str) -> dict:
    return _run(
        snapshot_attempt_activity(
            {
                "task_id": task_id,
                "attempt_id": attempt_id,
                "idempotency_key": f"snapshot:{attempt_id}",
            }
        )
    )


def _rollback(app: FastAPI, task_id: str, attempt_id: str, recovery_id: str) -> dict:
    return _run(
        rollback_attempt_activity(
            {
                "task_id": task_id,
                "attempt_id": attempt_id,
                "idempotency_key": f"rollback:{recovery_id}",
            }
        )
    )


def _head(root: Path) -> str:
    return (
        subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, check=True)
        .stdout.decode()
        .strip()
    )


def _branches(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "branch", "--format=%(refname:short)"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout.decode()
    return [line.strip() for line in out.splitlines() if line.strip()]


def test_snapshot_records_head_and_replays(git_project: tuple) -> None:
    app, _project_id, task_id, root = git_project
    attempt_id = str(uuid.uuid4())
    first = _snapshot(app, task_id, attempt_id)
    assert first["snapshotted"] is True
    assert first["sha"] == _head(root)
    second = _snapshot(app, task_id, attempt_id)
    assert second == {**first, "replayed": True}
    with app.state.session_factory() as session:
        events = session.scalars(
            select(Event).where(
                Event.task_id == uuid.UUID(task_id), Event.event_type == "SNAPSHOT_CREATED"
            )
        ).all()
        assert len(events) == 1


def test_snapshot_graceful_without_repo(app: FastAPI, repo_root: Path) -> None:
    with TestClient(app):
        init_refs(app.state.session_factory, app.state.artifacts, app.state.settings)
        project_id = (
            TestClient(app)
            .post("/api/projects/open", json={"root_path": str(repo_root)})
            .json()["id"]
        )
        with app.state.session_factory() as session:
            task = Task(project_id=uuid.UUID(project_id), title="t", request="r", payload={})
            session.add(task)
            session.commit()
            task_id = str(task.id)
    result = _snapshot(app, task_id, str(uuid.uuid4()))
    assert result == {"snapshotted": False, "reason": "not_a_repo"}


def test_rollback_restores_snapshot_and_keeps_evidence_branch(
    git_project: tuple,
) -> None:
    app, _project_id, task_id, root = git_project
    attempt_id = str(uuid.uuid4())
    clean_sha = _head(root)
    assert _snapshot(app, task_id, attempt_id)["sha"] == clean_sha

    (root / "victim.txt").write_text("dirty work\n", encoding="utf-8")
    # Note: reset restores TRACKED state; untracked files are deliberately left
    # alone (deleting them would destroy unrecoverable evidence).

    result = _rollback(app, task_id, attempt_id, f"rec-{uuid.uuid4().hex[:8]}")
    assert result["rolled_back"] is True
    assert result["to_sha"] == clean_sha
    assert (root / "victim.txt").read_text(encoding="utf-8") == "committed\n"
    branches = _branches(root)
    assert result["evidence_branch"] in branches

    # Replay after a crash between reset and event-commit converges, no duplicates.
    again = _rollback(app, task_id, attempt_id, f"rec-{uuid.uuid4().hex[:8]}")
    assert again["rolled_back"] is True  # already clean: noop path
    with app.state.session_factory() as session:
        rollbacks = session.scalars(
            select(Event).where(
                Event.task_id == uuid.UUID(task_id),
                Event.event_type == "ROLLBACK_COMPLETED",
            )
        ).all()
        assert len(rollbacks) == 1
        assert rollbacks[0].payload["evidence_branch"] == result["evidence_branch"]


def test_rollback_without_snapshot_is_a_noop(git_project: tuple) -> None:
    app, _project_id, task_id, _root = git_project
    result = _rollback(app, task_id, str(uuid.uuid4()), f"rec-{uuid.uuid4().hex[:8]}")
    assert result == {"rolled_back": False, "reason": "no_snapshot"}


def test_merge_conflict_workflow_rolls_back_then_delegates(
    git_project: tuple,
) -> None:
    """End-to-end MERGE_CONFLICT: worktree restored, integration child created."""
    import sys as _sys

    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    from app.artifacts.store import ArtifactStore
    from app.core.config import Settings
    from app.db.base import build_engine, build_session_factory
    from app.durable.activities import (
        agent_execute_activity,
        dependency_status_activity,
        end_agent_session_activity,
        execute_work_activity,
        finish_attempt_activity,
        hitl_recovery_gate_activity,
        load_task_activity,
        record_event_activity,
        recovery_budget_activity,
        replan_task_activity,
        set_agent_state_activity,
        set_task_status_activity,
        snapshot_attempt_activity,
        spawn_child_task_activity,
        start_agent_activity,
        start_attempt_activity,
        task_dependents_activity,
        terminal_failure_activity,
    )
    from app.durable.workflows import TaskExecutionInput, TaskExecutionWorkflow

    app, project_id, task_id, root = git_project
    conflicter = root / "conflicter.py"
    conflicter.write_text(
        "import pathlib, sys\n"
        "pathlib.Path('victim.txt').write_text('conflicted work\\n')\n"
        "sys.stderr.write('merge conflict: both modified victim.txt\\n')\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    with app.state.session_factory() as session:
        task = session.get(Task, uuid.UUID(task_id))
        assert task is not None
        task.payload = {"command": [_sys.executable, str(conflicter)], "timeout_seconds": 60}
        # max_attempts=2: attempt 1 has one attempt left → the class action
        # (create_integration_task); max_attempts=1 would ladder-end immediately.
        task.retry_policy = {"max_attempts": 2}
        session.commit()

    settings = Settings()
    engine = build_engine(settings.database_url)
    init_refs(build_session_factory(engine), ArtifactStore(root / "artifacts"), settings)
    try:

        async def _run() -> dict:
            async with (
                await WorkflowEnvironment.start_time_skipping() as env,
                Worker(
                    env.client,
                    task_queue="wave2-test",
                    workflows=[TaskExecutionWorkflow],
                    activities=[
                        load_task_activity,
                        start_attempt_activity,
                        agent_execute_activity,
                        execute_work_activity,
                        finish_attempt_activity,
                        set_task_status_activity,
                        set_agent_state_activity,
                        start_agent_activity,
                        record_event_activity,
                        recovery_budget_activity,
                        snapshot_attempt_activity,
                        rollback_attempt_activity,
                        spawn_child_task_activity,
                        replan_task_activity,
                        terminal_failure_activity,
                        end_agent_session_activity,
                        task_dependents_activity,
                        dependency_status_activity,
                        hitl_recovery_gate_activity,
                    ],
                ),
            ):
                return await env.client.execute_workflow(
                    TaskExecutionWorkflow.run,
                    TaskExecutionInput(task_id=task_id),
                    id=f"task-exec-{task_id}",
                    task_queue="wave2-test",
                )

        summary = asyncio.run(_run())
    finally:
        engine.dispose()

    assert summary["outcome"] == "failed"
    assert [h["action"] for h in summary["recovery_history"]] == ["create_integration_task"]
    # Worktree restored to the snapshot; the mess survives on a recovery branch.
    assert (root / "victim.txt").read_text(encoding="utf-8") == "committed\n"
    assert any(b.startswith("recovery/") for b in _branches(root))
    with app.state.session_factory() as session:
        children = session.scalars(
            select(Task).where(Task.parent_task_id == uuid.UUID(task_id))
        ).all()
        assert len(children) == 1
        assert children[0].payload.get("kind") == "integration_task"
        types = [
            e.event_type
            for e in session.scalars(select(Event).where(Event.task_id == uuid.UUID(task_id))).all()
        ]
        assert "ROLLBACK_COMPLETED" in types

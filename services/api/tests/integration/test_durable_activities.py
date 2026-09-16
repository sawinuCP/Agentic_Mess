"""Workflow activities against live PostgreSQL (integration).

Activities are decorated plain async functions; they are invoked directly here
with refs initialised against the integration database — no Temporal server
required for this level.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import Coroutine, Iterator
from pathlib import Path
from typing import Any, TypeVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Event, Task, TaskAttempt
from app.durable.activities import (
    execute_work_activity,
    finish_attempt_activity,
    init_refs,
    load_task_activity,
    record_event_activity,
    set_task_status_activity,
    start_attempt_activity,
)
from tests.conftest import unique_repo_root

pytestmark = pytest.mark.integration

_T = TypeVar("_T")


def _run(coro: Coroutine[Any, Any, _T]) -> _T:
    return asyncio.run(coro)


@pytest.fixture()
def wired(app: FastAPI, tmp_path: Path) -> Iterator[tuple[FastAPI, str, Path]]:
    """App with lifespan run, activity refs initialised, project registered."""
    root = unique_repo_root(tmp_path)
    (root / "script.py").write_text("print('x' * 600)\n", encoding="utf-8")
    with TestClient(app):
        init_refs(app.state.session_factory, app.state.artifacts)
        response = TestClient(app).post("/api/projects/open", json={"root_path": str(root)})
        project_id = response.json()["id"]
        yield app, project_id, root


def _create_task(app: FastAPI, project_id: str, payload: dict) -> str:
    with app.state.session_factory() as session:
        task = Task(
            project_id=uuid.UUID(project_id),
            title="durable smoke task",
            request="run the script",
            payload=payload,
        )
        session.add(task)
        session.commit()
        return str(task.id)


def test_attempt_lifecycle_records_evidence(wired: tuple[FastAPI, str, Path]) -> None:
    app, project_id, tmp_path = wired
    task_id = _create_task(
        app, project_id, {"command": [sys.executable, "script.py"], "timeout_seconds": 60}
    )

    loaded = _run(load_task_activity(task_id))
    assert loaded["title"] == "durable smoke task"
    assert loaded["project_id"] == project_id

    attempt = _run(start_attempt_activity({"task_id": task_id, "attempt_number": 1}))
    result = _run(
        execute_work_activity(
            {
                "task_id": task_id,
                "attempt_id": attempt["id"],
                "project_id": project_id,
                "payload": {"command": [sys.executable, "script.py"]},
            }
        )
    )
    assert result["outcome"] == "success"
    assert len(result["evidence_artifact_ids"]) >= 1  # stdout stored (stderr too small)

    _run(
        finish_attempt_activity(
            {
                "attempt_id": attempt["id"],
                "outcome": "success",
                "failure_class": None,
                "failure_detail": None,
                "evidence_artifact_ids": result["evidence_artifact_ids"],
            }
        )
    )
    _run(set_task_status_activity({"task_id": task_id, "status": "completed"}))
    _run(
        record_event_activity(
            {"task_id": task_id, "event_type": "TASK_COMPLETED", "payload": {"attempts": 1}}
        )
    )

    with app.state.session_factory() as session:
        attempt_row = session.get(TaskAttempt, uuid.UUID(attempt["id"]))
        assert attempt_row is not None
        assert attempt_row.outcome == "success"
        assert attempt_row.finished_at is not None
        assert len(attempt_row.evidence_artifact_ids) == 1
        events = session.scalars(select(Event).where(Event.task_id == uuid.UUID(task_id))).all()
        assert any(e.event_type == "TASK_COMPLETED" for e in events)


def test_failing_work_records_failure_classification(
    wired: tuple[FastAPI, str, Path],
) -> None:
    app, project_id, _tmp_path = wired
    task_id = _create_task(
        app,
        project_id,
        {"command": [sys.executable, "-c", "import sys; sys.exit(3)"], "timeout_seconds": 60},
    )
    attempt = _run(start_attempt_activity({"task_id": task_id, "attempt_number": 1}))
    result = _run(
        execute_work_activity(
            {
                "task_id": task_id,
                "attempt_id": attempt["id"],
                "project_id": project_id,
                "payload": {"command": [sys.executable, "-c", "import sys; sys.exit(3)"]},
            }
        )
    )
    assert result["outcome"] == "failed"
    assert result["failure_class"] == "TASK_FAILURE"


def test_work_without_command_fails_honestly(wired: tuple[FastAPI, str, Path]) -> None:
    _app, _project_id, _tmp_path = wired
    result = _run(
        execute_work_activity(
            {"task_id": str(uuid.uuid4()), "attempt_id": str(uuid.uuid4()), "payload": {}}
        )
    )
    assert result["outcome"] == "failed"
    assert result["failure_class"] == "TASK_FAILURE"
    assert "payload.command is missing" in result["failure_detail"]

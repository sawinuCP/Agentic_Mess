"""set_task_status_activity idempotency (live finding: scheduler pre-claims tasks
as running before the workflow starts, so the workflow's own set-to-running
must be a no-op — not a 422 that fails a healthy task)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

import app.durable.activities.tasks as task_activities
from app.core.errors import DomainError


class _StubTask:
    def __init__(self, status: str) -> None:
        self.status = status


class _StubSession:
    def __init__(self, task: _StubTask) -> None:
        self._task = task
        self.commits = 0

    def __enter__(self) -> _StubSession:
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def get(self, _model: Any, _task_id: uuid.UUID) -> _StubTask:
        return self._task

    def commit(self) -> None:
        self.commits += 1


def _run(monkeypatch: pytest.MonkeyPatch, task: _StubTask, target: str) -> _StubSession:
    session = _StubSession(task)
    monkeypatch.setattr(task_activities, "refs", lambda: (lambda: session, None))
    asyncio.run(
        task_activities.set_task_status_activity(
            {"task_id": str(uuid.uuid4()), "status": target}
        )
    )
    return session


def test_same_state_set_is_noop_success(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _run(monkeypatch, _StubTask("running"), "running")
    assert session.commits == 0


def test_lawful_transition_still_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    task = _StubTask("running")
    session = _run(monkeypatch, task, "completed")
    assert task.status == "completed"
    assert session.commits == 1


def test_unlawful_transition_still_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(DomainError, match="Invalid task transition"):
        _run(monkeypatch, _StubTask("completed"), "ready")

"""Model cost ledger integration (spec §32): recording, summary, budget gate."""

from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.durable.activities import agent_execute_activity, init_refs, start_agent_activity
from app.services import costs as cost_service

pytestmark = pytest.mark.integration


@pytest.fixture()
def wired(app: FastAPI, tmp_path: Path) -> Iterator[tuple[FastAPI, TestClient, str]]:
    (tmp_path / "work.py").write_text("print('cost ledger work')\n", encoding="utf-8")
    with TestClient(app) as client:
        init_refs(app.state.session_factory, app.state.artifacts, app.state.settings)
        response = TestClient(app).post("/api/projects/open", json={"root_path": str(tmp_path)})
        yield app, client, response.json()["id"]


def _add_task(app: FastAPI, project_id: str) -> str:
    from app.db.models import Task

    with app.state.session_factory() as session:
        task = Task(
            project_id=uuid.UUID(project_id),
            title="cost task",
            request="run the ledger probe",
            payload={"command": [sys.executable, "work.py"]},
            allowed_tools=["shell"],
        )
        session.add(task)
        session.commit()
        return str(task.id)


def _execute(app: FastAPI, project_id: str, task_id: str) -> dict:
    async def _flow() -> dict:
        agent = await start_agent_activity(
            {"task_id": task_id, "attempt_number": 1, "attempt_id": str(uuid.uuid4())}
        )
        return await agent_execute_activity(
            {
                "task_id": task_id,
                "attempt_id": str(uuid.uuid4()),
                "agent_id": agent["agent_id"],
                "session_id": agent["session_id"],
                "project_id": project_id,
                "payload": {"command": [sys.executable, "work.py"], "timeout_seconds": 60},
            }
        )

    return asyncio.run(_flow())


def test_model_calls_are_recorded_in_the_ledger(wired: tuple) -> None:
    app, client, project_id = wired
    task_id = _add_task(app, project_id)
    result = _execute(app, project_id, task_id)
    assert result["outcome"] == "success", result

    summary = cost_service.summary(
        app.state.session_factory(), uuid.UUID(project_id), uuid.UUID(task_id)
    )
    assert summary["invocations"] >= 1
    assert summary["total_tokens"] > 0
    assert any("rehearsal" in model for model in summary["by_model"])

    endpoint = client.get(
        f"/api/projects/{project_id}/intelligence/costs", params={"task_id": task_id}
    )
    assert endpoint.status_code == 200
    body = endpoint.json()
    assert body["total_tokens"] == summary["total_tokens"]
    assert body["task_id"] == task_id


def test_budget_gate_fails_closed_when_exhausted(
    wired: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client, project_id = wired
    task_id = _add_task(app, project_id)

    # Pre-charge the task beyond its configured budget.
    factory: sessionmaker = app.state.session_factory
    with factory() as session:
        cost_service.record_invocation(
            session,
            project_id=uuid.UUID(project_id),
            task_id=uuid.UUID(task_id),
            agent_id=None,
            role="worker",
            provider="rehearsal",
            model="rehearsal-1",
            prompt_tokens=10_000,
            completion_tokens=10_000,
        )

    monkeypatch.setattr(app.state.settings, "model_budget_tokens_per_task", 100)
    result = _execute(app, project_id, task_id)
    assert result["outcome"] == "failed"
    assert result["failure_class"] == "BUDGET_EXCEEDED"

    from app.db.models import Event

    with factory() as session:
        event = (
            session.query(Event)
            .filter_by(task_id=uuid.UUID(task_id), event_type="MODEL_BUDGET_EXCEEDED")
            .one()
        )
        assert event.source == "temporal"

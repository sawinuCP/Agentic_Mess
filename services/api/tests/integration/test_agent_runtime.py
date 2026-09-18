"""Phase-3 runtime integration: HITL gates, supervision, agent execution path."""

from __future__ import annotations

import asyncio
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import AgentSession, HitlRequest
from app.durable.activities import agent_execute_activity, init_refs, start_agent_activity
from app.services.orchestration import agents as agent_service
from app.services.orchestration import hitl as hitl_service

pytestmark = pytest.mark.integration


@pytest.fixture()
def wired(app: FastAPI, repo_root: Path) -> Iterator[tuple[FastAPI, str, Path]]:
    root = repo_root
    (root / "work.py").write_text("print('x' * 700)\n", encoding="utf-8")
    with TestClient(app):
        init_refs(app.state.session_factory, app.state.artifacts, app.state.settings)
        response = TestClient(app).post("/api/projects/open", json={"root_path": str(root)})
        yield app, response.json()["id"], root


def _create_task(app: FastAPI, project_id: str, payload: dict) -> str:
    from app.db.models import Task

    with app.state.session_factory() as session:
        task = Task(
            project_id=uuid.UUID(project_id),
            title="phase3 task",
            request="run gated work",
            payload=payload,
            allowed_tools=["shell"],
        )
        session.add(task)
        session.commit()
        return str(task.id)


def test_reviewer_agent_cannot_execute_shell(wired: tuple[FastAPI, str, Path]) -> None:
    """Read-only roles observe but never execute: the gateway denies shell."""
    from app.db.models import Agent, Task

    app, project_id, _tmp = wired
    task_id = _create_task(app, project_id, {"command": [sys.executable, "work.py"]})
    # Reviewers are created read-only (policy, not model choice).
    with app.state.session_factory() as session:
        task = session.get(Task, uuid.UUID(task_id))
        assert task is not None
        task.payload = {**(task.payload or {}), "agent_role": "reviewer"}
        session.commit()

    async def _flow() -> dict:
        agent = await start_agent_activity(
            {"task_id": task_id, "attempt_number": 1, "attempt_id": str(uuid.uuid4())}
        )
        with app.state.session_factory() as session:
            row = session.get(Agent, uuid.UUID(agent["agent_id"]))
            assert row is not None
            assert sorted(row.capabilities) == ["read"]
        return await agent_execute_activity(
            {
                "task_id": task_id,
                "attempt_id": str(uuid.uuid4()),
                "agent_id": agent["agent_id"],
                "session_id": agent["session_id"],
                "project_id": project_id,
            }
        )

    # Policy denial is a contained failure outcome (recovery classifies it),
    # never an escaping exception that would strand the workflow.
    result = asyncio.run(_flow())
    assert result["outcome"] == "failed"
    assert result["failure_class"] == "SECURITY_BLOCK"
    assert "capability" in result["failure_detail"]


def test_hitl_gate_approves_and_executes(wired: tuple[FastAPI, str, Path]) -> None:
    app, project_id, tmp_path = wired
    task_id = _create_task(
        app,
        project_id,
        {"command": [sys.executable, "-c", "print('DROP TABLE users'.lower())"]},
    )
    attempt_id = str(uuid.uuid4())

    async def _flow() -> dict:
        agent = await start_agent_activity(
            {"task_id": task_id, "attempt_number": 1, "attempt_id": attempt_id}
        )
        exec_task = asyncio.ensure_future(
            agent_execute_activity(
                {
                    "task_id": task_id,
                    "attempt_id": attempt_id,
                    "agent_id": agent["agent_id"],
                    "session_id": agent["session_id"],
                    "project_id": project_id,
                    "payload": {
                        "command": [sys.executable, "-c", "print('DROP TABLE'.lower())"],
                        "timeout_seconds": 60,
                    },
                }
            )
        )
        await asyncio.sleep(3)  # gate request created and polling
        with app.state.session_factory() as session:
            pending = session.scalars(
                select(HitlRequest).where(HitlRequest.status == "pending")
            ).all()
            assert pending, "expected a pending HITL request"
            hitl_service.decide_request(session, pending[0].id, "approved", "user", "ok")
        return await exec_task

    result = asyncio.run(_flow())
    assert result["outcome"] == "success", result
    assert "drop table" in result["observation"]["summary"]
    with app.state.session_factory() as session:
        requests = session.scalars(
            select(HitlRequest).where(HitlRequest.project_id == uuid.UUID(project_id))
        ).all()
        assert requests, "expected HITL requests for this project"
        assert all(r.status == "approved" for r in requests)


def test_hitl_gate_fails_closed_on_timeout(wired: tuple[FastAPI, str, Path]) -> None:
    app, project_id, _tmp_path = wired
    task_id = _create_task(
        app, project_id, {"command": ["echo", "DROP TABLE users"], "timeout_seconds": 60}
    )

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
                "payload": {"command": ["echo", "DROP TABLE users"], "timeout_seconds": 60},
            }
        )

    # The gate polls for HITL_TIMEOUT_SECONDS; shrink it via app settings.
    app.state.settings.hitl_timeout_seconds = 2
    app.state.settings.hitl_poll_seconds = 0.2
    result = asyncio.run(_flow())
    app.state.settings.hitl_timeout_seconds = 300
    assert result["outcome"] == "failed"
    assert result["failure_class"] == "SECURITY_BLOCK"
    assert "timeout" in result["failure_detail"]


def test_supervision_marks_stale_sessions_lost(wired: tuple[FastAPI, str, Path]) -> None:
    def _supervise(app: FastAPI, stale_seconds: int) -> dict[str, int]:
        with app.state.session_factory() as session:
            return agent_service.supervise_sessions(session, stale_seconds)

    app, project_id, _tmp_path = wired
    with app.state.session_factory() as session:
        from app.db.models import Agent

        row = Agent(
            project_id=uuid.UUID(project_id),
            name="lost-agent",
            role="worker",
            capabilities=[],
            state="running",
        )
        session.add(row)
        session.commit()
        agent_id = row.id
        cutoff = datetime.now(UTC) - timedelta(seconds=600)
        lost_session = AgentSession(
            agent_id=agent_id,
            runtime="temporal-worker",
            status="running",
            started_at=cutoff,
            heartbeat_at=cutoff,
        )
        session.add(lost_session)
        session.commit()
        session_id = lost_session.id

    result = asyncio.run(asyncio.to_thread(_supervise, app, 300))
    assert result["marked_lost"] >= 1
    with app.state.session_factory() as session:
        assert session.get(AgentSession, session_id).status == "lost"


def test_tool_lifecycle_events_bracket_each_command(
    wired: tuple[FastAPI, str, Path],
) -> None:
    """Per-command TOOL_STARTED/COMPLETED(/FAILED): bounded lifecycle frames
    (≤2 per command, concise payload, evidence by artifact id) — the allowed
    granularity between silence and per-token storms."""
    from app.db.models import Event

    app, project_id, _tmp_path = wired
    task_id = _create_task(app, project_id, {"command": [sys.executable, "work.py"]})
    attempt_id = str(uuid.uuid4())

    async def _flow() -> dict:
        agent = await start_agent_activity(
            {"task_id": task_id, "attempt_number": 1, "attempt_id": attempt_id}
        )
        return await agent_execute_activity(
            {
                "task_id": task_id,
                "attempt_id": attempt_id,
                "agent_id": agent["agent_id"],
                "session_id": agent["session_id"],
                "project_id": project_id,
            }
        )

    result = asyncio.run(_flow())
    assert result["outcome"] == "success", result
    with app.state.session_factory() as session:
        rows = session.scalars(
            select(Event).where(
                Event.task_id == uuid.UUID(task_id),
                Event.event_type.in_(("TOOL_STARTED", "TOOL_COMPLETED", "TOOL_FAILED")),
            )
        ).all()
        kinds = [row.event_type for row in rows]
        assert kinds == ["TOOL_STARTED", "TOOL_COMPLETED"]
        started, completed = (row.payload for row in rows)
        assert started["tool"] == "shell" and started["attempt_id"] == attempt_id
        assert "work.py" in started["command"]
        assert completed["status"] == "success"
        assert completed["exit_code"] == 0
        assert all(row.agent_id for row in rows)


def test_failed_command_emits_tool_failed(wired: tuple[FastAPI, str, Path]) -> None:
    from app.db.models import Event

    app, project_id, _tmp_path = wired
    task_id = _create_task(
        app,
        project_id,
        {"command": [sys.executable, "-c", "import sys; sys.exit(3)"]},
    )
    attempt_id = str(uuid.uuid4())

    async def _flow() -> dict:
        agent = await start_agent_activity(
            {"task_id": task_id, "attempt_number": 1, "attempt_id": attempt_id}
        )
        return await agent_execute_activity(
            {
                "task_id": task_id,
                "attempt_id": attempt_id,
                "agent_id": agent["agent_id"],
                "session_id": agent["session_id"],
                "project_id": project_id,
            }
        )

    result = asyncio.run(_flow())
    assert result["outcome"] == "failed"
    with app.state.session_factory() as session:
        kinds = [
            row.event_type
            for row in session.scalars(
                select(Event).where(
                    Event.task_id == uuid.UUID(task_id),
                    Event.event_type.in_(("TOOL_STARTED", "TOOL_COMPLETED", "TOOL_FAILED")),
                )
            ).all()
        ]
        assert kinds == ["TOOL_STARTED", "TOOL_FAILED"]

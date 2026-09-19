"""Chaos integration: kill -9, NATS loss, and PostgreSQL restarts mid-run.

All tests assert the same invariant from different directions — when the
ephemeral side dies, the durable side (PostgreSQL) still has the truth and the
system resumes instead of corrupting, duplicating, or hanging work.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import text

from app.db.base import build_engine, build_session_factory
from app.durable.activities import (
    agent_execute_activity,
    end_agent_session_activity,
    execute_work_activity,
    finish_attempt_activity,
    hitl_recovery_gate_activity,
    init_refs,
    load_task_activity,
    record_event_activity,
    recovery_budget_activity,
    replan_task_activity,
    rollback_attempt_activity,
    set_agent_state_activity,
    set_task_status_activity,
    snapshot_attempt_activity,
    spawn_child_task_activity,
    start_agent_activity,
    start_attempt_activity,
    task_dependents_activity,
    terminal_failure_activity,
)
from app.services.intelligence import costs as cost_service

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        shutil.which("docker") is None, reason="docker CLI is required for DB chaos"
    ),
]

_PG_CONTAINER = "ai-harness-postgres-1"

_CHILD_RUNNER = """\
import asyncio
import json
import sys
import uuid
from pathlib import Path

from app.artifacts.store import ArtifactStore
from app.core.config import Settings
from app.db.base import build_engine, build_session_factory
from app.durable.activities import agent_execute_activity
from app.durable.activities._context import init_refs


async def _main(task_id: str, agent_id: str, session_id: str, project_id: str) -> None:
    settings = Settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    init_refs(factory, ArtifactStore(Path(settings.artifacts_dir)), settings)
    result = await agent_execute_activity(
        {
            "task_id": task_id,
            "attempt_id": str(uuid.uuid4()),
            "agent_id": agent_id,
            "session_id": session_id,
            "project_id": project_id,
        }
    )
    print("child_result=" + json.dumps(result), flush=True)


asyncio.run(_main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]))
"""


def _add_task(app: FastAPI, project_id: str, command: list[str]) -> str:
    from app.db.models import Task

    with app.state.session_factory() as session:
        task = Task(
            project_id=uuid.UUID(project_id),
            title="chaos task",
            request="survive kill -9",
            payload={"command": command, "timeout_seconds": 120},
            allowed_tools=["shell"],
        )
        session.add(task)
        session.commit()
        return str(task.id)


def _ledger_count(app: FastAPI, task_id: str) -> int:
    with app.state.session_factory() as session:
        return cost_service.invocations_for_task(session, uuid.UUID(task_id))


def test_injected_tool_failure_classifies_and_recovers(project: tuple) -> None:
    """Failure injection through the real activity path: a simulated tool
    outage fails the attempt as TOOL_FAILURE (policy still enforced first)."""
    from app.core.config import Settings

    app, _client, project_id, root = project
    (root / "work.py").write_text("print('never runs')\n", encoding="utf-8")
    settings = Settings(
        failure_injection=True,
        failure_injection_points="tool_fail",
    )
    init_refs(app.state.session_factory, app.state.artifacts, settings)
    try:
        task_id = _add_task(app, project_id, [sys.executable, "work.py"])

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
                }
            )

        result = asyncio.run(_flow())
        assert result["outcome"] == "failed"
        assert result["failure_class"] == "TOOL_FAILURE"
        assert "simulation" in result["failure_detail"]
    finally:
        init_refs(app.state.session_factory, app.state.artifacts, app.state.settings)


def test_injected_model_flakiness_rides_retry_then_fallback() -> None:
    """Flaky provider (2 injected failures) exhausts primary retries and lands
    on the configured fallback role — the full production chain, no mocks."""
    from app.agents_runtime.models_registry import ModelRegistry
    from app.agents_runtime.providers import ModelRequest
    from app.chaos.faults import FaultState

    async def _run() -> object:
        registry = ModelRegistry(
            {
                "worker": {
                    "provider": "rehearsal",
                    "model": "r1",
                    "fallback_role": "reviewer",
                },
                "reviewer": {"provider": "rehearsal", "model": "r2"},
            },
            max_attempts=2,
            backoff_base_seconds=0.01,
            backoff_jitter_ratio=0.0,
        )
        faults = FaultState(enabled=True, points={"model_flaky": "2"})
        return await registry.complete(
            ModelRequest(role="worker", system="s", prompt="- RUN: echo hi"),
            faults=faults,
        )

    response = asyncio.run(_run())
    assert response.fell_back_to == "reviewer"


def test_kill9_worker_mid_run_then_retry_succeeds(project: tuple, tmp_path: Path) -> None:
    app, _client, project_id, root = project
    init_refs(app.state.session_factory, app.state.artifacts, app.state.settings)

    (root / "sleeper.py").write_text("import time\ntime.sleep(20)\n", encoding="utf-8")
    (root / "fast.py").write_text("print('recovered')\n", encoding="utf-8")
    runner = tmp_path / "chaos_child.py"
    runner.write_text(_CHILD_RUNNER, encoding="utf-8")

    task_id = _add_task(app, project_id, [sys.executable, "sleeper.py"])

    async def _start_agent() -> dict:
        return await start_agent_activity(
            {"task_id": task_id, "attempt_number": 1, "attempt_id": str(uuid.uuid4())}
        )

    agent = asyncio.run(_start_agent())

    child = subprocess.Popen(
        [sys.executable, str(runner), task_id, agent["agent_id"], agent["session_id"], project_id],
        cwd=Path(__file__).resolve().parents[2],  # services/api (runner + app imports)
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        # Wait until the child provably reached command execution (its model
        # invocation is recorded before the sleep starts), then kill -9 it.
        deadline = time.monotonic() + 30
        while _ledger_count(app, task_id) == 0 and time.monotonic() < deadline:
            time.sleep(0.5)
        assert _ledger_count(app, task_id) >= 1, "child never reached execution"
        assert child.poll() is None, "child exited before the kill"
        child.kill()  # SIGKILL / TerminateProcess: uncatchable, no cleanup runs
        child.wait(timeout=15)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=15)

    # Durable state survived the crash: task + agent + session rows intact.
    from app.db.models import Agent, AgentSession, Task

    with app.state.session_factory() as session:
        assert session.get(Task, uuid.UUID(task_id)) is not None
        assert session.get(Agent, uuid.UUID(agent["agent_id"])) is not None
        assert session.get(AgentSession, uuid.UUID(agent["session_id"])) is not None

    # Retry in this process with a fast payload: succeeds, no duplicate confusion.
    with app.state.session_factory() as session:
        task = session.get(Task, uuid.UUID(task_id))
        assert task is not None
        task.payload = {"command": [sys.executable, "fast.py"], "timeout_seconds": 120}
        session.commit()

    async def _retry() -> dict:
        agent2 = await start_agent_activity(
            {"task_id": task_id, "attempt_number": 2, "attempt_id": str(uuid.uuid4())}
        )
        return await agent_execute_activity(
            {
                "task_id": task_id,
                "attempt_id": str(uuid.uuid4()),
                "agent_id": agent2["agent_id"],
                "session_id": agent2["session_id"],
                "project_id": project_id,
            }
        )

    result = asyncio.run(_retry())
    assert result["outcome"] == "success", result
    assert _ledger_count(app, task_id) >= 2  # crashed attempt + retry, both accounted


def test_nats_transport_loss_mid_run_keeps_durable_history(
    project: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    app, client, _project_id, _tmp = project
    live_url = app.state.settings.nats_url

    monkeypatch.setattr(app.state.settings, "nats_delivery_enabled", True)
    first = client.post("/api/messages", json={"type": "request", "payload": {"n": 1}})
    assert first.status_code == 201
    delivered = client.post("/api/messages/deliver-pending")
    assert delivered.status_code == 200, delivered.json()

    # NATS drops mid-run: transport fails closed, durable rows are untouched.
    # (127.0.0.1, not localhost: IPv6 ::1 blackholes on this host instead of
    # refusing, which would hang any client regardless of its timeout.)
    monkeypatch.setattr(app.state.settings, "nats_url", "nats://127.0.0.1:9")
    conversation = first.json()["conversation_id"]
    second = client.post(
        "/api/messages",
        json={"type": "request", "payload": {"n": 2}, "conversation_id": conversation},
    )
    assert second.status_code == 201
    failed = client.post("/api/messages/deliver-pending")
    assert failed.status_code == 503

    replayed = client.get(f"/api/conversations/{conversation}/messages").json()
    assert len(replayed) == 2  # both sends durable despite the transport loss
    assert replayed[0]["delivered_at"] is not None
    assert replayed[1]["delivered_at"] is None

    # Transport recovers: the pending message drains, nothing duplicated.
    monkeypatch.setattr(app.state.settings, "nats_url", live_url)
    redelivered = client.post("/api/messages/deliver-pending").json()
    assert redelivered["delivered_count"] == 1
    replayed = client.get(f"/api/conversations/{conversation}/messages").json()
    assert all(m["delivered_at"] is not None for m in replayed)


def _wait_for_port(host: str, port: int, timeout: float = 60) -> None:
    import socket

    deadline = time.monotonic() + timeout
    while True:
        try:
            socket.create_connection((host, port), timeout=2).close()
            return
        except OSError as exc:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"{host}:{port} never came back") from exc
            time.sleep(1)


def test_killed_backends_are_transparent_to_the_pool() -> None:
    """`pool_pre_ping` recycles dead pooled connections without surfacing errors."""
    from app.core.config import Settings

    settings = Settings()
    engine = build_engine(settings.database_url)
    try:
        factory = build_session_factory(engine)
        with factory() as session:
            pid = session.execute(text("SELECT pg_backend_pid()")).scalar()
            # Kill every backend on a SEPARATE connection (never our own row).
            session.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND pid <> pg_backend_pid()"
                )
            )
            session.commit()
            assert isinstance(pid, int)
        # The pool transparently reconnects: reads and writes just work.
        with factory() as session:
            assert session.execute(text("SELECT 1")).scalar() == 1
            session.execute(text("SELECT pg_backend_pid()"))
            session.commit()
    finally:
        engine.dispose()


def test_postgres_restart_mid_workflow_recovers(project: tuple, tmp_path: Path) -> None:
    """A container restart during execution loses no durable state and the
    workflow completes: heartbeats are best-effort, durable writes retry, and
    the pool reconnects — nothing hangs, nothing duplicates."""
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    from app.artifacts.store import ArtifactStore
    from app.core.config import Settings
    from app.durable.workflows import TaskExecutionInput, TaskExecutionWorkflow

    app, _client, project_id, root = project
    (root / "slow.py").write_text("import time\ntime.sleep(20)\n", encoding="utf-8")

    settings = Settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    init_refs(factory, ArtifactStore(tmp_path / "artifacts"), settings)
    try:
        from app.db.models import Task

        with factory() as session:
            task = Task(
                project_id=uuid.UUID(project_id),
                title="restart rodeo",
                request="survive a database restart",
                payload={"command": [sys.executable, "slow.py"], "timeout_seconds": 120},
                allowed_tools=["shell"],
                retry_policy={"max_attempts": 2},
            )
            session.add(task)
            session.commit()
            task_id = str(task.id)

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
                        hitl_recovery_gate_activity,
                    ],
                ),
            ):
                run = asyncio.ensure_future(
                    env.client.execute_workflow(
                        TaskExecutionWorkflow.run,
                        TaskExecutionInput(task_id=task_id),
                        id=f"task-exec-{task_id}",
                        task_queue="wave2-test",
                    )
                )
                # Wait until the attempt provably started executing, then
                # pull the database out from under it mid-flight.
                deadline = time.monotonic() + 60
                while True:
                    with factory() as session:
                        started = cost_service.invocations_for_task(session, uuid.UUID(task_id))
                    if started >= 1:
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError("attempt never started executing")
                    await asyncio.sleep(0.5)
                subprocess.run(
                    ["docker", "restart", _PG_CONTAINER],
                    capture_output=True,
                    check=True,
                    timeout=120,
                )
                _wait_for_port("127.0.0.1", 15432)
                return await run

        summary = asyncio.run(_run())
        assert summary["outcome"] == "success", summary
        assert summary["attempts"] == 1  # no duplicate attempt from the outage
        with factory() as session:
            task = session.get(Task, uuid.UUID(task_id))
            assert task is not None and task.status == "completed"
    finally:
        engine.dispose()

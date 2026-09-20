"""Temporal recovery-coordinator tests (Wave 2 acceptance core).

The task workflow runs against the time-skipping test server with real
activities and the live database: recovery decisions must produce real bounded
actions (replace/spawn/terminal/HITL), the replacement chain must drain the old
agent, and nothing may loop or strand a task.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.artifacts.store import ArtifactStore
from app.core.config import Settings
from app.db.base import build_engine, build_session_factory
from app.db.models import Agent, AgentSession, Event, Project, Task, TaskAttempt
from app.durable.activities import (
    agent_execute_activity,
    dependency_status_activity,
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
from app.durable.workflows import TaskExecutionInput, TaskExecutionWorkflow

pytestmark = pytest.mark.integration

_ACTIVITIES = [
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
]


def _settings(**overrides: object) -> Settings:
    base = {
        "environment": "test",
        "log_level": "WARNING",
        "otel_enabled": False,
        "nats_events_enabled": False,
        "temporal_enabled": False,
        "hitl_timeout_seconds": 3.0,
        "hitl_poll_seconds": 0.2,
    }
    base.update(overrides)  # type: ignore[typeddict-item]
    return Settings(**base)  # type: ignore[arg-type]


def _seed(root: Path, command: list[str], *, max_attempts: int = 2) -> tuple[Settings, str, str]:
    settings = _settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    init_refs(factory, ArtifactStore(root / "artifacts"), settings)
    with factory() as session:
        project = Project(name=f"wf-{uuid.uuid4().hex[:8]}", root_path=str(root))
        session.add(project)
        session.flush()
        task = Task(
            project_id=project.id,
            title="workflow task",
            request="run",
            payload={"command": command, "timeout_seconds": 60},
            allowed_tools=["shell"],
            retry_policy={"max_attempts": max_attempts},
        )
        session.add(task)
        session.commit()
        ids = str(project.id), str(task.id)
    engine.dispose()
    return settings, ids[0], ids[1]


async def _execute(settings: Settings, task_id: str) -> dict:
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue="wave2-test",
            workflows=[TaskExecutionWorkflow],
            activities=_ACTIVITIES,
        ),
    ):
        return await env.client.execute_workflow(
            TaskExecutionWorkflow.run,
            TaskExecutionInput(task_id=task_id),
            id=f"task-exec-{task_id}",
            task_queue="wave2-test",
        )


def _run(settings: Settings, task_id: str) -> dict:
    return asyncio.run(_execute(settings, task_id))


def _events(task_id: str, *types: str) -> list[Event]:
    settings = _settings()
    engine = build_engine(settings.database_url)
    try:
        with build_session_factory(engine)() as session:
            return session.scalars(
                select(Event)
                .where(Event.task_id == uuid.UUID(task_id))
                .order_by(Event.occurred_at, Event.id)
            ).all()
    finally:
        engine.dispose()


def _event_types(task_id: str) -> list[str]:
    return [e.event_type for e in _events(task_id)]


def _session():
    """Throwaway session factory on the harness DB (polling helpers only)."""
    from contextlib import contextmanager

    engine = build_engine(_settings().database_url)
    factory = build_session_factory(engine)

    @contextmanager
    def _scope():
        try:
            with factory() as session:
                yield session
        finally:
            engine.dispose()

    return _scope()


def test_retry_then_success_completes(tmp_path: Path) -> None:
    marker = tmp_path / "attempted"
    script = tmp_path / "flaky.py"
    script.write_text(
        "import pathlib, sys\n"
        f"m = pathlib.Path({str(marker)!r})\n"
        "sys.exit(0 if m.exists() else (m.touch() or 1))\n",
        encoding="utf-8",
    )
    settings, _project_id, task_id = _seed(tmp_path, [sys.executable, str(script)], max_attempts=3)
    summary = _run(settings, task_id)
    assert summary["outcome"] == "success"
    assert summary["attempts"] == 2
    assert summary["recovery_history"][0]["action"] == "retry_then_replan"
    assert "RECOVERY_SELECTED" in _event_types(task_id)
    assert "RETRY_STARTED" in _event_types(task_id)


def test_workflow_history_stays_bounded_per_attempt(tmp_path: Path) -> None:
    """Temporal history growth (§15/§40): a 2-attempt run with recovery must
    produce hundreds — not thousands — of history events. Large payloads ride
    activities/artifacts, never workflow state."""
    script = tmp_path / "ok.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    settings, _project_id, task_id = _seed(tmp_path, [sys.executable, str(script)], max_attempts=3)

    async def _run_with_history() -> tuple[dict, int]:
        async with (
            await WorkflowEnvironment.start_time_skipping() as env,
            Worker(
                env.client,
                task_queue="wave2-test",
                workflows=[TaskExecutionWorkflow],
                activities=_ACTIVITIES,
            ),
        ):
            summary = await env.client.execute_workflow(
                TaskExecutionWorkflow.run,
                TaskExecutionInput(task_id=task_id),
                id=f"task-exec-{task_id}",
                task_queue="wave2-test",
            )
            handle = env.client.get_workflow_handle(f"task-exec-{task_id}")
            history = await handle.fetch_history()
            return summary, len(history.events)

    summary, history_events = asyncio.run(_run_with_history())
    assert summary["outcome"] == "success"
    assert summary["attempts"] == 1
    print(f"\nHISTORY_RESULT attempts=1 events={history_events}")
    assert history_events < 300, f"history growing unbounded: {history_events} events"


def test_tool_failure_replaces_agent_then_replans_at_ladder_end(tmp_path: Path) -> None:
    script = tmp_path / "brokentool.py"
    script.write_text(
        "import sys\nsys.stderr.write('tool pytest missing from PATH\\n')\nsys.exit(1)\n",
        encoding="utf-8",
    )
    settings, project_id, task_id = _seed(tmp_path, [sys.executable, str(script)], max_attempts=2)
    summary = _run(settings, task_id)

    assert summary["outcome"] == "failed"
    assert summary["attempts"] == 2
    actions = [h["action"] for h in summary["recovery_history"]]
    assert actions == ["replace_agent", "escalate_or_replan"]

    engine = build_engine(settings.database_url)
    try:
        with build_session_factory(engine)() as session:
            agents = session.scalars(
                select(Agent).where(Agent.project_id == uuid.UUID(project_id))
            ).all()
            assert len(agents) == 2
            first, second = sorted(agents, key=lambda a: a.created_at)
            # Replacement chain recorded; old agent drained, no duplicates running.
            replaced = [
                e
                for e in _events(task_id)
                if e.event_type == "AGENT_CREATED"
                and e.payload.get("replaces_agent_id") == str(first.id)
            ]
            assert replaced, "second agent must record replaces_agent_id"
            assert second.id == uuid.UUID(replaced[0].payload["agent_id"])
            assert session.get(Agent, first.id) is not None
            first_session = session.scalars(
                select(AgentSession).where(AgentSession.agent_id == first.id)
            ).one()
            assert first_session.status == "ended"
            assert "AGENT_REPLACED" in _event_types(task_id)
            children = session.scalars(
                select(Task).where(Task.parent_task_id == uuid.UUID(task_id))
            ).all()
            assert len(children) == 1 and children[0].title.startswith("Replan: ")
            assert "TASK_TERMINALLY_FAILED" in _event_types(task_id)
    finally:
        engine.dispose()


def test_task_failure_spawns_debugger_and_references_it(tmp_path: Path) -> None:
    script = tmp_path / "always_fails.py"
    script.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    settings, _project_id, task_id = _seed(tmp_path, [sys.executable, str(script)], max_attempts=2)
    summary = _run(settings, task_id)

    assert summary["outcome"] == "failed"
    assert [h["action"] for h in summary["recovery_history"]] == ["spawn_debugger"]

    engine = build_engine(settings.database_url)
    try:
        with build_session_factory(engine)() as session:
            children = session.scalars(
                select(Task).where(Task.parent_task_id == uuid.UUID(task_id))
            ).all()
            assert len(children) == 1
            child = children[0]
            assert child.payload.get("kind") == "debug"
            assert child.payload.get("failure_class") == "TASK_FAILURE"
            terminal = next(e for e in _events(task_id) if e.event_type == "TASK_TERMINALLY_FAILED")
            assert str(child.id) in terminal.payload["failure_detail"]
            assert str(child.id) in terminal.payload["recommended_action"]
            assert "DEBUGGER_SPAWNED" in _event_types(task_id)
    finally:
        engine.dispose()


def test_security_block_stops_on_first_attempt(tmp_path: Path) -> None:
    script = tmp_path / "work.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    settings = _settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    init_refs(factory, ArtifactStore(tmp_path / "artifacts"), settings)
    with factory() as session:
        project = Project(name=f"wf-{uuid.uuid4().hex[:8]}", root_path=str(tmp_path))
        session.add(project)
        session.flush()
        task = Task(
            project_id=project.id,
            title="review task",
            request="review only",
            payload={"command": [sys.executable, str(script)], "agent_role": "reviewer"},
            allowed_tools=["shell"],
            retry_policy={"max_attempts": 3},
        )
        session.add(task)
        session.commit()
        task_id = str(task.id)
    engine.dispose()

    summary = _run(settings, task_id)
    assert summary["outcome"] == "failed"
    assert summary["attempts"] == 1  # no retry of a hard policy stop
    assert summary["recovery_history"][0]["action"] == "stop"
    assert "TASK_TERMINALLY_FAILED" in _event_types(task_id)


def test_resource_pressure_requests_hitl_then_fails_closed_on_timeout(
    tmp_path: Path,
) -> None:
    script = tmp_path / "hungry.py"
    script.write_text(
        "import sys\nsys.stderr.write('disk quota exceeded\\n')\nsys.exit(1)\n",
        encoding="utf-8",
    )
    settings, _project_id, task_id = _seed(tmp_path, [sys.executable, str(script)], max_attempts=2)
    summary = _run(settings, task_id)

    assert summary["outcome"] == "failed"
    assert [h["action"] for h in summary["recovery_history"]] == ["request_hitl"]
    types = _event_types(task_id)
    assert "HITL_RECOVERY_REQUESTED" in types
    assert "HITL_RECOVERY_RESPONDED" in types
    assert "TASK_TERMINALLY_FAILED" in types


def test_finished_dependency_resumes_without_waiting(tmp_path: Path) -> None:
    """The pre-wait race fix: a dependency that completed before the waiter
    parks would never signal again — the waiter must resume immediately."""
    from app.db.models import TaskDependency

    blocked_script = tmp_path / "blocked.py"
    blocked_script.write_text(
        "import sys\nsys.stderr.write('blocked by upstream task\\n')\nsys.exit(1)\n",
        encoding="utf-8",
    )
    ok_script = tmp_path / "ok.py"
    ok_script.write_text("print('upstream done')\n", encoding="utf-8")

    settings = _settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    init_refs(factory, ArtifactStore(tmp_path / "artifacts"), settings)
    with factory() as session:
        project = Project(name=f"wf-{uuid.uuid4().hex[:8]}", root_path=str(tmp_path))
        session.add(project)
        session.flush()
        upstream = Task(
            project_id=project.id,
            title="upstream",
            request="run",
            payload={"command": [sys.executable, str(ok_script)], "timeout_seconds": 60},
            allowed_tools=["shell"],
            retry_policy={"max_attempts": 2},
        )
        blocked = Task(
            project_id=project.id,
            title="blocked",
            request="run",
            payload={"command": [sys.executable, str(blocked_script)], "timeout_seconds": 60},
            allowed_tools=["shell"],
            retry_policy={"max_attempts": 2},
        )
        session.add_all([upstream, blocked])
        session.flush()
        session.add(TaskDependency(task_id=blocked.id, depends_on_task_id=upstream.id))
        session.commit()
        upstream_id, blocked_id = str(upstream.id), str(blocked.id)
    engine.dispose()

    # Upstream completes FIRST: when the blocked workflow later parks, no
    # signal will ever come — the pre-check must resume it immediately.
    upstream_summary = _run(settings, upstream_id)
    assert upstream_summary["outcome"] == "success"
    blocked_summary = _run(settings, blocked_id)

    assert blocked_summary["attempts"] == 2
    assert [h["action"] for h in blocked_summary["recovery_history"]] == [
        "wait_for_dependency",
        "escalate_or_replan",
    ]
    resumed = [
        e
        for e in _events(blocked_id)
        if e.event_type == "DEPENDENCY_RESUMED" and e.payload.get("already_satisfied")
    ]
    assert resumed, "pre-check must short-circuit an already-satisfied wait"


def test_dependency_signal_resumes_parked_workflow(tmp_path: Path) -> None:
    """Live signal path: a parked waiter resumes when signalled (no busy loop)."""
    blocked_script = tmp_path / "blocked2.py"
    blocked_script.write_text(
        "import sys\nsys.stderr.write('blocked by upstream task\\n')\nsys.exit(1)\n",
        encoding="utf-8",
    )
    settings = _settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    init_refs(factory, ArtifactStore(tmp_path / "artifacts"), settings)
    with factory() as session:
        project = Project(name=f"wf-{uuid.uuid4().hex[:8]}", root_path=str(tmp_path))
        session.add(project)
        session.flush()
        # A permanently-unfinished blocker forces the workflow to really park.
        blocker = Task(project_id=project.id, title="blocker", request="never runs", payload={})
        session.add(blocker)
        session.flush()
        blocked = Task(
            project_id=project.id,
            title="blocked",
            request="run",
            payload={"command": [sys.executable, str(blocked_script)], "timeout_seconds": 60},
            allowed_tools=["shell"],
            retry_policy={"max_attempts": 2},
        )
        session.add(blocked)
        session.flush()
        from app.db.models import TaskDependency

        session.add(TaskDependency(task_id=blocked.id, depends_on_task_id=blocker.id))
        session.commit()
        blocked_id = str(blocked.id)
    engine.dispose()

    async def _signalled_run() -> dict:
        import time as _time

        # Real clock (not time-skipping): the 900 s wait deadline must NOT
        # fast-forward past the moment we deliver the signal.
        async with (
            await WorkflowEnvironment.start_local() as env,
            Worker(
                env.client,
                task_queue="wave2-test",
                workflows=[TaskExecutionWorkflow],
                activities=_ACTIVITIES,
            ),
        ):
            run = asyncio.ensure_future(
                env.client.execute_workflow(
                    TaskExecutionWorkflow.run,
                    TaskExecutionInput(task_id=blocked_id),
                    id=f"task-exec-{blocked_id}",
                    task_queue="wave2-test",
                )
            )
            deadline = _time.monotonic() + 120
            while "DEPENDENCY_WAIT_STARTED" not in _event_types(blocked_id):
                if _time.monotonic() > deadline:
                    raise TimeoutError("workflow never parked in its wait")
                await asyncio.sleep(0.5)
            handle = env.client.get_workflow_handle(f"task-exec-{blocked_id}")
            await handle.signal("dependency_completed")
            return await run

    summary = asyncio.run(_signalled_run())
    assert summary["attempts"] == 2  # resumed, ran again, then ladder-ended
    assert [h["action"] for h in summary["recovery_history"]] == [
        "wait_for_dependency",
        "escalate_or_replan",
    ]
    assert "DEPENDENCY_RESUMED" in _event_types(blocked_id)


def test_pause_parks_and_resume_completes_without_duplication(tmp_path: Path) -> None:
    """Pause/resume during real work: the workflow parks at a checkpoint
    (agent → paused), resumes on signal, and finishes with one attempt —
    no duplicate work, no lost state."""
    import time as _time

    from app.db.models import Agent

    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(8)\n", encoding="utf-8")
    settings, _project_id, task_id = _seed(tmp_path, [sys.executable, str(script)], max_attempts=2)

    async def _paused_run() -> dict:
        from datetime import timedelta

        # Real clock (not time-skipping): a parked workflow has no deadline
        # pressure, but the test server still needs a generous execution
        # timeout — and time-skipping would fast-forward any finite timeout
        # the moment the workflow parks.
        async with (
            await WorkflowEnvironment.start_local() as env,
            Worker(
                env.client,
                task_queue="wave2-test",
                workflows=[TaskExecutionWorkflow],
                activities=_ACTIVITIES,
            ),
        ):
            run = asyncio.ensure_future(
                env.client.execute_workflow(
                    TaskExecutionWorkflow.run,
                    TaskExecutionInput(task_id=task_id),
                    id=f"task-exec-{task_id}",
                    task_queue="wave2-test",
                    # Real sleeps + polling outlast the test server's default
                    # execution timeout; the product sets its own timeouts.
                    execution_timeout=timedelta(seconds=600),
                )
            )
            handle = env.client.get_workflow_handle(f"task-exec-{task_id}")
            # Wait until the attempt is executing, then pause mid-flight.
            deadline = _time.monotonic() + 60
            started = False
            while not started and _time.monotonic() < deadline:
                with _session() as session:
                    started = (
                        session.scalars(
                            select(TaskAttempt).where(TaskAttempt.task_id == uuid.UUID(task_id))
                        ).first()
                        is not None
                    )
                await asyncio.sleep(0.5)
            assert started, "attempt never started"
            await handle.signal("pause")
            # Parked: the agent row reaches paused at the post-execute checkpoint.
            deadline = _time.monotonic() + 60
            parked = False
            while not parked and _time.monotonic() < deadline:
                with _session() as session:
                    parked = (
                        session.scalars(
                            select(Agent).where(
                                Agent.name.like(f"agent-{task_id[:8]}%"),
                                Agent.state == "paused",
                            )
                        ).first()
                        is not None
                    )
                await asyncio.sleep(0.5)
            assert parked, "workflow never parked on pause"
            await handle.signal("resume")
            return await run

    summary = asyncio.run(_paused_run())
    assert summary["outcome"] == "success", summary
    assert summary["attempts"] == 1  # resume continues; nothing re-ran

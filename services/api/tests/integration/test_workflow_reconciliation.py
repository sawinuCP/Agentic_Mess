"""Workflow failure reconciliation (backend trust hardening).

A failed Temporal run must never orphan its task in a non-terminal state
with zero product signal: the workflow safety net finishes the open attempt,
records the terminal failure (idempotent), moves the task to failed
(cancelled when it never started), and emits TASK_FAILED — then re-raises so
the Temporal run status stays truthful.

Runs against the time-skipping test server with real activities and the live
database, following tests/integration/test_recovery_workflow.py.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.artifacts.store import ArtifactStore
from app.core.config import Settings
from app.db.base import build_engine, build_session_factory
from app.db.models import Event, Project, Task, TaskAttempt
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

_BASE_ACTIVITIES = [
    load_task_activity,
    start_attempt_activity,
    agent_execute_activity,
    execute_work_activity,
    finish_attempt_activity,
    set_agent_state_activity,
    set_task_status_activity,
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
    base: dict[str, object] = {
        "environment": "test",
        "log_level": "WARNING",
        "otel_enabled": False,
        "nats_events_enabled": False,
        "temporal_enabled": False,
        "hitl_timeout_seconds": 3.0,
        "hitl_poll_seconds": 0.2,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def _seed(root: Path, command: list[str], *, max_attempts: int = 1) -> tuple[str, str]:
    settings = _settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    init_refs(factory, ArtifactStore(root / "artifacts"), settings)
    with factory() as session:
        project = Project(name=f"reconcile-{uuid.uuid4().hex[:8]}", root_path=str(root))
        session.add(project)
        session.flush()
        task = Task(
            project_id=project.id,
            title="reconciliation task",
            request="run",
            payload={"command": command, "timeout_seconds": 60},
            allowed_tools=["shell"],
            retry_policy={"max_attempts": max_attempts},
        )
        session.add(task)
        session.commit()
        ids = str(project.id), str(task.id)
    engine.dispose()
    return ids


def _read(task_id: str) -> tuple[Task, list[TaskAttempt], list[str]]:
    settings = _settings()
    engine = build_engine(settings.database_url)
    try:
        with build_session_factory(engine)() as session:
            task = session.get(Task, uuid.UUID(task_id))
            assert task is not None
            attempts = session.scalars(
                select(TaskAttempt)
                .where(TaskAttempt.task_id == task.id)
                .order_by(TaskAttempt.attempt_number)
            ).all()
            types = session.scalars(
                select(Event.event_type).where(Event.task_id == task.id)
            ).all()
            session.expunge_all()
            return task, list(attempts), [str(t) for t in types]
    finally:
        engine.dispose()


async def _execute(task_id: str, activities: list[Any]) -> dict:
    async with (
        await WorkflowEnvironment.start_time_skipping() as env,
        Worker(
            env.client,
            task_queue="reconcile-test",
            workflows=[TaskExecutionWorkflow],
            activities=activities,
        ),
    ):
        return await env.client.execute_workflow(
            TaskExecutionWorkflow.run,
            TaskExecutionInput(task_id=task_id),
            id=f"task-exec-{task_id}",
            task_queue="reconcile-test",
        )


def test_success_leaves_no_unfinished_attempt(tmp_path: Path) -> None:
    """Invariant 2: a completed task has no unfinished terminal attempt."""
    script = tmp_path / "ok.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    _, task_id = _seed(tmp_path, [sys.executable, str(script)])
    summary = asyncio.run(_execute(task_id, _BASE_ACTIVITIES))
    assert summary["outcome"] == "success"
    task, attempts, types = _read(task_id)
    assert task.status == "completed"
    assert attempts and all(a.outcome is not None and a.finished_at is not None for a in attempts)
    assert "TASK_COMPLETED" in types


def test_terminal_workflow_failure_reconciles(tmp_path: Path) -> None:
    """Invariant 1: an unhandled run-body error marks the task failed with a
    terminal attempt, classification, and durable events — then re-raises."""
    script = tmp_path / "ok.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    _, task_id = _seed(tmp_path, [sys.executable, str(script)])

    calls = {"n": 0}

    @activity.defn(name="finish_attempt_activity")
    async def flaky_finish(input: dict[str, Any]) -> None:
        # Exhaust the workflow's RETRY_DB budget (3 attempts), then behave so
        # the safety net's own cleanup call succeeds through the same name.
        calls["n"] += 1
        if calls["n"] <= 3:
            raise RuntimeError("boom")
        return await finish_attempt_activity(input)

    activities = [a if a is not finish_attempt_activity else flaky_finish for a in _BASE_ACTIVITIES]
    with pytest.raises(WorkflowFailureError):
        asyncio.run(_execute(task_id, activities))

    task, attempts, types = _read(task_id)
    assert task.status == "failed", "reconciled task must not stay running"
    assert len(attempts) == 1
    assert attempts[0].outcome == "failed"
    assert attempts[0].failure_class == "TASK_FAILURE"
    assert attempts[0].finished_at is not None
    assert "TASK_TERMINALLY_FAILED" in types
    assert "TASK_FAILED" in types


def test_terminal_task_state_wins(tmp_path: Path) -> None:
    """Reconciliation never rewrites an already-terminal task: executing a
    completed task fails the run (unlawful transition) but changes nothing."""
    script = tmp_path / "ok.py"
    script.write_text("print('ok')\n", encoding="utf-8")
    _, task_id = _seed(tmp_path, [sys.executable, str(script)])
    asyncio.run(_execute(task_id, _BASE_ACTIVITIES))
    _, _, before = _read(task_id)
    assert "TASK_COMPLETED" in before
    with pytest.raises(WorkflowFailureError):
        asyncio.run(_execute(task_id, _BASE_ACTIVITIES))
    task, attempts, types = _read(task_id)
    assert task.status == "completed"
    assert [t for t in types if t == "TASK_FAILED"] == []
    assert all(a.outcome == "success" for a in attempts)

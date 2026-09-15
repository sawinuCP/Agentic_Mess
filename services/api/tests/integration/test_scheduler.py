"""Scheduler integration tests (FR-009/011, PERF-003): limits, roles, leases, commit."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI

from app.db.models import Event, Task
from app.services.scheduler import SchedulingLimits, commit_scheduled, plan_schedule

pytestmark = pytest.mark.integration


def _limits(**overrides: object) -> SchedulingLimits:
    values: dict[str, object] = {"max_concurrency": 4, "role_limits": {}, "spawn_max_depth": 2}
    values.update(overrides)
    return SchedulingLimits(
        max_concurrency=values["max_concurrency"],  # type: ignore[arg-type]
        role_limits=values["role_limits"],  # type: ignore[arg-type]
        spawn_max_depth=values["spawn_max_depth"],  # type: ignore[arg-type]
    )


def _add_task(
    app: FastAPI,
    project_id: str,
    title: str,
    *,
    priority: int = 5,
    payload: dict | None = None,
    status: str = "ready",
) -> str:
    with app.state.session_factory() as session:
        task = Task(
            project_id=uuid.UUID(project_id),
            title=title,
            request="scheduler work",
            priority=priority,
            status=status,
            payload=payload or {},
        )
        session.add(task)
        session.commit()
        return str(task.id)


def test_plan_respects_global_concurrency_limit(project: tuple) -> None:
    _app, _client, project_id, _tmp = project
    _add_task(_app, project_id, "p5", priority=5)
    _add_task(_app, project_id, "p4", priority=4)
    _add_task(_app, project_id, "p3", priority=3)
    with _app.state.session_factory() as session:
        tick = plan_schedule(session, uuid.UUID(project_id), _limits(max_concurrency=2))
    assert [entry.title for entry in tick.scheduled] == ["p3", "p4"]  # priority order
    assert len(tick.skipped) == 1
    assert "global concurrency limit" in tick.skipped[0].reason


def test_same_role_runs_concurrently_without_role_cap(project: tuple) -> None:
    """FR-009: multiple concurrent instances of the same role are allowed."""
    _app, _client, project_id, _tmp = project
    _add_task(_app, project_id, "impl-1", payload={"role": "implementer"})
    _add_task(_app, project_id, "impl-2", payload={"role": "implementer"})
    with _app.state.session_factory() as session:
        tick = plan_schedule(session, uuid.UUID(project_id), _limits())
    assert [entry.title for entry in tick.scheduled] == ["impl-1", "impl-2"]


def test_role_limit_caps_concurrent_instances(project: tuple) -> None:
    _app, _client, project_id, _tmp = project
    _add_task(_app, project_id, "impl-1", payload={"role": "implementer"})
    _add_task(_app, project_id, "impl-2", payload={"role": "implementer"})
    _add_task(_app, project_id, "test-1", payload={"role": "tester"})
    with _app.state.session_factory() as session:
        tick = plan_schedule(
            session,
            uuid.UUID(project_id),
            _limits(role_limits={"implementer": 1, "tester": 1}),
        )
    assert [entry.title for entry in tick.scheduled] == ["impl-1", "test-1"]
    assert "role limit" in tick.skipped[0].reason


def test_spawn_depth_bound_skips_over_deep_tasks(project: tuple) -> None:
    _app, _client, project_id, _tmp = project
    _add_task(_app, project_id, "deep", payload={"spawn_depth": 3})
    _add_task(_app, project_id, "top", payload={})
    with _app.state.session_factory() as session:
        tick = plan_schedule(session, uuid.UUID(project_id), _limits(spawn_max_depth=2))
    assert [entry.title for entry in tick.scheduled] == ["top"]
    assert "spawn depth" in tick.skipped[0].reason


def test_actively_leased_resource_skips_task(project: tuple) -> None:
    app, client, project_id, _tmp = project
    from app.schemas.leases import LeaseIn
    from app.services import leases as lease_service

    lease_key = f"res-{uuid.uuid4().hex[:8]}"
    _add_task(
        app,
        project_id,
        "conflicting",
        payload={"resource_requirements": [{"kind": "branch", "key": lease_key}]},
    )
    _add_task(app, project_id, "free")

    with app.state.session_factory() as session:
        lease_service.acquire(
            session, uuid.UUID(project_id), LeaseIn(kind="branch", key=lease_key, ttl_seconds=300)
        )
        blocked = plan_schedule(session, uuid.UUID(project_id), _limits())
    assert [entry.title for entry in blocked.scheduled] == ["free"]
    assert "actively leased" in blocked.skipped[0].reason

    for lease in client.get(f"/api/projects/{project_id}/leases").json():
        assert client.post(f"/api/leases/{lease['id']}/release").status_code == 200
    with app.state.session_factory() as session:
        unblocked = plan_schedule(session, uuid.UUID(project_id), _limits())
    assert [entry.title for entry in unblocked.scheduled] == ["conflicting", "free"]


def test_commit_scheduled_marks_running_and_emits_event(project: tuple) -> None:
    app, _client, project_id, _tmp = project
    task_id = uuid.UUID(_add_task(app, project_id, "committed"))
    with app.state.session_factory() as session:
        assert commit_scheduled(session, uuid.UUID(project_id), {task_id: "wf-1"}) == 1
        task = session.get(Task, task_id)
        assert task is not None and task.status == "running"
        event = session.query(Event).filter_by(task_id=task_id, event_type="TASK_SCHEDULED").one()
        assert event.payload["workflow_id"] == "wf-1"
        # Idempotent: a second commit for the same task changes nothing.
        assert commit_scheduled(session, uuid.UUID(project_id), {task_id: "wf-1"}) == 0


def test_scheduler_tick_fails_closed_without_temporal(project: tuple) -> None:
    _app, client, project_id, _tmp = project
    _add_task(_app, project_id, "never-started")
    response = client.post(f"/api/projects/{project_id}/scheduler/tick")
    assert response.status_code == 503
    assert "Temporal" in response.json()["detail"]


def test_scheduler_state_endpoint(project: tuple) -> None:
    app, client, project_id, _tmp = project
    _add_task(app, project_id, "one")
    _add_task(app, project_id, "two", payload={"role": "tester"})
    state = client.get(f"/api/projects/{project_id}/scheduler/state")
    assert state.status_code == 200
    body = state.json()
    assert body["tasks_by_status"]["ready"] == 2
    assert body["limits"]["max_concurrency"] == app.state.settings.scheduler_max_concurrency

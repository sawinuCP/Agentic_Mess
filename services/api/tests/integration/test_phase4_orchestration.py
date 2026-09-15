"""Phase-4 orchestration integration: resource leases, scheduler, message fan-out."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.models import Event, Resource, Task
from app.messaging.broker import MessageEnvelope, subject_for
from app.schemas.leases import LeaseIn
from app.schemas.messages import MessageIn
from app.services import leases as lease_service
from app.services import messages as message_service
from app.services.scheduler import SchedulingLimits, commit_scheduled, plan_schedule

pytestmark = pytest.mark.integration

# Lease keys live in one global namespace per kind — tests use run-unique keys so
# re-runs against the same database never collide with a previous run's leases.
_RUN = uuid.uuid4().hex[:8]


@pytest.fixture()
def wired(app: FastAPI, tmp_path: Path) -> Iterator[tuple[FastAPI, TestClient, str, Path]]:
    with TestClient(app) as client:
        response = client.post("/api/projects/open", json={"root_path": str(tmp_path)})
        yield app, client, response.json()["id"], tmp_path


def _limits(**overrides: Any) -> SchedulingLimits:
    values: dict[str, Any] = {"max_concurrency": 4, "role_limits": {}, "spawn_max_depth": 2}
    values.update(overrides)
    return SchedulingLimits(
        max_concurrency=values["max_concurrency"],
        role_limits=values["role_limits"],
        spawn_max_depth=values["spawn_max_depth"],
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
            request="phase4 work",
            priority=priority,
            status=status,
            payload=payload or {},
        )
        session.add(task)
        session.commit()
        return str(task.id)


# --- Resource leases (spec §18) -------------------------------------------------


def test_lease_acquire_conflicts_then_releases(wired: tuple) -> None:
    _app, client, project_id, _tmp = wired
    first = client.post(
        f"/api/projects/{project_id}/leases",
        json={"kind": "branch", "key": f"main-{_RUN}", "ttl_seconds": 300},
    )
    assert first.status_code == 201
    assert first.json()["status"] == "active"

    conflict = client.post(
        f"/api/projects/{project_id}/leases",
        json={"kind": "branch", "key": f"main-{_RUN}", "ttl_seconds": 300},
    )
    assert conflict.status_code == 409
    assert "actively leased" in conflict.json()["detail"]

    other = client.post(
        f"/api/projects/{project_id}/leases",
        json={"kind": "branch", "key": f"feature-{_RUN}", "ttl_seconds": 300},
    )
    assert other.status_code == 201  # distinct resources never conflict

    released = client.post(f"/api/leases/{first.json()['id']}/release")
    assert released.status_code == 200
    assert released.json()["status"] == "released"

    reacquire = client.post(
        f"/api/projects/{project_id}/leases",
        json={"kind": "branch", "key": f"main-{_RUN}", "ttl_seconds": 300},
    )
    assert reacquire.status_code == 201


def test_lease_renewal_requires_the_holder(wired: tuple) -> None:
    _app, client, project_id, _tmp = wired
    agent_a = client.post(
        f"/api/projects/{project_id}/agents", json={"name": "a", "role": "implementer"}
    ).json()["id"]
    agent_b = client.post(
        f"/api/projects/{project_id}/agents", json={"name": "b", "role": "implementer"}
    ).json()["id"]
    lease = client.post(
        f"/api/projects/{project_id}/leases",
        json={
            "kind": "tool",
            "key": f"linter-{_RUN}",
            "holder_agent_id": agent_a,
            "ttl_seconds": 300,
        },
    ).json()

    denied = client.post(f"/api/leases/{lease['id']}/renew", json={"holder_agent_id": agent_b})
    assert denied.status_code == 409

    renewed = client.post(
        f"/api/leases/{lease['id']}/renew", json={"holder_agent_id": agent_a, "ttl_seconds": 600}
    )
    assert renewed.status_code == 200
    assert renewed.json()["ttl_seconds"] == 600
    assert renewed.json()["expires_at"] > lease["expires_at"]


def test_lease_release_denied_for_non_holder(wired: tuple) -> None:
    _app, client, project_id, _tmp = wired
    agent_a = client.post(
        f"/api/projects/{project_id}/agents", json={"name": "a", "role": "implementer"}
    ).json()["id"]
    agent_b = client.post(
        f"/api/projects/{project_id}/agents", json={"name": "b", "role": "implementer"}
    ).json()["id"]
    lease = client.post(
        f"/api/projects/{project_id}/leases",
        json={"kind": "port", "key": f"port-{_RUN}", "holder_agent_id": agent_a},
    ).json()
    stolen = client.post(f"/api/leases/{lease['id']}/release?holder_agent_id={agent_b}")
    assert stolen.status_code == 409
    released = client.post(f"/api/leases/{lease['id']}/release?holder_agent_id={agent_a}")
    assert released.status_code == 200


def test_expired_lease_is_reported_expired_and_taken_over(wired: tuple) -> None:
    app, client, project_id, _tmp = wired
    lease = client.post(
        f"/api/projects/{project_id}/leases",
        json={"kind": "worktree", "key": f"wt-{_RUN}", "ttl_seconds": 5},
    ).json()
    with app.state.session_factory() as session:
        row = session.get(Resource, uuid.UUID(lease["id"]))
        assert row is not None
        row.acquired_at = datetime.now(UTC) - timedelta(seconds=600)
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    listed = client.get(f"/api/projects/{project_id}/leases?status=active")
    assert listed.status_code == 200
    assert listed.json() == []  # computed status: expired, not active

    expired = client.post("/api/leases/expire-stale")
    assert expired.status_code == 200
    assert expired.json()["expired"] >= 1

    takeover = client.post(
        f"/api/projects/{project_id}/leases",
        json={"kind": "worktree", "key": f"wt-{_RUN}", "ttl_seconds": 300},
    )
    assert takeover.status_code == 201  # spec §18: expired leases may be re-acquired


def test_lease_batch_is_all_or_nothing(wired: tuple) -> None:
    app, client, project_id, _tmp = wired
    with app.state.session_factory() as session:
        held = lease_service.acquire(
            session,
            uuid.UUID(project_id),
            LeaseIn(kind="file", key=f"locked-{_RUN}.py", ttl_seconds=300),
        )
        assert held.status == "active"

    batch = client.post(
        f"/api/projects/{project_id}/leases/batch",
        json={
            "leases": [
                {"kind": "file", "key": f"free-{_RUN}.py", "ttl_seconds": 300},
                {"kind": "file", "key": f"locked-{_RUN}.py", "ttl_seconds": 300},
            ]
        },
    )
    assert batch.status_code == 409

    listed = client.get(f"/api/projects/{project_id}/leases").json()
    keys = {lease["key"] for lease in listed}
    assert f"free-{_RUN}.py" not in keys  # rolled back — the whole batch is abandoned


def test_deterministic_batch_acquisition_order(wired: tuple) -> None:
    _app, client, project_id, _tmp = wired
    batch = client.post(
        f"/api/projects/{project_id}/leases/batch",
        json={
            "leases": [
                {"kind": "file", "key": f"b-{_RUN}.py", "ttl_seconds": 300},
                {"kind": "file", "key": f"a-{_RUN}.py", "ttl_seconds": 300},
            ]
        },
    )
    assert batch.status_code == 201
    assert [lease["key"] for lease in batch.json()] == [f"a-{_RUN}.py", f"b-{_RUN}.py"]


# --- Scheduler (FR-009/011, PERF-003) -------------------------------------------


def test_plan_respects_global_concurrency_limit(wired: tuple) -> None:
    _app, _client, project_id, _tmp = wired
    _add_task(_app, project_id, "p5", priority=5)
    _add_task(_app, project_id, "p4", priority=4)
    _add_task(_app, project_id, "p3", priority=3)
    with _app.state.session_factory() as session:
        tick = plan_schedule(session, uuid.UUID(project_id), _limits(max_concurrency=2))
    assert [entry.title for entry in tick.scheduled] == ["p3", "p4"]  # priority order
    assert len(tick.skipped) == 1
    assert "global concurrency limit" in tick.skipped[0].reason


def test_same_role_runs_concurrently_without_role_cap(wired: tuple) -> None:
    """FR-009: multiple concurrent instances of the same role are allowed."""
    _app, _client, project_id, _tmp = wired
    _add_task(_app, project_id, "impl-1", payload={"role": "implementer"})
    _add_task(_app, project_id, "impl-2", payload={"role": "implementer"})
    with _app.state.session_factory() as session:
        tick = plan_schedule(session, uuid.UUID(project_id), _limits())
    assert [entry.title for entry in tick.scheduled] == ["impl-1", "impl-2"]


def test_role_limit_caps_concurrent_instances(wired: tuple) -> None:
    _app, _client, project_id, _tmp = wired
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


def test_spawn_depth_bound_skips_over_deep_tasks(wired: tuple) -> None:
    _app, _client, project_id, _tmp = wired
    _add_task(_app, project_id, "deep", payload={"spawn_depth": 3})
    _add_task(_app, project_id, "top", payload={})
    with _app.state.session_factory() as session:
        tick = plan_schedule(session, uuid.UUID(project_id), _limits(spawn_max_depth=2))
    assert [entry.title for entry in tick.scheduled] == ["top"]
    assert "spawn depth" in tick.skipped[0].reason


def test_actively_leased_resource_skips_task(wired: tuple) -> None:
    app, client, project_id, _tmp = wired
    lease_key = f"res-{_RUN}"
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


def test_commit_scheduled_marks_running_and_emits_event(wired: tuple) -> None:
    app, _client, project_id, _tmp = wired
    task_id = uuid.UUID(_add_task(app, project_id, "committed"))
    with app.state.session_factory() as session:
        assert commit_scheduled(session, uuid.UUID(project_id), {task_id: "wf-1"}) == 1
        assert session.get(Task, task_id).status == "running"
        event = session.query(Event).filter_by(task_id=task_id, event_type="TASK_SCHEDULED").one()
        assert event.payload["workflow_id"] == "wf-1"
        # Idempotent: a second commit for the same task changes nothing.
        assert commit_scheduled(session, uuid.UUID(project_id), {task_id: "wf-1"}) == 0


def test_scheduler_tick_fails_closed_without_temporal(wired: tuple) -> None:
    _app, client, project_id, _tmp = wired
    _add_task(_app, project_id, "never-started")
    response = client.post(f"/api/projects/{project_id}/scheduler/tick")
    assert response.status_code == 503
    assert "Temporal" in response.json()["detail"]


def test_scheduler_state_endpoint(wired: tuple) -> None:
    app, client, project_id, _tmp = wired
    _add_task(app, project_id, "one")
    _add_task(app, project_id, "two", payload={"role": "tester"})
    state = client.get(f"/api/projects/{project_id}/scheduler/state")
    assert state.status_code == 200
    body = state.json()
    assert body["tasks_by_status"]["ready"] == 2
    assert body["limits"]["max_concurrency"] == app.state.settings.scheduler_max_concurrency


# --- Message delivery fan-out (FR-010) ------------------------------------------


def test_delivery_disabled_fails_closed_and_keeps_messages_pending(wired: tuple) -> None:
    _app, client, project_id, _tmp = wired
    sent = client.post("/api/messages", json={"type": "request", "payload": {"hello": True}})
    assert sent.status_code == 201
    assert sent.json()["delivered_at"] is None

    response = client.post("/api/messages/deliver-pending")
    assert response.status_code == 503
    assert "NATS" in response.json()["detail"]

    conversation = sent.json()["conversation_id"]
    replayed = client.get(f"/api/conversations/{conversation}/messages").json()
    assert replayed and replayed[0]["delivered_at"] is None  # durable record untouched


def test_delivery_fan_out_marks_delivered_with_fake_broker(
    wired: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    _app, client, project_id, _tmp = wired
    published: list[MessageEnvelope] = []

    class FakeBroker:
        async def publish(self, envelope: MessageEnvelope) -> None:
            published.append(envelope)

        async def close(self) -> None:
            return None

    monkeypatch.setattr("app.api.routes.messages.build_broker", lambda _settings: FakeBroker())

    recipient = client.post(
        f"/api/projects/{project_id}/agents", json={"name": "receiver", "role": "implementer"}
    ).json()["id"]
    direct = client.post(
        "/api/messages",
        json={"type": "request", "recipient_agent_id": recipient, "payload": {}},
    ).json()
    client.post("/api/messages", json={"type": "broadcast", "payload": {}})

    result = client.post("/api/messages/deliver-pending")
    assert result.status_code == 200
    body = result.json()
    # The fan-out pass is global: every pending message gets delivered, ours included.
    assert body["delivered_count"] >= 2 and body["failed_count"] == 0
    assert {subject_for(env, "harness.msg") for env in published} >= {
        f"harness.msg.agent.{direct['recipient_agent_id']}",
        "harness.msg.broadcast",
    }

    replayed = client.get(f"/api/conversations/{direct['conversation_id']}/messages").json()
    assert replayed[0]["delivered_at"] is not None

    again = client.post("/api/messages/deliver-pending").json()
    assert again["pending_count"] == 0 and again["delivered_count"] == 0


def test_message_service_envelope_roundtrip(wired: tuple) -> None:
    app, _client, project_id, _tmp = wired
    with app.state.session_factory() as session:
        sent = message_service.send_message(session, MessageIn(type="question", payload={"q": 1}))
        rows = message_service.pending_messages(session, 10)
        envelope = message_service.envelope_from(rows[0])
        assert envelope.message_id == sent.id
        assert envelope.type == "question"

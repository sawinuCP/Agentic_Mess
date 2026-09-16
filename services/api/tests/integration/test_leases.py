"""Resource-lease integration tests (spec §18, FR-011): TTL, renewal, release, expiry."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.models import Resource
from app.schemas.orchestration.leases import LeaseIn
from app.services.orchestration import leases as lease_service

pytestmark = pytest.mark.integration

# Lease keys live in one global namespace per kind — tests use run-unique keys so
# re-runs against the same database never collide with a previous run's leases.
_RUN = uuid.uuid4().hex[:8]


def test_lease_acquire_conflicts_then_releases(project: tuple) -> None:
    _app, client, project_id, _tmp = project
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


def _two_agents(client: TestClient, project_id: str) -> tuple[str, str]:
    def _agent(name: str) -> str:
        return client.post(
            f"/api/projects/{project_id}/agents", json={"name": name, "role": "implementer"}
        ).json()["id"]

    return _agent("a"), _agent("b")


def test_lease_renewal_requires_the_holder(project: tuple) -> None:
    _app, client, project_id, _tmp = project
    agent_a, agent_b = _two_agents(client, project_id)
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


def test_lease_release_denied_for_non_holder(project: tuple) -> None:
    _app, client, project_id, _tmp = project
    agent_a, agent_b = _two_agents(client, project_id)
    lease = client.post(
        f"/api/projects/{project_id}/leases",
        json={"kind": "port", "key": f"port-{_RUN}", "holder_agent_id": agent_a},
    ).json()
    stolen = client.post(f"/api/leases/{lease['id']}/release?holder_agent_id={agent_b}")
    assert stolen.status_code == 409
    released = client.post(f"/api/leases/{lease['id']}/release?holder_agent_id={agent_a}")
    assert released.status_code == 200


def test_expired_lease_is_reported_expired_and_taken_over(project: tuple) -> None:
    app, client, project_id, _tmp = project
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


def test_lease_batch_is_all_or_nothing(project: tuple) -> None:
    app, client, project_id, _tmp = project
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


def test_deterministic_batch_acquisition_order(project: tuple) -> None:
    _app, client, project_id, _tmp = project
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

"""Port allocator integration (spec §19.1): range scan, bind probe, TTL, release."""

from __future__ import annotations

import socket
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db.models import PortAllocation
from app.services.execution import ports as port_service

pytestmark = pytest.mark.integration


@pytest.fixture()
def port_range() -> tuple[int, int]:
    """A run-unique 4-port window per test — the active ledger is global, so
    tests must never share a range (cross-test interference otherwise)."""
    base = 30000 + (int(uuid.uuid4().hex[:4], 16) % 20000)
    return base, base + 3


def test_allocate_picks_free_bindable_ports_in_range(
    project: tuple, port_range: tuple[int, int]
) -> None:
    app, _client, project_id, _tmp = project
    low, high = port_range
    first = port_service.allocate(
        app.state.session_factory(),
        uuid.UUID(project_id),
        purpose="preview",
        holder=None,
        ttl_seconds=300,
        port_low=low,
        port_high=high,
    )
    second = port_service.allocate(
        app.state.session_factory(),
        uuid.UUID(project_id),
        purpose="service",
        holder=None,
        ttl_seconds=300,
        port_low=low,
        port_high=high,
    )
    assert low <= first["port"] <= high
    assert second["port"] != first["port"]
    assert first["status"] == "active"


def test_bind_probe_skips_occupied_ports(project: tuple, port_range: tuple[int, int]) -> None:
    """A port occupied by a real socket is skipped even if not in the ledger."""
    app, _client, project_id, _tmp = project
    low, high = port_range
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", low))
    blocker.listen(1)
    try:
        allocation = port_service.allocate(
            app.state.session_factory(),
            uuid.UUID(project_id),
            purpose="preview",
            holder=None,
            ttl_seconds=300,
            port_low=low,
            port_high=high,
        )
        assert allocation["port"] != low  # bind probe skipped the occupied port
    finally:
        blocker.close()


def test_preferred_port_falls_back_when_taken(project: tuple, port_range: tuple[int, int]) -> None:
    app, _client, project_id, _tmp = project
    low, high = port_range
    first = port_service.allocate(
        app.state.session_factory(),
        uuid.UUID(project_id),
        purpose="preview",
        holder=None,
        ttl_seconds=300,
        port_low=low,
        port_high=high,
    )
    # A preferred port that is already allocated falls back to the next free one.
    second = port_service.allocate(
        app.state.session_factory(),
        uuid.UUID(project_id),
        purpose="service",
        holder=None,
        ttl_seconds=300,
        port_low=low,
        port_high=high,
        preferred_port=first["port"],
    )
    assert second["port"] != first["port"]


def test_out_of_range_preferred_port_rejected(project: tuple, port_range: tuple[int, int]) -> None:
    app, _client, project_id, _tmp = project
    low, high = port_range
    with pytest.raises(port_service.DomainError) as excinfo:
        port_service.allocate(
            app.state.session_factory(),
            uuid.UUID(project_id),
            purpose="service",
            holder=None,
            ttl_seconds=300,
            port_low=low,
            port_high=high,
            preferred_port=high + 500,
        )
    assert excinfo.value.status_code == 422


def test_release_then_reallocate_the_same_port(project: tuple, port_range: tuple[int, int]) -> None:
    app, _client, project_id, _tmp = project
    low, _high = port_range
    allocation = port_service.allocate(
        app.state.session_factory(),
        uuid.UUID(project_id),
        purpose="debug",
        holder="agent-1",
        ttl_seconds=300,
        port_low=low,
        port_high=low,
    )
    released = port_service.release(
        app.state.session_factory(), uuid.UUID(allocation["id"]), "agent-1"
    )
    assert released["status"] == "released"

    again = port_service.allocate(
        app.state.session_factory(),
        uuid.UUID(project_id),
        purpose="debug",
        holder="agent-2",
        ttl_seconds=300,
        port_low=low,
        port_high=low,
    )
    assert again["port"] == low  # the released port is reusable


def test_ttl_expiry_frees_the_port(project: tuple, port_range: tuple[int, int]) -> None:
    app, _client, project_id, _tmp = project
    low, _high = port_range
    allocation = port_service.allocate(
        app.state.session_factory(),
        uuid.UUID(project_id),
        purpose="test",
        holder=None,
        ttl_seconds=5,
        port_low=low,
        port_high=low,
    )
    with app.state.session_factory() as session:
        row = session.get(PortAllocation, uuid.UUID(allocation["id"]))
        assert row is not None
        row.allocated_at = datetime.now(UTC) - timedelta(seconds=600)
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    expired = port_service.expire_stale(app.state.session_factory())
    assert expired["expired"] >= 1

    re_request = port_service.allocate(
        app.state.session_factory(),
        uuid.UUID(project_id),
        purpose="test",
        holder=None,
        ttl_seconds=300,
        port_low=low,
        port_high=low,
    )
    assert re_request["port"] == low


def test_port_api_endpoints(project: tuple) -> None:
    app, client, project_id, _tmp = project
    allocated = client.post(
        f"/api/projects/{project_id}/ports", json={"purpose": "preview", "ttl_seconds": 300}
    )
    assert allocated.status_code == 201
    port = allocated.json()["port"]
    assert 21000 <= port <= 21999  # configured default range

    listed = client.get(f"/api/projects/{project_id}/ports?status=active").json()
    assert any(entry["port"] == port for entry in listed)

    renewed = client.post(f"/api/ports/{allocated.json()['id']}/renew", json={"ttl_seconds": 600})
    assert renewed.status_code == 200
    assert renewed.json()["ttl_seconds"] == 600

    released = client.post(f"/api/ports/{allocated.json()['id']}/release")
    assert released.status_code == 200 and released.json()["status"] == "released"

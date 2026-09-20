"""Wave 3 integration: SSE realtime gateway (`GET /api/events/stream`).

Auth/routing tests use TestClient (buffered — fine for responses that end
before streaming). Streaming behavior uses the ``sse`` ASGI harness fixture,
which exercises the real middleware stack and incremental frames.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from conftest import AUTH_TEST_TOKEN, SseTestClient
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app

pytestmark = pytest.mark.integration

AUTH = {"Authorization": f"Bearer {AUTH_TEST_TOKEN}"}


# --- authentication & routing (responses end before streaming) -----------------


def test_stream_requires_authentication(auth_settings: Any) -> None:
    app: FastAPI = create_app(auth_settings())
    with TestClient(app) as client:
        assert client.get("/api/events/stream").status_code == 401
        wrong = client.get("/api/events/stream", headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 401


def test_unknown_project_rejected(project: tuple) -> None:
    _app, client, _project_id, _tmp = project
    assert client.get(f"/api/events/stream?project_id={uuid.uuid4()}").status_code == 404


def test_since_requires_project_scope(project: tuple) -> None:
    _app, client, _project_id, _tmp = project
    assert client.get("/api/events/stream?since=0").status_code == 400


def test_connection_limit_returns_429(project: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    app, client, project_id, _tmp = project
    gateway = app.state.realtime
    monkeypatch.setattr(app.state.settings, "realtime_max_connections", 1)
    first = gateway.register(uuid.UUID(project_id))
    try:
        assert client.get(f"/api/events/stream?project_id={project_id}").status_code == 429
    finally:
        gateway.unregister(first)


# --- streaming behavior (ASGI harness) -----------------------------------------


def test_stream_accepts_bearer_token(
    project: tuple, auth_settings: Any, sse: type[SseTestClient]
) -> None:
    _app, _client, project_id, _tmp = project
    app: FastAPI = create_app(auth_settings())

    async def scenario() -> tuple[int, str]:
        async with app.router.lifespan_context(app):
            stream = sse(app, f"/api/events/stream?project_id={project_id}", headers=AUTH)
            stream.start()
            await stream.frames(1)  # GATEWAY_STATUS
            status, content_type = stream.status_code, stream.headers.get("content-type", "")
            await stream.disconnect()
            return int(status or 0), content_type

    status, content_type = asyncio.run(scenario())
    assert status == 200
    assert content_type.startswith("text/event-stream")


def test_gateway_status_and_replay(
    project: tuple,
    sse: type[SseTestClient],
    seed_events: Any,
    event_frames_of: Any,
    control_frames_of: Any,
) -> None:
    app, client, project_id, _tmp = project
    rows = seed_events(client, project_id, 3)
    assert len(rows) >= 4  # PROJECT_OPENED + 3 REQUIREMENT_CREATED

    async def scenario() -> list[dict[str, str]]:
        stream = sse(app, f"/api/events/stream?project_id={project_id}&since=0")
        stream.start()
        frames = await stream.frames(8)
        await stream.disconnect()
        return frames

    frames = asyncio.run(scenario())
    assert any(c.get("kind") == "GATEWAY_STATUS" for c in control_frames_of(frames))

    events = event_frames_of(frames)
    seqs = [int(f["id"]) for f in events if f.get("id", "").isdigit()]
    assert seqs == sorted(seqs)
    assert all(seq > 0 for seq in seqs)
    assert "REQUIREMENT_CREATED" in {f["event"] for f in events}


def test_live_fanout_and_project_isolation(
    project: tuple, sse: type[SseTestClient], make_envelope: Any, event_frames_of: Any
) -> None:
    app, client, project_id, _tmp = project
    gateway = app.state.realtime
    other_project = str(uuid.uuid4())
    other_conn = gateway.register(uuid.UUID(other_project))
    try:

        async def scenario() -> None:
            stream = sse(app, f"/api/events/stream?project_id={project_id}")
            stream.start()
            assert await stream.wait_status() == 200  # registered before broadcast
            gateway.broadcast(make_envelope(project_id, 999, "AGENT_STARTED"))
            gateway.broadcast(make_envelope(other_project, 1, "AGENT_STARTED"))
            # The other project's connection receives ONLY its own scope.
            item = other_conn.queue.get_nowait()
            assert item.project_id == other_project
            frames = await stream.frames(2)
            await stream.disconnect()
            events = event_frames_of(frames)
            live = [f for f in events if '"sequence":999' in f["data"].replace(" ", "")]
            assert live and live[0]["event"] == "AGENT_STARTED"
            assert all(project_id in f["data"] for f in events)  # scope respected

        asyncio.run(scenario())
    finally:
        gateway.unregister(other_conn)


def test_replay_after_disconnect_returns_missed_events(
    project: tuple, sse: type[SseTestClient], seed_events: Any, event_frames_of: Any
) -> None:
    app, client, project_id, _tmp = project
    rows = seed_events(client, project_id, 2)
    last_seq = int(rows[-1]["project_seq"])

    # "Disconnect"; more events occur while nobody is watching.
    more = seed_events(client, project_id, 2)

    async def scenario() -> list[int]:
        stream = sse(app, f"/api/events/stream?project_id={project_id}&since={last_seq}")
        stream.start()
        frames = await stream.frames(1 + len(more))
        await stream.disconnect()
        return [int(f["id"]) for f in event_frames_of(frames) if f.get("id", "").isdigit()]

    seqs = asyncio.run(scenario())
    expected = [int(e["project_seq"]) for e in more if int(e["project_seq"] or 0) > last_seq]
    assert seqs == expected
    assert all(seq > last_seq for seq in seqs)


def test_duplicate_delivery_is_protocol_safe(
    project: tuple, sse: type[SseTestClient], make_envelope: Any, event_frames_of: Any
) -> None:
    app, client, project_id, _tmp = project
    gateway = app.state.realtime
    envelope = make_envelope(project_id, 500, "TOOL_COMPLETED")

    async def scenario() -> list[str]:
        stream = sse(app, f"/api/events/stream?project_id={project_id}")
        stream.start()
        assert await stream.wait_status() == 200  # registered before broadcasting
        for _ in range(3):
            gateway.broadcast(envelope)
        frames = await stream.frames(4)  # status + 3 duplicates
        await stream.disconnect()
        return [f["data"] for f in event_frames_of(frames) if "TOOL_COMPLETED" in f["data"]]

    bodies = asyncio.run(scenario())
    assert len(bodies) == 3
    assert len(set(bodies)) == 1  # byte-identical frames — client dedupes by event_id


def test_client_disconnect_unregisters_connection(project: tuple, sse: type[SseTestClient]) -> None:
    app, client, project_id, _tmp = project
    gateway = app.state.realtime
    before = len(gateway._connections)  # noqa: SLF001 — test introspection

    async def scenario() -> int:
        stream = sse(app, f"/api/events/stream?project_id={project_id}")
        stream.start()
        await stream.frames(1)
        active = len(gateway._connections)  # noqa: SLF001
        await stream.disconnect()
        return active

    active = asyncio.run(scenario())
    assert active == before + 1
    assert len(gateway._connections) == before  # unregistered on disconnect


def test_slow_client_drops_and_eventually_disconnects(
    project: tuple, monkeypatch: pytest.MonkeyPatch, make_envelope: Any
) -> None:
    app, _client, project_id, _tmp = project
    gateway = app.state.realtime
    monkeypatch.setattr(app.state.settings, "realtime_connection_queue_size", 2)
    monkeypatch.setattr(app.state.settings, "realtime_slow_client_max_drops", 3)

    conn = gateway.register(uuid.UUID(project_id))
    for seq in range(1, 8):
        gateway.broadcast(make_envelope(project_id, seq))
    assert conn.drops >= 3
    assert conn.dead is True
    rendered = app.state.metrics.render_prometheus()
    assert "harness_realtime_slow_clients_total" in rendered
    assert 'harness_events_dropped_total{reason="gateway_queue_full"}' in rendered


def test_metrics_endpoint_exposes_realtime_instruments(project: tuple, make_envelope: Any) -> None:
    app, client, project_id, _tmp = project
    app.state.realtime.broadcast(make_envelope(project_id, 700, "TOOL_STARTED"))
    body = client.get("/metrics").text
    assert "# TYPE harness_realtime_active_connections gauge" in body
    assert "harness_events_delivered_total" in body
    assert "harness_realtime_connections_total" in body
    assert "harness_event_delivery_latency_seconds" in body


def test_two_clients_converge_on_the_same_live_state(
    project: tuple,
    sse: type[SseTestClient],
    seed_events: Any,
    make_envelope: Any,
    event_frames_of: Any,
) -> None:
    """Wave 12 §14: two simultaneous subscribers observe identical replay +
    live frames (no divergence); missed-event catch-up itself is covered by
    the replay-after-disconnect test over durable rows."""
    app, client, project_id, _tmp = project
    gateway = app.state.realtime
    seed_events(client, project_id, 2)

    async def scenario() -> tuple[list[str], list[str]]:
        first = sse(app, f"/api/events/stream?project_id={project_id}&since=0")
        second = sse(app, f"/api/events/stream?project_id={project_id}&since=0")
        first.start()
        second.start()
        assert await first.wait_status() == 200
        assert await second.wait_status() == 200
        gateway.broadcast(make_envelope(project_id, 901, "AGENT_CREATED"))
        first_frames = await first.frames(4)  # status + 2 replayed + 1 live
        second_frames = await second.frames(4)
        await first.disconnect()
        await second.disconnect()
        return (
            [f["id"] for f in event_frames_of(first_frames) if f.get("id", "").isdigit()],
            [f["id"] for f in event_frames_of(second_frames) if f.get("id", "").isdigit()],
        )

    first_ids, second_ids = asyncio.run(scenario())
    # Identical cursors on both clients: 2 durable replayed + 1 live frame.
    assert first_ids == second_ids
    assert len(first_ids) == 3

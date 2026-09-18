"""Wave 3 critical integration scenarios (§29 A–H).

Each scenario drives the REAL durable path (events table → per-project sequence
→ gateway fan-out → SSE protocol over the full middleware stack). The live NATS
hop is represented by direct gateway broadcasts (the same call the JetStream
consumer loop makes), so scenarios run without NATS while exercising the full
ordering/dedup/resync contract.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from conftest import SseTestClient, auth_test_settings
from sqlalchemy import select

from app.core.metrics import MetricsRegistry
from app.db.models import Event
from app.main import create_app
from app.realtime.gateway import RealtimeGateway

pytestmark = pytest.mark.integration


def _collect(
    app: Any,
    sse: type[SseTestClient],
    query: str,
    count: int,
    act: Callable[[], None] | None = None,
) -> list[dict[str, str]]:
    """Open one SSE connection, optionally act once registered, collect frames."""

    async def scenario() -> list[dict[str, str]]:
        stream = sse(app, f"/api/events/stream?{query}")
        stream.start()
        registered = await stream.wait_status()
        assert registered == 200
        if act is not None:
            act()
        frames = await stream.frames(count)
        await stream.disconnect()
        return frames

    return asyncio.run(scenario())


# --- Scenario A: agent lifecycle -------------------------------------------------


def test_scenario_a_agent_lifecycle_transitions_in_order(
    project: tuple,
    sse: type[SseTestClient],
    make_envelope: Any,
    event_frames_of: Any,
) -> None:
    app, client, project_id, _tmp = project
    gateway = app.state.realtime

    def broadcast_lifecycle() -> None:
        for seq, event_type in (
            (11, "AGENT_CREATED"),
            (12, "AGENT_STARTED"),
            (13, "AGENT_STATUS_CHANGED"),
            (14, "AGENT_COMPLETED"),
        ):
            gateway.broadcast(make_envelope(project_id, seq, event_type))

    frames = _collect(app, sse, f"project_id={project_id}", 5, broadcast_lifecycle)
    lifecycle = [f["event"] for f in event_frames_of(frames) if f["event"].startswith("AGENT_")]
    assert lifecycle == [
        "AGENT_CREATED",
        "AGENT_STARTED",
        "AGENT_STATUS_CHANGED",
        "AGENT_COMPLETED",
    ]


# --- Scenario B: failure / recovery ----------------------------------------------


def test_scenario_b_failure_recovery_order(
    project: tuple, sse: type[SseTestClient], make_envelope: Any, event_frames_of: Any
) -> None:
    app, client, project_id, _tmp = project
    gateway = app.state.realtime

    def broadcast_recovery() -> None:
        for seq, event_type in (
            (21, "AGENT_FAILED"),
            (22, "RECOVERY_STARTED"),
            (23, "AGENT_REPLACED"),
            (24, "TASK_STATUS_CHANGED"),
        ):
            gateway.broadcast(make_envelope(project_id, seq, event_type))

    frames = _collect(app, sse, f"project_id={project_id}", 5, broadcast_recovery)
    recovery = [
        f["event"]
        for f in event_frames_of(frames)
        if f["event"]
        in {"AGENT_FAILED", "RECOVERY_STARTED", "AGENT_REPLACED", "TASK_STATUS_CHANGED"}
    ]
    assert recovery == [
        "AGENT_FAILED",
        "RECOVERY_STARTED",
        "AGENT_REPLACED",
        "TASK_STATUS_CHANGED",
    ]


# --- Scenario C: parallel agents ---------------------------------------------------


def test_scenario_c_parallel_agents_no_cross_contamination(
    project: tuple, sse: type[SseTestClient], make_envelope: Any, event_frames_of: Any
) -> None:
    app, client, project_id, _tmp = project
    gateway = app.state.realtime
    other = str(uuid.uuid4())
    other_conn = gateway.register(uuid.UUID(other))
    try:

        async def scenario() -> None:
            stream = sse(app, f"/api/events/stream?project_id={project_id}")
            stream.start()
            assert await stream.wait_status() == 200  # registered before broadcasting
            for i in range(10):
                gateway.broadcast(make_envelope(project_id, 31 + i))
            gateway.broadcast(make_envelope(other, 1))
            frames = await stream.frames(11)  # status + 10 parallel events
            await stream.disconnect()
            events = event_frames_of(frames)
            parallel = [f for f in events if f["event"] == "AGENT_STATUS_CHANGED"]
            assert len(parallel) == 10  # every parallel event arrived, none lost
            # The other project's connection got exactly its own single event.
            drained = 0
            while True:
                try:
                    item = other_conn.queue.get_nowait()
                except Exception:  # noqa: BLE001 — queue drained
                    break
                assert item.project_id == other
                drained += 1
            assert drained == 1

        asyncio.run(scenario())
    finally:
        gateway.unregister(other_conn)


# --- Scenario D: connection loss + catch-up --------------------------------------


def test_scenario_d_connection_loss_catches_up(
    project: tuple, sse: type[SseTestClient], seed_events: Any, event_frames_of: Any
) -> None:
    app, client, project_id, _tmp = project
    rows = seed_events(client, project_id, 2)
    last_seq = int(rows[-1]["project_seq"])
    missed = seed_events(client, project_id, 3)

    frames = _collect(app, sse, f"project_id={project_id}&since={last_seq}", 1 + 3)
    seqs = [int(f["id"]) for f in event_frames_of(frames) if f.get("id", "").isdigit()]
    assert seqs == [int(e["project_seq"]) for e in missed if int(e["project_seq"] or 0) > last_seq]


# --- Scenario E: gateway restart ---------------------------------------------------


def test_scenario_e_gateway_restart_recovers(
    project: tuple, sse: type[SseTestClient], seed_events: Any, event_frames_of: Any
) -> None:
    app, client, project_id, _tmp = project
    old_gateway = app.state.realtime
    rows = seed_events(client, project_id, 2)
    last_seq = int(rows[-1]["project_seq"])

    # Simulate a gateway restart: old connections die, a fresh instance serves.
    client.portal.call(old_gateway.close)
    app.state.realtime = RealtimeGateway(app.state.settings, MetricsRegistry(), bus_present=False)
    seed_events(client, project_id, 1)  # execution continues during the restart

    frames = _collect(app, sse, f"project_id={project_id}&since={last_seq}", 1 + 1)
    seqs = [int(f["id"]) for f in event_frames_of(frames) if f.get("id", "").isdigit()]
    assert seqs and all(seq > last_seq for seq in seqs)  # nothing lost across restart


# --- Scenario F: duplication --------------------------------------------------------


def test_scenario_f_duplicate_events_are_safe(
    project: tuple, sse: type[SseTestClient], make_envelope: Any, event_frames_of: Any
) -> None:
    app, client, project_id, _tmp = project
    gateway = app.state.realtime
    envelope = make_envelope(project_id, 88, "TASK_COMPLETED")

    def broadcast_twice() -> None:
        for _ in range(2):
            gateway.broadcast(envelope)

    frames = _collect(app, sse, f"project_id={project_id}", 3, broadcast_twice)
    bodies = [f["data"] for f in event_frames_of(frames)]
    assert len(bodies) == 2 and len(set(bodies)) == 1  # duplicates delivered identical


# --- Scenario G: sequence gap → resync ----------------------------------------------


def test_scenario_g_sequence_gap_triggers_resync_signal(
    project: tuple,
    sse: type[SseTestClient],
    seed_events: Any,
    event_frames_of: Any,
    control_frames_of: Any,
) -> None:
    app, client, project_id, _tmp = project
    seed_events(client, project_id, 4)  # 5 events: seqs 1..5

    # Simulate retention pruning of the EARLIER range: keep only the newest event.
    with app.state.session_factory() as session:
        for row in session.scalars(select(Event).where(Event.project_seq < 5)).all():
            session.delete(row)
        session.commit()

    # Reconnect from a cursor the server can no longer serve → RESYNC_REQUIRED.
    frames = _collect(app, sse, f"project_id={project_id}&since=0", 3)
    assert any(c.get("kind") == "RESYNC_REQUIRED" for c in control_frames_of(frames))
    replayed = [int(f["id"]) for f in event_frames_of(frames) if f.get("id", "").isdigit()]
    assert replayed == [5]  # what remains is still replayed after the resync signal


# --- Scenario H: authorization -------------------------------------------------------


def test_scenario_h_unauthorized_clients_never_receive_events(
    project: tuple, sse: type[SseTestClient], make_envelope: Any
) -> None:
    app, _client, project_id, _tmp = project
    secure = create_app(auth_test_settings())  # token-protected app, same database

    async def scenario() -> tuple[int, int]:
        async with secure.router.lifespan_context(secure):
            no_token = sse(secure, f"/api/events/stream?project_id={project_id}")
            no_token.start()
            no_token_status = await no_token.wait_status()
            await no_token.disconnect()
            bad_token = sse(
                secure,
                f"/api/events/stream?project_id={project_id}",
                headers={"Authorization": "Bearer nope"},
            )
            bad_token.start()
            bad_status = await bad_token.wait_status()
            await bad_token.disconnect()
            return int(no_token_status or 0), int(bad_status or 0)

    no_token_status, bad_status = asyncio.run(scenario())
    gateway = app.state.realtime
    gateway.broadcast(make_envelope(project_id, 990))  # live event, original app
    # Invalid credentials are rejected before any event byte can flow.
    assert no_token_status == 401
    assert bad_status == 401

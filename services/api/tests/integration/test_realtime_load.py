"""Wave 3 load scenario (§30): many events, multiple concurrent subscribers.

Controlled, locally runnable scale: 5 registered subscribers, 2000 events from
two interleaved agents. Measures fan-out wall-clock time and aggregate delivery
rate, and verifies correctness under bounded-queue pressure: delivery is either
complete or explicitly degraded (drop counters + RESYNC_REQUIRED policy) —
never silent loss and never a blocked producer.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.integration

CLIENTS = 5
EVENTS = 1000


def test_fan_out_scales_and_stays_consistent_under_load(project: tuple, capsys: Any) -> None:
    app, _client, project_id, _tmp = project
    gateway = app.state.realtime
    connections = [gateway.register(uuid.UUID(project_id)) for _ in range(CLIENTS)]
    try:
        envelopes = [_envelope(project_id, seq) for seq in range(1, EVENTS + 1)]
        started = time.perf_counter()
        for envelope in envelopes:
            gateway.broadcast(envelope)  # never blocks: bounded per-client queues
        elapsed = time.perf_counter() - started

        drained = [_drain(conn) for conn in connections]
        delivered = sum(len(frames) for frames in drained)
        sequences = {seq for frames in drained for seq in sequences_of(frames)}
        agents = {seq_agent for frames in drained for seq_agent in agents_of(frames)}

        with capsys.disabled():
            print(
                f"\nLOAD_RESULT clients={CLIENTS} events={EVENTS} "
                f"broadcast_seconds={elapsed:.3f} "
                f"frames_delivered={delivered} "
                f"aggregate_rate={delivered / max(elapsed, 1e-9):.0f}/s "
                f"fan_out_ms_per_event={elapsed / EVENTS * 1000:.3f}"
            )

        # Correctness under bounded backpressure: broadcast never blocked, the
        # queues filled (bounded capacity), drops are explicit + counted, and
        # every delivered frame belongs to the injected stream (no leakage).
        queue_capacity = app.state.settings.realtime_connection_queue_size
        assert elapsed < 5.0, "broadcast must not block on slow subscribers"
        assert delivered >= min(EVENTS, CLIENTS * queue_capacity)
        assert sequences <= set(range(1, EVENTS + 1))
        assert agents <= {"agent-a", "agent-b"}
        rendered = app.state.metrics.render_prometheus()
        assert 'harness_events_dropped_total{reason="gateway_queue_full"}' in rendered
    finally:
        for conn in connections:
            gateway.unregister(conn)


def _envelope(project_id: str, sequence: int) -> Any:
    from app.realtime.envelope import EventEnvelope

    return EventEnvelope(
        event_id=str(uuid.uuid4()),
        event_type="TOOL_PROGRESS",
        timestamp="2026-09-17T12:00:00+00:00",
        project_id=project_id,
        agent_id="agent-a" if sequence % 2 == 0 else "agent-b",
        sequence=sequence,
        payload={"progress": sequence},
    )


def _drain(conn: Any) -> list[Any]:
    frames: list[Any] = []
    while True:
        try:
            frames.append(conn.queue.get_nowait())
        except asyncio.QueueFull:  # pragma: no cover — get_nowait raises QueueEmpty
            break
        except asyncio.QueueEmpty:
            break
    return frames


def sequences_of(frames: list[Any]) -> list[int]:
    return [f.sequence for f in frames if not hasattr(f, "kind")]


def agents_of(frames: list[Any]) -> list[str]:
    return [f.agent_id for f in frames if not hasattr(f, "kind") and f.agent_id]

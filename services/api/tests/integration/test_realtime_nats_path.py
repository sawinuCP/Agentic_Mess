"""Live NATS path (Wave 3 §28/§30): bus → JetStream → consumer → fan-out.

Unlike the gateway unit tests (fake consumer), this exercises the REAL live
hop against the compose NATS server: stream creation, server-side dedup
headers, the durable pull consumer, decode, ack, and fan-out — plus a
controlled load measurement (hundreds of events, many agents, several
subscribers) with real measured numbers.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid

import pytest

from app.core.config import Settings
from app.core.metrics import MetricsRegistry
from app.realtime.bus import EventBus
from app.realtime.envelope import EventEnvelope
from app.realtime.gateway import RealtimeGateway

pytestmark = pytest.mark.integration

EVENTS = 300
AGENTS = 20
CLIENTS = 3


def _settings() -> Settings:
    # Hermetic NATS scope: a dedicated stream/prefix per this module plus a
    # UNIQUE durable consumer per test. Sharing a durable consumer across
    # tests is flaky: purge does not clear the server's pending/redelivery
    # state, so a reused consumer can stall behind ghost entries.
    return Settings(
        environment="test",
        log_level="WARNING",
        otel_enabled=False,
        nats_events_enabled=True,
        nats_events_stream="harness-events-test",
        nats_events_subject_prefix="harness.test-events",
        realtime_consumer_name=f"realtime-gateway-test-{uuid.uuid4().hex[:8]}",
        realtime_fetch_timeout_seconds=0.2,
        realtime_heartbeat_seconds=0.5,
    )


def _envelope(project_id: str, seq: int) -> EventEnvelope:
    from datetime import UTC, datetime

    return EventEnvelope(
        event_id=uuid.uuid4().hex,
        event_type="TEST_EVENT",
        timestamp=datetime.now(UTC).isoformat(),
        project_id=project_id,
        agent_id=f"load-agent-{seq % AGENTS}",
        sequence=seq,
        payload={"seq": seq},
    )


async def _drain(queue: asyncio.Queue, count: int, timeout: float) -> list:
    items = []
    deadline = time.monotonic() + timeout
    while len(items) < count and time.monotonic() < deadline:
        try:
            items.append(await asyncio.wait_for(queue.get(), timeout=0.5))
        except TimeoutError:
            continue
    return items


def _project_id() -> str:
    # Dashed UUID form: the gateway matches envelope.project_id against the
    # connection's project key with plain string equality.
    return str(uuid.uuid4())


async def _purge_stream() -> None:
    """Empty the hermetic test stream so consecutive tests (and reruns) never
    see each other's messages or redeliveries."""
    import nats  # noqa: PLC0415 — test-only direct client

    nc = await nats.connect(servers=["nats://127.0.0.1:14222"])
    try:
        js = nc.jetstream()
        with contextlib.suppress(Exception):
            await js.purge_stream("harness-events-test")
    finally:
        await nc.close()


async def _delete_consumer(settings: Settings) -> None:
    """Remove this test's durable consumer so server-side consumer state does
    not accumulate across runs (the stream itself is shared infrastructure)."""
    import nats  # noqa: PLC0415 — test-only direct client

    nc = await nats.connect(servers=["nats://127.0.0.1:14222"])
    try:
        js = nc.jetstream()
        with contextlib.suppress(Exception):
            await js.delete_consumer(settings.nats_events_stream, settings.realtime_consumer_name)
    finally:
        await nc.close()


def test_live_nats_path_delivers_in_order() -> None:
    async def _scenario() -> None:
        await _purge_stream()
        settings = _settings()
        metrics = MetricsRegistry()
        project_id = _project_id()
        bus = EventBus(settings, metrics)
        gateway = RealtimeGateway(settings, metrics, bus_present=True)
        await bus.start()
        await gateway.start()
        try:
            conns = [gateway.register(uuid.UUID(project_id)) for _ in range(CLIENTS)]
            started = time.monotonic()
            for seq in range(1, EVENTS + 1):
                assert bus.publish_nowait(_envelope(project_id, seq)), "queue full too early"
            frames = await _drain(conns[0].queue, EVENTS, timeout=60)
            elapsed = time.monotonic() - started
            assert len(frames) == EVENTS, f"lost events on the live hop: {len(frames)}/{EVENTS}"
            assert [f.sequence for f in frames] == list(range(1, EVENTS + 1))
            assert {f.agent_id for f in frames} == {f"load-agent-{i}" for i in range(AGENTS)}
            # The drained subscriber kept up; the idle ones overflowed their
            # bounded queues and dropped (slow-client policy, by design — they
            # would resync from the durable API rather than block anyone).
            for conn in conns[1:]:
                assert conn.drops > 0
                assert conn.queue.qsize() == 256
            print(
                f"\nLOAD_RESULT path=nats events={EVENTS} agents={AGENTS} "
                f"clients={CLIENTS} elapsed_s={elapsed:.2f} "
                f"events_per_s={EVENTS / elapsed:.0f}"
            )
        finally:
            await gateway.close()
            await bus.close()
            await _delete_consumer(settings)

    asyncio.run(_scenario())


def test_live_nats_duplicate_publish_dedupes() -> None:
    """Server-side Nats-Msg-Id dedup: publishing the same envelope twice
    delivers once (120 s duplicate window)."""

    async def _scenario() -> None:
        await _purge_stream()
        settings = _settings()
        metrics = MetricsRegistry()
        project_id = _project_id()
        bus = EventBus(settings, metrics)
        gateway = RealtimeGateway(settings, metrics, bus_present=True)
        await bus.start()
        await gateway.start()
        try:
            conn = gateway.register(uuid.UUID(project_id))
            envelope = _envelope(project_id, 1)
            assert bus.publish_nowait(envelope)
            assert bus.publish_nowait(envelope)  # same event_id, same body
            frames = await _drain(conn.queue, 2, timeout=20)
            assert len(frames) == 1
        finally:
            await gateway.close()
            await bus.close()
            await _delete_consumer(settings)

    asyncio.run(_scenario())

"""Unit tests: EventBus bounded queue + oversized payload rejection (no NATS)."""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.config import Settings
from app.core.metrics import MetricsRegistry
from app.realtime.bus import EventBus
from app.realtime.envelope import EventEnvelope


def _envelope(sequence: int = 1) -> EventEnvelope:
    return EventEnvelope(
        event_id="123e4567-e89b-12d3-a456-426614174000",
        event_type="TOOL_COMPLETED",
        timestamp="2026-09-17T00:00:00+00:00",
        sequence=sequence,
        payload={"summary": {"passed": 182, "failed": 2}},
    )


def _settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "environment": "test",
        "nats_url": "nats://localhost:9",
        "nats_events_enabled": True,
    }
    base.update(overrides)
    return Settings(**base)


def test_publish_nowait_requires_started_queue() -> None:
    bus = EventBus(_settings(), MetricsRegistry())
    assert bus.publish_nowait(_envelope()) is False  # never started: fail-soft drop


def test_publish_nowait_enqueues_until_full_then_drops() -> None:
    async def scenario() -> None:
        settings = _settings(realtime_publish_queue_size=2)
        metrics = MetricsRegistry()
        bus = EventBus(settings, metrics)
        await bus.start()
        try:
            assert bus.publish_nowait(_envelope(1)) is True
            assert bus.publish_nowait(_envelope(2)) is True
            assert bus.publish_nowait(_envelope(3)) is False  # bounded backpressure
            assert bus._queue is not None and bus._queue.qsize() == 2
            rendered = metrics.render_prometheus()
            assert 'harness_events_dropped_total{reason="publisher_queue_full"} 1' in rendered
        finally:
            await bus.close()

    asyncio.run(scenario())


def test_oversized_payload_is_dropped_not_published() -> None:
    async def scenario() -> None:
        settings = _settings(realtime_max_payload_bytes=128)
        metrics = MetricsRegistry()
        bus = EventBus(settings, metrics)
        await bus.start()
        try:
            big = _envelope()
            object.__setattr__(  # frozen dataclass — tests only
                big, "payload", {"blob": "x" * 4096}
            )
            assert bus.publish_nowait(big) is False
            assert 'harness_events_dropped_total{reason="payload_too_large"} 1' in (
                metrics.render_prometheus()
            )
        finally:
            await bus.close()

    asyncio.run(scenario())


def test_close_is_idempotent_and_stops_accepting() -> None:
    async def scenario() -> None:
        bus = EventBus(_settings(), MetricsRegistry())
        await bus.start()
        await bus.close()
        await bus.close()
        assert bus.publish_nowait(_envelope()) is False

    asyncio.run(scenario())

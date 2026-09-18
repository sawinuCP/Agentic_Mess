"""Realtime gateway dead-letter handling: poison messages never loop forever."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.core.config import Settings
from app.core.metrics import MetricsRegistry
from app.realtime import gateway as gateway_module
from app.realtime.envelope import EventEnvelope
from app.realtime.gateway import RealtimeGateway


class _FakeMetadata:
    def __init__(self, num_delivered: int) -> None:
        self.num_delivered = num_delivered


class _FakeMsg:
    def __init__(self, data: bytes, *, num_delivered: int = 1) -> None:
        self.data = data
        self.subject = "harness.events.project.X"
        self.metadata = _FakeMetadata(num_delivered)
        self.acked = False
        self.naked = False

    async def ack(self) -> None:
        self.acked = True

    async def nak(self) -> None:
        self.naked = True


class _FakeJS:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes, dict[str, str]]] = []

    async def publish(
        self, subject: str, data: bytes, headers: dict[str, str] | None = None
    ) -> None:
        self.published.append((subject, data, headers or {}))


def _gateway() -> RealtimeGateway:
    return RealtimeGateway(Settings(), MetricsRegistry(), bus_present=False)


def _valid_bytes() -> bytes:
    return (
        EventEnvelope(
            event_id=uuid.uuid4().hex,
            event_type="TASK_CREATED",
            timestamp="2026-01-01T00:00:00+00:00",
        )
        .to_json()
        .encode("utf-8")
    )


def test_decode_failure_is_dead_lettered_and_acked() -> None:
    gw = _gateway()
    js = _FakeJS()
    msg = _FakeMsg(b"not-json-at-all")
    asyncio.run(gw._dispatch_message(js, msg))
    assert len(js.published) == 1
    subject, data, headers = js.published[0]
    assert subject == "harness.events.dlq"
    assert data == b"not-json-at-all"
    assert "envelope_decode" in headers["Harness-Dlq-Reason"]
    assert msg.acked and not msg.naked


def _poison(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(raw: bytes) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(gateway_module, "_decode", _raise)


def test_transient_crash_naks_for_redelivery(monkeypatch: pytest.MonkeyPatch) -> None:
    gw = _gateway()
    js = _FakeJS()
    _poison(monkeypatch)
    msg = _FakeMsg(_valid_bytes(), num_delivered=1)
    asyncio.run(gw._dispatch_message(js, msg))
    assert msg.naked and not msg.acked
    assert js.published == []


def test_exhausted_crash_is_dead_lettered_and_acked(monkeypatch: pytest.MonkeyPatch) -> None:
    gw = _gateway()
    js = _FakeJS()
    _poison(monkeypatch)
    msg = _FakeMsg(_valid_bytes(), num_delivered=3)  # == realtime_max_deliver default
    asyncio.run(gw._dispatch_message(js, msg))
    assert msg.acked and not msg.naked
    assert len(js.published) == 1
    assert js.published[0][0] == "harness.events.dlq"


def test_valid_message_fans_out_and_acks() -> None:
    gw = _gateway()
    js = _FakeJS()
    conn = gw.register(None)
    msg = _FakeMsg(_valid_bytes())
    asyncio.run(gw._dispatch_message(js, msg))
    assert msg.acked and not msg.naked
    assert js.published == []
    assert conn.queue.qsize() == 1


def test_register_counts_connections_and_broadcast_measures_latency() -> None:
    from app.core.metrics import MetricsRegistry

    metrics = MetricsRegistry()
    gw = RealtimeGateway(Settings(), metrics, bus_present=False)
    gw.register(None)
    gw.register(None)
    rendered = metrics.render_prometheus()
    assert "harness_realtime_connections_total 2.0" in rendered

    envelope = EventEnvelope(
        event_id=uuid.uuid4().hex,
        event_type="TASK_CREATED",
        timestamp="2026-01-01T00:00:00+00:00",
    )
    gw.broadcast(envelope)
    assert "harness_event_delivery_latency_seconds" in metrics.render_prometheus()

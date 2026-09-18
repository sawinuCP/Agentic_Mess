"""Event bus: JetStream publisher for durable execution events (Wave 3).

Delivery semantics: **at-most-once live hop**. The durable ``events`` row is
written first (authoritative); this bus only accelerates delivery to connected
realtime clients. Publishing never blocks or fails a request: the bridge
enqueues onto a bounded queue (overflow drops the live copy and counts a
metric — clients recover via replay/resync from PostgreSQL). JetStream
server-side deduplication is keyed on ``Nats-Msg-Id`` = ``event_id``, so
producer retries and bridge re-runs cannot duplicate events on the stream.

Stream retention is bounded (max age / msgs / bytes) — the durable history and
long-term replay live in PostgreSQL, never in NATS.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import queue
import random
from typing import Any

from app.core.config import Settings
from app.core.metrics import MetricsRegistry
from app.realtime.envelope import EventEnvelope, subject_for

logger = logging.getLogger("harness.realtime.bus")

_CONNECT_BACKOFF_SECONDS = (0.5, 1.0, 2.0, 4.0, 8.0, 15.0, 30.0)


async def ensure_events_stream(js: Any, settings: Settings) -> None:
    """Idempotently create the bounded execution-events stream (shared by bus + gateway).

    Retention is explicit and bounded: NATS holds only the recent live projection;
    durable history and replay live in PostgreSQL.
    """
    prefix = settings.nats_events_subject_prefix
    from nats.js.api import RetentionPolicy, StreamConfig  # noqa: PLC0415

    config = StreamConfig(
        name=settings.nats_events_stream,
        subjects=[f"{prefix}.>"],
        retention=RetentionPolicy.LIMITS,
        max_age=float(settings.nats_events_max_age_seconds),
        max_msgs=settings.nats_events_max_msgs,
        max_bytes=settings.nats_events_max_bytes,
        duplicate_window=120.0,  # nats-py durations are seconds; server gets nanoseconds
    )
    try:
        await js.add_stream(config)
    except Exception as exc:  # noqa: BLE001 — "already exists" is fine
        if "already" not in str(exc).lower():
            raise


class EventBus:
    """Bounded-queue JetStream publisher. Start once per process; ``close`` on shutdown."""

    def __init__(self, settings: Settings, metrics: MetricsRegistry) -> None:
        self._settings = settings
        self._metrics = metrics
        self._nc: Any = None
        self._js: Any = None
        self._queue: queue.Queue[EventEnvelope] | None = None
        self._task: asyncio.Task[None] | None = None
        self._connected = asyncio.Event()
        self._closed = False
        self.published = metrics.counter(
            "harness_events_published_total", "Execution events published to the event bus"
        )
        self.dropped = metrics.counter(
            "harness_events_dropped_total",
            "Live event copies dropped (durable row unaffected)",
        )
        self.errors = metrics.counter(
            "harness_realtime_stream_errors_total", "Realtime pipeline errors by kind"
        )

    @property
    def healthy(self) -> bool:
        return self._connected.is_set()

    async def start(self) -> None:
        self._queue = queue.Queue(maxsize=self._settings.realtime_publish_queue_size)
        self._task = asyncio.create_task(self._drain(), name="harness-event-bus")

    async def close(self) -> None:
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._disconnect()
        self._connected.clear()

    def publish_nowait(self, envelope: EventEnvelope) -> bool:
        """Enqueue the live copy. Returns False when dropped (bounded backpressure).

        Oversized envelopes are rejected here: large outputs must go to the
        artifact store and travel as ``payload_ref`` (spec §30, Wave 3 §20).
        """
        if self._queue is None or self._closed:
            return False
        if envelope.encoded_size() > self._settings.realtime_max_payload_bytes:
            self.dropped.inc(reason="payload_too_large")
            logger.warning(
                "event_payload_too_large %s size=%d cap=%d",
                envelope.log_context(),
                envelope.encoded_size(),
                self._settings.realtime_max_payload_bytes,
            )
            return False
        try:
            self._queue.put_nowait(envelope)
        except queue.Full:
            self.dropped.inc(reason="publisher_queue_full")
            return False
        return True

    async def _drain(self) -> None:
        assert self._queue is not None
        attempt = 0
        while not self._closed:
            if not self._connected.is_set():
                attempt = await self._connect_with_backoff(attempt)
                continue
            try:
                envelope = self._queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)
                continue
            except asyncio.CancelledError:
                return
            try:
                await self._publish_one(envelope)
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001 — live hop must never crash the drain
                self.errors.inc(kind="bus_publish")
                self.dropped.inc(reason="publish_failed")
                logger.warning("bus_publish_failed %s error=%s", envelope.log_context(), exc)

    async def _connect_with_backoff(self, attempt: int) -> int:
        try:
            await self._connect()
        except Exception as exc:  # noqa: BLE001 — retry with bounded backoff
            self._connected.clear()
            self.errors.inc(kind="bus_connect")
            delay = _CONNECT_BACKOFF_SECONDS[min(attempt, len(_CONNECT_BACKOFF_SECONDS) - 1)]
            attempt += 1
            logger.warning("event_bus_unavailable error=%s retry_in=%.1fs", exc, delay)
            await asyncio.sleep(delay + random.uniform(0, delay * 0.25))  # noqa: S311
            return attempt
        logger.info("event_bus_connected stream=%s", self._settings.nats_events_stream)
        return 0

    async def _connect(self) -> None:
        import nats  # noqa: PLC0415 — heavy import, on demand

        self._nc = await nats.connect(
            servers=[self._settings.nats_url],
            connect_timeout=5,
            max_reconnect_attempts=-1,
            reconnect_time_wait=1,
            disconnected_cb=self._on_disconnected,
            reconnected_cb=self._on_reconnected,
        )
        self._js = self._nc.jetstream()
        await ensure_events_stream(self._js, self._settings)
        self._connected.set()

    async def _on_disconnected(self) -> None:
        self._connected.clear()
        if self._closed:
            return  # intentional close: not an outage, stay quiet
        self.errors.inc(kind="bus_disconnected")
        logger.warning("event_bus_disconnected")

    async def _on_reconnected(self) -> None:
        self._connected.set()
        logger.info("event_bus_reconnected")

    async def _disconnect(self) -> None:
        if self._nc is not None:
            with contextlib.suppress(Exception):  # closing must never raise
                await self._nc.close()
        self._nc = None
        self._js = None

    async def _publish_one(self, envelope: EventEnvelope) -> None:
        assert self._js is not None
        subject = subject_for(envelope, self._settings.nats_events_subject_prefix)
        await self._js.publish(
            subject,
            envelope.to_json().encode("utf-8"),
            headers={"Nats-Msg-Id": envelope.event_id},
        )
        self.published.inc(event_type=envelope.event_type)

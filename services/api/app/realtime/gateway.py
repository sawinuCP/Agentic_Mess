"""Realtime gateway: JetStream consumer → authorized SSE fan-out (Wave 3).

The gateway subscribes to the ``harness.events.>`` subjects with **one durable
pull consumer per process** (no consumer explosion), decodes envelopes, and fans
them out to connected clients filtered by project scope. Clients that cannot
keep up are degraded (bounded per-connection queue; drops counted; a
``RESYNC_REQUIRED`` control frame asks the client to refetch authoritative
state) and eventually disconnected — one slow browser tab must never block
backend execution or other clients.

Events are always acknowledged after fan-out: the NATS stream is a bounded live
projection, replay/resync authority is PostgreSQL. When NATS is unavailable the
gateway degrades — SSE connections still get durable replay on connect and a
``GATEWAY_STATUS`` control frame so the UI can show a degraded state.

Dead-letter handling: messages that can never be processed (envelope decode
failures, or unexpected crashes on their final allowed delivery) are published
verbatim to ``{prefix}.dlq`` — covered by the same stream subjects, so the
poison payload is retained and inspectable — then acknowledged. Anything else
is negatively-acknowledged for redelivery instead of crash-looping the consumer.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings
from app.core.metrics import MetricsRegistry
from app.realtime.bus import ensure_events_stream
from app.realtime.envelope import EventEnvelope, EventEnvelopeError

logger = logging.getLogger("harness.realtime.gateway")

_CONNECT_BACKOFF_SECONDS = (0.5, 1.0, 2.0, 4.0, 8.0, 15.0, 30.0)


class ConnectionLimitError(Exception):
    """Raised when a new SSE connection would exceed ``realtime_max_connections``."""


@dataclass
class ControlFrame:
    """Server → client control signal (never a domain event)."""

    kind: str  # RESYNC_REQUIRED | GATEWAY_STATUS | DISCONNECT
    detail: str = ""
    state: str | None = None  # for GATEWAY_STATUS: live | degraded

    def to_json(self) -> str:
        import json  # noqa: PLC0415 — local import keeps the hot path lean

        body: dict[str, Any] = {"kind": self.kind, "detail": self.detail}
        if self.state is not None:
            body["state"] = self.state
        return json.dumps(body, sort_keys=True)


@dataclass
class Connection:
    """One authorized SSE subscriber with a bounded delivery queue."""

    connection_id: str
    project_id: uuid.UUID | None
    queue: asyncio.Queue[EventEnvelope | ControlFrame]
    drops: int = 0
    dead: bool = False
    accepted_at: float = field(default_factory=time.monotonic)

    @property
    def project_key(self) -> str | None:
        return str(self.project_id) if self.project_id else None


class RealtimeGateway:
    """Fan-out registry + JetStream consumer. One instance per process."""

    def __init__(
        self,
        settings: Settings,
        metrics: MetricsRegistry,
        bus_present: bool,
    ) -> None:
        self._settings = settings
        self._bus_present = bus_present  # whether an EventBus feeds JetStream
        self._connections: dict[str, Connection] = {}
        self._task: asyncio.Task[None] | None = None
        self._closing = False
        self._lag_tick = 0
        m = metrics
        self.delivered = m.counter(
            "harness_events_delivered_total", "Event frames queued for authorized subscribers"
        )
        self.dropped = m.counter(
            "harness_events_dropped_total", "Live event copies dropped (durable row unaffected)"
        )
        self.slow_clients = m.counter(
            "harness_realtime_slow_clients_total", "Slow-client drop episodes"
        )
        self.resyncs = m.counter(
            "harness_realtime_resyncs_total", "RESYNC_REQUIRED control frames emitted"
        )
        self.errors = m.counter(
            "harness_realtime_stream_errors_total", "Realtime pipeline errors by kind"
        )
        self.active_connections = m.gauge(
            "harness_realtime_active_connections", "Currently connected SSE clients"
        )
        self.consumer_lag = m.gauge(
            "harness_realtime_nats_consumer_lag", "JetStream consumer pending messages"
        )

    @property
    def degraded(self) -> bool:
        """Live delivery unavailable (NATS off/unreachable): replay-only mode."""
        return not self._bus_present

    async def start(self) -> None:
        if self._bus_present:
            self._task = asyncio.create_task(self._consume_loop(), name="harness-realtime-gateway")

    async def close(self) -> None:
        self._closing = True
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        for conn in list(self._connections.values()):
            conn.dead = True

    def register(self, project_id: uuid.UUID | None) -> Connection:
        if len(self._connections) >= self._settings.realtime_max_connections:
            raise ConnectionLimitError(
                f"realtime connection limit reached ({self._settings.realtime_max_connections})"
            )
        conn = Connection(
            connection_id=uuid.uuid4().hex,
            project_id=project_id,
            queue=asyncio.Queue(maxsize=self._settings.realtime_connection_queue_size),
        )
        self._connections[conn.connection_id] = conn
        self.active_connections.set(len(self._connections))
        return conn

    def unregister(self, conn: Connection) -> None:
        self._connections.pop(conn.connection_id, None)
        self.active_connections.set(len(self._connections))

    def broadcast(self, envelope: EventEnvelope) -> None:
        """Fan one envelope out to matching subscribers (never blocks)."""
        for conn in list(self._connections.values()):
            if conn.project_key is not None and envelope.project_id != conn.project_key:
                continue
            self._deliver(conn, envelope)

    def _deliver(self, conn: Connection, envelope: EventEnvelope) -> None:
        try:
            conn.queue.put_nowait(envelope)
            self.delivered.inc()
        except asyncio.QueueFull:
            self._handle_slow_client(conn)

    def _handle_slow_client(self, conn: Connection) -> None:
        self.dropped.inc(reason="gateway_queue_full")
        self.slow_clients.inc()
        conn.drops += 1
        logger.warning(
            "slow_client connection_id=%s project=%s drops=%d",
            conn.connection_id,
            conn.project_key or "-",
            conn.drops,
        )
        if conn.drops == 1:
            # Ask for an authoritative refetch; if even the control frame cannot
            # fit, the client's next sequence gap triggers resync anyway.
            with contextlib.suppress(asyncio.QueueFull):
                conn.queue.put_nowait(ControlFrame("RESYNC_REQUIRED", "delivery queue overflow"))
            self.resyncs.inc()
        if conn.drops >= self._settings.realtime_slow_client_max_drops:
            conn.dead = True
            with contextlib.suppress(asyncio.QueueFull):
                conn.queue.put_nowait(ControlFrame("DISCONNECT", "slow client disconnected"))
            self.errors.inc(kind="slow_client_disconnected")

    # -- JetStream consumption ---------------------------------------------------

    async def _consume_loop(self) -> None:
        """Durable pull consumer: fetch → decode → fan-out → ack (bounded retries)."""
        import nats  # noqa: PLC0415 — heavy import, on demand
        from nats.js.api import AckPolicy, ConsumerConfig  # noqa: PLC0415

        attempt = 0
        while not self._closing:
            try:
                nc = await nats.connect(servers=[self._settings.nats_url], connect_timeout=5)
                js = nc.jetstream()
                await ensure_events_stream(js, self._settings)
                sub = await js.pull_subscribe(
                    f"{self._settings.nats_events_subject_prefix}.>",
                    durable=self._settings.realtime_consumer_name,
                    stream=self._settings.nats_events_stream,
                    config=ConsumerConfig(
                        ack_policy=AckPolicy.EXPLICIT,
                        max_ack_pending=self._settings.realtime_max_ack_pending,
                        max_deliver=self._settings.realtime_max_deliver,
                        ack_wait=30.0,
                    ),
                )
                logger.info(
                    "realtime_gateway_consumer_ready consumer=%s stream=%s",
                    self._settings.realtime_consumer_name,
                    self._settings.nats_events_stream,
                )
                attempt = 0
                while not self._closing:
                    try:
                        msgs = await sub.fetch(
                            batch=self._settings.realtime_fetch_batch,
                            timeout=self._settings.realtime_fetch_timeout_seconds,
                        )
                    except Exception as exc:  # noqa: BLE001 — timeouts are normal
                        if type(exc).__name__.endswith("TimeoutError"):
                            await asyncio.sleep(0.01)
                            continue
                        raise
                    for msg in msgs:
                        await self._dispatch_message(js, msg)
                    self._lag_tick += 1
                    if self._lag_tick >= 30:
                        self._lag_tick = 0
                        await self._report_lag(js)
                with contextlib.suppress(Exception):
                    await nc.close()
                return
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001 — reconnect with bounded backoff
                self.errors.inc(kind="gateway_consume")
                delay = _CONNECT_BACKOFF_SECONDS[min(attempt, len(_CONNECT_BACKOFF_SECONDS) - 1)]
                attempt += 1
                logger.warning("realtime_gateway_degraded error=%s retry_in=%.1fs", exc, delay)
                await asyncio.sleep(delay + random.uniform(0, delay * 0.25))  # noqa: S311

    def _dlq_subject(self) -> str:
        """Dead-letter subject — inside the stream's ``{prefix}.>`` subjects."""
        return f"{self._settings.nats_events_subject_prefix}.dlq"

    async def _dead_letter(self, js: Any, msg: Any, reason: str) -> None:
        """Retain a poison message verbatim on the DLQ subject (never raises)."""
        try:
            await js.publish(
                self._dlq_subject(),
                msg.data,
                headers={
                    "Harness-Dlq-Reason": reason[:256],
                    "Harness-Orig-Subject": str(getattr(msg, "subject", ""))[:256],
                },
            )
        except Exception as exc:  # noqa: BLE001 — a DLQ outage must not kill consumption
            logger.warning("dead_letter_publish_failed error=%s", exc)
        else:
            self.errors.inc(kind="dead_lettered")

    async def _dispatch_message(self, js: Any, msg: Any) -> None:
        """Decode → fan-out → ack exactly one JetStream message.

        Undecodable envelopes are dead-lettered (never redelivered forever);
        unexpected processing crashes are nacked for redelivery until the
        final allowed delivery, then dead-lettered — the consumer loop itself
        never crash-loops on a poison message.
        """
        try:
            delivered = int(getattr(getattr(msg, "metadata", None), "num_delivered", 1) or 1)
        except (TypeError, ValueError):
            delivered = 1
        try:
            envelope = _decode(msg.data)
        except EventEnvelopeError as exc:
            self.errors.inc(kind="envelope_decode")
            logger.warning("envelope_rejected error=%s", exc)
            await self._dead_letter(js, msg, f"envelope_decode: {exc}")
        except Exception as exc:  # noqa: BLE001 — poison must not kill the loop
            if delivered >= max(1, self._settings.realtime_max_deliver):
                self.errors.inc(kind="poison_message")
                logger.warning(
                    "poison_message_dead_lettered deliveries=%d error=%r",
                    delivered,
                    exc,
                )
                await self._dead_letter(js, msg, f"poison: {type(exc).__name__}")
            else:
                with contextlib.suppress(Exception):
                    await msg.nak()
                return
        else:
            self.broadcast(envelope)
        with contextlib.suppress(Exception):
            await msg.ack()

    async def _report_lag(self, js: Any) -> None:
        with contextlib.suppress(Exception):
            info = await js.consumer_info(
                self._settings.nats_events_stream, self._settings.realtime_consumer_name
            )
            self.consumer_lag.set(getattr(info, "num_pending", 0) or 0)


def _decode(raw: bytes) -> EventEnvelope:
    from app.realtime.envelope import decode_envelope  # noqa: PLC0415

    return decode_envelope(raw)

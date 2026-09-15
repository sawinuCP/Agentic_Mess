"""Message transport (FR-010, spec §14): durable PG first, NATS JetStream fan-out.

The ``messages`` table is the source of truth; the broker is an at-least-once
transport that delivers durable envelopes to subscribers. Idempotency across
redeliveries comes from the ``Nats-Msg-Id`` header (JetStream server-side
deduplication keyed by the durable message id). Delivery is opt-in
(``HARNESS_NATS_DELIVERY_ENABLED``); with it off, the durable replay endpoints
still work — fail-closed applies to the fan-out, never to the durable record.
"""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import Settings

logger = logging.getLogger("harness.messaging")

BROADCAST_TYPE = "broadcast"


class BrokerUnavailable(Exception):
    """NATS is disabled or unreachable; routes map this to HTTP 503."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.message = detail


@dataclass(frozen=True, slots=True)
class MessageEnvelope:
    """The wire form of a durable message (spec §14 envelope)."""

    message_id: uuid.UUID
    conversation_id: uuid.UUID
    type: str  # request|response|progress|artifact|question|broadcast
    recipient_agent_id: uuid.UUID | None
    sender_agent_id: uuid.UUID | None
    task_id: uuid.UUID | None
    priority: int
    correlation_id: str | None
    payload: dict[str, Any]


def subject_for(envelope: MessageEnvelope, prefix: str) -> str:
    """Direct messages address one agent; broadcasts fan out to a shared subject."""
    if envelope.type == BROADCAST_TYPE or envelope.recipient_agent_id is None:
        return f"{prefix}.broadcast"
    return f"{prefix}.agent.{envelope.recipient_agent_id}"


def encode_envelope(envelope: MessageEnvelope) -> bytes:
    """Canonical JSON body — stable field order, UUIDs as strings."""
    body = {
        "message_id": str(envelope.message_id),
        "conversation_id": str(envelope.conversation_id),
        "type": envelope.type,
        "recipient_agent_id": (
            str(envelope.recipient_agent_id) if envelope.recipient_agent_id else None
        ),
        "sender_agent_id": str(envelope.sender_agent_id) if envelope.sender_agent_id else None,
        "task_id": str(envelope.task_id) if envelope.task_id else None,
        "priority": envelope.priority,
        "correlation_id": envelope.correlation_id,
        "payload": envelope.payload,
    }
    return json.dumps(body, sort_keys=True).encode("utf-8")


class MessageBroker(Protocol):
    """At-least-once transport. ``publish`` returns after the server acks."""

    async def publish(self, envelope: MessageEnvelope) -> None: ...

    async def close(self) -> None: ...


class NullBroker:
    """Transport-off implementation. Publishing fails loudly (503 at the route);
    the durable message record and its replay endpoints are unaffected."""

    async def publish(self, envelope: MessageEnvelope) -> None:
        raise BrokerUnavailable(
            "NATS delivery is disabled (set HARNESS_NATS_DELIVERY_ENABLED=true; NATS is "
            "in the default compose stack)"
        )

    async def close(self) -> None:
        return None


class NatsJetStreamBroker:
    """NATS JetStream publisher with a lazily-created durable stream."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._nc: Any = None
        self._js: Any = None

    async def _ensure(self) -> Any:
        if self._js is not None:
            return self._js
        try:
            import nats  # noqa: PLC0415 — heavy import, on demand
        except ImportError as exc:  # pragma: no cover — dependency is declared
            raise BrokerUnavailable(f"nats-py is not installed: {exc}") from None
        try:
            self._nc = await nats.connect(self._settings.nats_url)
            self._js = self._nc.jetstream()
            prefix = self._settings.nats_delivery_subject_prefix
            try:
                await self._js.add_stream(
                    self._settings.nats_delivery_stream, subjects=[f"{prefix}.>"]
                )
            except Exception as exc:  # noqa: BLE001 — "already exists" is fine
                if "already" not in str(exc).lower():
                    raise
        except BrokerUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — any connect/config failure is "unavailable"
            logger.warning("nats_broker_unavailable error=%s", exc)
            await self.close()
            raise BrokerUnavailable(
                f"NATS unavailable at {self._settings.nats_url}: {exc}"
            ) from None
        return self._js

    async def publish(self, envelope: MessageEnvelope) -> None:
        js = await self._ensure()
        subject = subject_for(envelope, self._settings.nats_delivery_subject_prefix)
        try:
            await js.publish(
                subject,
                encode_envelope(envelope),
                headers={"Nats-Msg-Id": str(envelope.message_id)},
            )
        except Exception as exc:  # noqa: BLE001 — publish failure leaves the row undelivered
            raise BrokerUnavailable(
                f"NATS publish failed for {envelope.message_id}: {exc}"
            ) from None

    async def close(self) -> None:
        if self._nc is not None:
            with contextlib.suppress(Exception):  # closing must never raise
                await self._nc.close()
        self._nc = None
        self._js = None


def build_broker(settings: Settings) -> MessageBroker:
    """Transport selection: JetStream when enabled, fail-loud NullBroker otherwise."""
    if settings.nats_delivery_enabled:
        return NatsJetStreamBroker(settings)
    return NullBroker()

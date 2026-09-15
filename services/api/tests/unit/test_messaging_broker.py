"""Messaging transport units: subjects, canonical encoding, fail-loud NullBroker."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from app.messaging.broker import (
    BrokerUnavailable,
    MessageEnvelope,
    NullBroker,
    encode_envelope,
    subject_for,
)

AGENT = uuid.uuid4()
OTHER = uuid.uuid4()


def _envelope(**overrides: object) -> MessageEnvelope:
    base: dict[str, object] = {
        "message_id": uuid.uuid4(),
        "conversation_id": uuid.uuid4(),
        "type": "request",
        "recipient_agent_id": AGENT,
        "sender_agent_id": OTHER,
        "task_id": None,
        "priority": 5,
        "correlation_id": "corr-1",
        "payload": {"step": 1},
    }
    base.update(overrides)
    return MessageEnvelope(**base)  # type: ignore[arg-type]


def test_subject_direct_targets_the_recipient_agent() -> None:
    subject = subject_for(_envelope(), "harness.msg")
    assert subject == f"harness.msg.agent.{AGENT}"


def test_subject_broadcast_ignores_recipient() -> None:
    subject = subject_for(_envelope(type="broadcast"), "harness.msg")
    assert subject == "harness.msg.broadcast"


def test_encode_envelope_is_canonical_json() -> None:
    body = json.loads(encode_envelope(_envelope()))
    assert body["recipient_agent_id"] == str(AGENT)
    assert body["payload"] == {"step": 1}
    # Stable field order → identical bytes for the identical envelope.
    envelope = _envelope()
    assert encode_envelope(envelope) == encode_envelope(envelope)


def test_null_broker_fails_loudly() -> None:
    with pytest.raises(BrokerUnavailable):
        asyncio.run(NullBroker().publish(_envelope()))

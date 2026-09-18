"""Unit tests: canonical realtime event envelope (Wave 3)."""

from __future__ import annotations

import json

import pytest

from app.realtime.envelope import (
    SCHEMA_VERSION,
    EventEnvelope,
    EventEnvelopeError,
    decode_envelope,
    envelope_from_event,
    subject_for,
)


def _envelope(**overrides: object) -> EventEnvelope:
    base: dict[str, object] = {
        "event_id": "123e4567-e89b-12d3-a456-426614174000",
        "event_type": "AGENT_STATUS_CHANGED",
        "timestamp": "2026-09-17T00:00:00+00:00",
        "sequence": 42,
        "payload": {"to": "running"},
    }
    base.update(overrides)
    return EventEnvelope(**base)  # type: ignore[arg-type]


def test_json_roundtrip_preserves_all_fields() -> None:
    envelope = _envelope(
        project_id="p-1",
        execution_id="x-1",
        task_id="t-1",
        agent_id="a-1",
        correlation_id="c-1",
        source="temporal",
        payload_ref="artifact://sha",
    )
    decoded = decode_envelope(envelope.to_json())
    assert decoded == envelope


def test_to_json_is_stable_and_compact() -> None:
    first = _envelope().to_json()
    second = _envelope().to_json()
    assert first == second
    assert " " not in first  # compact separators
    body = json.loads(first)
    assert body["schema_version"] == SCHEMA_VERSION


def test_decode_rejects_unsupported_schema_version() -> None:
    body = json.loads(_envelope().to_json())
    body["schema_version"] = SCHEMA_VERSION + 1
    with pytest.raises(EventEnvelopeError, match="schema_version"):
        decode_envelope(json.dumps(body))


def test_decode_rejects_missing_or_malformed_required_fields() -> None:
    with pytest.raises(EventEnvelopeError):
        decode_envelope("{}")
    body = json.loads(_envelope().to_json())
    body["event_id"] = "not-a-uuid"
    with pytest.raises(EventEnvelopeError, match="UUID"):
        decode_envelope(json.dumps(body))
    body = json.loads(_envelope().to_json())
    body["event_type"] = ""
    with pytest.raises(EventEnvelopeError, match="event_type"):
        decode_envelope(json.dumps(body))
    body = json.loads(_envelope().to_json())
    body["sequence"] = "seven"
    with pytest.raises(EventEnvelopeError, match="sequence"):
        decode_envelope(json.dumps(body))
    with pytest.raises(EventEnvelopeError, match="JSON"):
        decode_envelope(b"\xff\xfe not json")


def test_decode_accepts_unknown_optional_fields_absent() -> None:
    decoded = decode_envelope(_envelope(sequence=None).to_json())
    assert decoded.sequence is None


def test_subject_for_scopes_by_project() -> None:
    prefix = "harness.events"
    assert subject_for(_envelope(project_id="p-1"), prefix) == f"{prefix}.project.p-1"
    assert subject_for(_envelope(project_id=None), prefix) == f"{prefix}.global"


def test_log_context_never_contains_payload_data() -> None:
    context = _envelope(payload={"secret_detail": "s3cr3t-value"}).log_context()
    assert "s3cr3t" not in context
    assert "AGENT_STATUS_CHANGED" in context
    assert "seq=42" in context


def test_encoded_size_reflects_payload() -> None:
    small = _envelope()
    big = _envelope(payload={"blob": "x" * 10_000})
    assert big.encoded_size() > small.encoded_size()


def test_envelope_from_event_projects_durable_row() -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    from app.db.models import Event

    project_id = uuid4()
    task_id = uuid4()
    row = Event(
        id=uuid4(),
        occurred_at=datetime(2026, 9, 17, tzinfo=UTC),
        event_type="TASK_COMPLETED",
        source="temporal",
        project_id=project_id,
        task_id=task_id,
        agent_id="agent-1",
        execution_id="wf-1",
        correlation_id="corr-1",
        payload={"attempts": 2},
    )
    row.project_seq = 9
    envelope = envelope_from_event(row)
    assert envelope.event_type == "TASK_COMPLETED"
    assert envelope.sequence == 9
    assert envelope.project_id == str(project_id)
    assert envelope.task_id == str(task_id)
    assert envelope.payload == {"attempts": 2}

"""Canonical realtime event envelope (Wave 3).

One wire format for every execution event that travels from the durable
``events`` table to live subscribers (JetStream → SSE gateway → frontend). The
envelope is a projection of a committed ``Event`` row — PostgreSQL remains the
source of truth. Large data never rides in ``payload``: producers attach an
``artifact_ref`` (e.g. ``artifact://<sha>``) plus a concise summary, and the
client fetches the artifact on demand.

Only fields that exist on the durable row are populated; consumers must reject
unknown ``schema_version`` values safely (resync from the authoritative API).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover — import cycle guard for type checkers only
    from app.db.models import Event

SCHEMA_VERSION = 1


class EventEnvelopeError(ValueError):
    """Envelope cannot be built/decoded, or is not supported by this consumer."""


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """The wire form of one durable execution event (schema v1)."""

    event_id: str
    event_type: str
    timestamp: str  # ISO-8601, UTC
    schema_version: int = SCHEMA_VERSION
    project_id: str | None = None
    execution_id: str | None = None
    task_id: str | None = None
    agent_id: str | None = None
    correlation_id: str | None = None
    source: str | None = None
    sequence: int | None = None  # per-project dense sequence (ordering scope)
    payload: dict[str, Any] | None = None
    payload_ref: str | None = None  # artifact reference for large data

    def to_json(self) -> str:
        """Canonical JSON — stable field order, so byte-equal frames dedupe cleanly."""
        body = {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "project_id": self.project_id,
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "correlation_id": self.correlation_id,
            "source": self.source,
            "sequence": self.sequence,
            "payload": self.payload or {},
            "payload_ref": self.payload_ref,
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":"))

    def encoded_size(self) -> int:
        return len(self.to_json().encode("utf-8"))

    def log_context(self) -> str:
        """Correlation fields for structured logs — never includes payload data."""

        def short(value: str | None) -> str:
            return value[:8] if value else "-"

        return (
            "event_id={eid} event_type={etype} project={pid} execution={xid} "
            "task={tid} agent={aid} correlation={cid} seq={seq}".format(
                eid=short(self.event_id),
                etype=self.event_type,
                pid=short(self.project_id),
                xid=short(self.execution_id),
                tid=short(self.task_id),
                aid=short(self.agent_id),
                cid=short(self.correlation_id),
                seq=self.sequence if self.sequence is not None else "-",
            )
        )


def subject_for(envelope: EventEnvelope, prefix: str) -> str:
    """Subject hierarchy: ``<prefix>.project.<project_id>`` or ``<prefix>.global``.

    Mirrors the existing ``harness.msg.*`` convention; the JetStream stream binds
    ``<prefix>.>`` so new scopes never need stream reconfiguration.
    """
    if envelope.project_id:
        return f"{prefix}.project.{envelope.project_id}"
    return f"{prefix}.global"


def envelope_from_event(row: Event) -> EventEnvelope:
    """Build the envelope projection from a committed durable Event row."""
    return EventEnvelope(
        event_id=str(row.id),
        event_type=row.event_type,
        timestamp=row.occurred_at.isoformat() if row.occurred_at else "",
        project_id=str(row.project_id) if row.project_id else None,
        execution_id=row.execution_id,
        task_id=str(row.task_id) if row.task_id else None,
        agent_id=row.agent_id,
        correlation_id=row.correlation_id,
        source=row.source,
        sequence=row.project_seq,
        payload=dict(row.payload or {}),
    )


def decode_envelope(raw: bytes | str) -> EventEnvelope:
    """Parse + validate a wire envelope. Raises ``EventEnvelopeError`` on anything
    this consumer does not fully understand (callers must resync, not guess)."""
    try:
        body = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EventEnvelopeError(f"envelope is not valid JSON: {exc}") from None
    if not isinstance(body, dict):
        raise EventEnvelopeError("envelope must be a JSON object")

    version = body.get("schema_version")
    if not isinstance(version, int) or version > SCHEMA_VERSION:
        raise EventEnvelopeError(f"unsupported schema_version: {version!r}")

    event_id = body.get("event_id")
    if not isinstance(event_id, str):
        raise EventEnvelopeError("event_id is required")
    try:
        uuid.UUID(event_id)
    except ValueError:
        raise EventEnvelopeError("event_id must be a UUID") from None

    event_type = body.get("event_type")
    if not isinstance(event_type, str) or not event_type:
        raise EventEnvelopeError("event_type is required")

    timestamp = body.get("timestamp")
    if not isinstance(timestamp, str) or not timestamp:
        raise EventEnvelopeError("timestamp is required")

    sequence = body.get("sequence")
    if sequence is not None and not isinstance(sequence, int):
        raise EventEnvelopeError("sequence must be an integer or null")

    payload = body.get("payload")
    if payload is not None and not isinstance(payload, dict):
        raise EventEnvelopeError("payload must be an object")

    return EventEnvelope(
        event_id=event_id,
        event_type=event_type,
        timestamp=timestamp,
        schema_version=version,
        project_id=body.get("project_id"),
        execution_id=body.get("execution_id"),
        task_id=body.get("task_id"),
        agent_id=body.get("agent_id"),
        correlation_id=body.get("correlation_id"),
        source=body.get("source"),
        sequence=sequence,
        payload=payload or {},
        payload_ref=body.get("payload_ref"),
    )

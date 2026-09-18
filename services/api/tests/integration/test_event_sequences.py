"""Wave 3 integration: per-project monotonic sequences + replay query API."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.db.models import Event
from app.services.core.events import record_event

pytestmark = pytest.mark.integration

REQUIREMENT_BODY = {
    "title": "Authentication module",
    "description": "Users must be able to sign in with credentials.",
    "desired_outcome": "Working login flow with tests",
    "priority": "must",
    "criteria": [{"description": "It works", "kind": "automated_test"}],
}


def _requirement(title: str) -> dict[str, object]:
    return {**REQUIREMENT_BODY, "title": title}


def _project_events(app: FastAPI, project_id: str) -> list[Event]:
    with app.state.session_factory() as session:
        rows = session.scalars(
            select(Event)
            .where(Event.project_id == uuid.UUID(project_id))
            .order_by(Event.project_seq.asc())
        ).all()
        return [row for row in rows if row.project_seq is not None]


def test_project_sequences_are_dense_and_monotonic(project: tuple) -> None:
    _app, client, project_id, _tmp = project
    for index in range(5):
        client.post(
            f"/api/projects/{project_id}/requirements",
            json=_requirement(f"req {index}"),
        )
    rows = _project_events(_app, project_id)
    # The project open itself records the first event; every insert extends the stream.
    sequences = [row.project_seq for row in rows]
    assert sequences and all(s is not None for s in sequences)
    assert sequences == list(range(1, len(sequences) + 1))


def test_since_seq_returns_only_newer_rows_in_order(project: tuple) -> None:
    _app, client, project_id, _tmp = project
    for index in range(4):
        client.post(
            f"/api/projects/{project_id}/requirements",
            json=_requirement(f"r{index}"),
        )
    rows = _project_events(_app, project_id)
    assert len(rows) >= 5
    middle = rows[1].project_seq

    body = client.get(
        "/api/events",
        params={"project_id": project_id, "since_seq": middle, "order": "asc", "limit": 500},
    ).json()

    returned = [e["project_seq"] for e in body if e["project_seq"] is not None]
    assert returned == sorted(returned)
    assert all(seq > middle for seq in returned)
    assert rows[-1].event_type in {e["event_type"] for e in body}


def test_record_event_persists_agent_and_execution_scope(project: tuple) -> None:
    app, _client, project_id, _tmp = project
    import asyncio

    asyncio.run(
        record_event(
            app.state.session_factory,
            "AGENT_STATUS_CHANGED",
            project_id=uuid.UUID(project_id),
            agent_id="agent-xyz",
            execution_id="wf-42",
            correlation_id="corr-9",
            payload={"from": "created", "to": "running"},
            source="test",
        )
    )
    with app.state.session_factory() as session:
        row = session.scalars(
            select(Event).where(
                Event.project_id == uuid.UUID(project_id), Event.agent_id == "agent-xyz"
            )
        ).one()
    assert row.execution_id == "wf-42"
    assert row.correlation_id == "corr-9"
    assert row.project_seq is not None

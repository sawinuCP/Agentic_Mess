"""Wave 3 integration: bounded retention for durable events + manual prune endpoint."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import update

from app.db.models import Event
from app.realtime.retention import prune_events

pytestmark = pytest.mark.integration


def _insert_event(app: Any, project_id: uuid.UUID, age_days: float) -> Event:
    with app.state.session_factory() as session:
        row = Event(
            event_type="TEST_EVENT",
            source="retention-test",
            project_id=project_id,
            payload={"ok": True},
        )
        session.add(row)
        session.commit()
        # Backdate after insert (server_default owns the column on insert).
        session.execute(
            update(Event)
            .where(Event.id == row.id)
            .values(occurred_at=datetime.now(UTC) - timedelta(days=age_days))
        )
        session.commit()
        return row


def test_prune_events_removes_only_rows_past_window(project: tuple) -> None:
    app, client, project_id, _tmp = project
    old_row = _insert_event(app, uuid.UUID(project_id), age_days=45)
    fresh_row = _insert_event(app, uuid.UUID(project_id), age_days=0)

    removed = prune_events(app.state.session_factory, older_than_days=30, batch_size=100)

    assert removed >= 1
    with app.state.session_factory() as session:
        assert session.get(Event, old_row.id) is None
        assert session.get(Event, fresh_row.id) is not None


def test_prune_disabled_window_is_noop(project: tuple) -> None:
    app, _client, project_id, _tmp = project
    row = _insert_event(app, uuid.UUID(project_id), age_days=400)
    assert prune_events(app.state.session_factory, older_than_days=0, batch_size=100) == 0
    with app.state.session_factory() as session:
        assert session.get(Event, row.id) is not None


def test_manual_retention_endpoint(project: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    app, client, project_id, _tmp = project
    row = _insert_event(app, uuid.UUID(project_id), age_days=900)
    monkeypatch.setattr(app.state.settings, "retention_events_days", 30)
    body: dict = client.post("/api/retention/prune").json()
    assert body["events_pruned"] >= 1
    with app.state.session_factory() as session:
        assert session.get(Event, row.id) is None

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


def test_blob_prune_spares_referenced_evidence(project: tuple, tmp_path) -> None:
    """Reference-aware retention: an old blob referenced by attempt evidence
    survives; an equally old unreferenced blob is pruned."""
    import os
    import time

    from app.artifacts.store import ArtifactStore
    from app.db.models import Artifact, TaskAttempt
    from app.realtime.retention import prune_artifact_blobs

    app, _client, project_id, _tmp = project
    store = ArtifactStore(tmp_path / "blobs")
    kept = store.put(b"final evidence")
    gone = store.put(b"disposable output")
    past = time.time() - 10 * 86_400
    for blob in (kept, gone):
        path = tmp_path / "blobs" / blob.storage_path
        os.utime(path, (past, past))
    with app.state.session_factory() as session:
        from app.db.models import Task

        task = Task(project_id=uuid.UUID(project_id), title="t", request="r", payload={})
        session.add(task)
        session.flush()
        artifact = Artifact(
            project_id=uuid.UUID(project_id),
            name="evidence.log",
            kind="raw_output",
            mime="text/plain",
            size=kept.size,
            sha256=kept.sha256,
            storage_path=kept.storage_path,
        )
        session.add(artifact)
        session.flush()
        session.add(
            TaskAttempt(
                task_id=task.id,
                attempt_number=1,
                outcome="failed",
                evidence_artifact_ids=[str(artifact.id)],
            )
        )
        session.add(
            Artifact(
                project_id=uuid.UUID(project_id),
                name="scratch.log",
                kind="raw_output",
                mime="text/plain",
                size=gone.size,
                sha256=gone.sha256,
                storage_path=gone.storage_path,
            )
        )
        session.commit()

    removed = prune_artifact_blobs(
        tmp_path / "blobs", older_than_days=5, factory=app.state.session_factory
    )
    assert removed == 1
    assert (tmp_path / "blobs" / kept.storage_path).exists()
    assert not (tmp_path / "blobs" / gone.storage_path).exists()


def test_manual_retention_endpoint(project: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    app, client, project_id, _tmp = project
    row = _insert_event(app, uuid.UUID(project_id), age_days=900)
    monkeypatch.setattr(app.state.settings, "retention_events_days", 30)
    body: dict = client.post("/api/retention/prune").json()
    assert body["events_pruned"] >= 1
    with app.state.session_factory() as session:
        assert session.get(Event, row.id) is None

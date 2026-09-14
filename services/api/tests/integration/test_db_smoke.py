"""Database integration smoke test. Requires PostgreSQL; skips when unreachable."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.db.base import session_scope
from app.db.models import Event, Project

pytestmark = pytest.mark.integration


def _postgres_available(app: FastAPI) -> bool:
    try:
        with app.state.session_factory() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


def test_project_and_event_roundtrip(app: FastAPI) -> None:
    with TestClient(app):  # enters lifespan: builds engine + session factory
        if not _postgres_available(app):
            pytest.skip("PostgreSQL not reachable; integration smoke skipped")
        factory = app.state.session_factory

        project_id = uuid.uuid4()
        with session_scope(factory) as session:
            session.add(
                Project(
                    id=project_id,
                    name=f"smoke-{project_id.hex[:8]}",
                    root_path="C:/tmp/smoke",
                )
            )
        try:
            with session_scope(factory) as session:
                session.add(
                    Event(
                        event_type="TEST_EVENT",
                        project_id=project_id,
                        payload={"ok": True},
                    )
                )
            with session_scope(factory) as session:
                assert session.get(Project, project_id) is not None
                events = session.scalars(select(Event).where(Event.project_id == project_id)).all()
                assert len(events) == 1
                assert events[0].payload == {"ok": True}
        finally:
            with session_scope(factory) as session:
                project = session.get(Project, project_id)
                if project is not None:
                    session.delete(project)

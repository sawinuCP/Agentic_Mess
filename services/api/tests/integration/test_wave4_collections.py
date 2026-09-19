"""Wave 4 collection budgets: bounded queries + pagination (no N+1, no unbounded)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.db.models import AcceptanceCriterion, Agent, Requirement
from app.services.orchestration import agents as agent_service
from app.services.planning.requirements import list_requirements

pytestmark = pytest.mark.integration


def _seed_requirements(db: Session, project_id: uuid.UUID, count: int) -> None:
    for i in range(count):
        requirement = Requirement(project_id=project_id, title=f"req {i}", description="d")
        db.add(requirement)
        db.flush()
        db.add(AcceptanceCriterion(requirement_id=requirement.id, description="criterion"))
    db.commit()


def test_requirements_list_uses_two_queries(app: FastAPI, project: tuple) -> None:
    _app, _client, project_id, _tmp = project
    with app.state.session_factory() as session:
        _seed_requirements(session, uuid.UUID(project_id), 20)
    queries: list[str] = []
    with app.state.session_factory() as session:
        connection = session.connection()

        def observe(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
            queries.append(statement)

        event.listen(connection, "before_cursor_execute", observe)
        try:
            rows = list_requirements(session, uuid.UUID(project_id))
        finally:
            event.remove(connection, "before_cursor_execute", observe)
    assert len(rows) == 20
    assert all(len(row.criteria) == 1 for row in rows)
    assert len(queries) == 2, queries  # page + batched criteria (was N+1 = 21)


def test_requirements_pagination_tiles(app: FastAPI, project: tuple) -> None:
    _app, _client, project_id, _tmp = project
    with app.state.session_factory() as session:
        _seed_requirements(session, uuid.UUID(project_id), 7)
    with app.state.session_factory() as session:
        first = list_requirements(session, uuid.UUID(project_id), limit=5, offset=0)
        second = list_requirements(session, uuid.UUID(project_id), limit=5, offset=5)
    assert [len(first), len(second)] == [5, 2]
    assert len({row.id for row in (*first, *second)}) == 7


def test_agents_pagination_tiles(app: FastAPI, project: tuple) -> None:
    _app, _client, project_id, _tmp = project
    with app.state.session_factory() as session:
        for i in range(5):
            session.add(
                Agent(
                    project_id=uuid.UUID(project_id),
                    name=f"agent-{i}",
                    role="worker",
                    state="created",
                )
            )
        session.commit()
    with app.state.session_factory() as session:
        page = agent_service.list_agents(session, uuid.UUID(project_id), limit=3, offset=0)
        tail = agent_service.list_agents(session, uuid.UUID(project_id), limit=3, offset=3)
    assert [len(page), len(tail)] == [3, 2]
    assert len({a.id for a in (*page, *tail)}) == 5


def test_agents_pagination_over_http(project: tuple) -> None:
    app, client, project_id, _tmp = project
    with app.state.session_factory() as session:
        for i in range(3):
            session.add(
                Agent(
                    project_id=uuid.UUID(project_id),
                    name=f"http-agent-{i}",
                    role="worker",
                    state="created",
                )
            )
        session.commit()
    first = client.get(f"/api/projects/{project_id}/agents?limit=2").json()
    rest = client.get(f"/api/projects/{project_id}/agents?limit=2&offset=2").json()
    assert len(first) == 2 and len(rest) == 1


def test_memories_and_context_items_are_capped(app: FastAPI, project: tuple) -> None:
    from app.db.models import ContextItem, Memory
    from app.services.orchestration import knowledge as knowledge_service

    _app, _client, project_id, _tmp = project
    with app.state.session_factory() as session:
        for i in range(120):
            session.add(Memory(project_id=uuid.UUID(project_id), kind="fact", content=f"m{i}"))
            session.add(
                ContextItem(
                    project_id=uuid.UUID(project_id),
                    tier=3,
                    kind="file",
                    ref=f"f{i}.py",
                    summary="s",
                )
            )
        session.commit()
    with app.state.session_factory() as session:
        memories = knowledge_service.list_memories(session, uuid.UUID(project_id), None)
        items = knowledge_service.list_context_items(session, uuid.UUID(project_id), None, None)
    assert len(memories) == 100  # default cap, not all 120
    assert len(items) == 100


def test_leases_status_filter_applies_in_sql(app: FastAPI, project: tuple) -> None:
    from datetime import UTC, datetime, timedelta

    from app.db.models import Resource
    from app.services.orchestration import leases as lease_service

    _app, _client, project_id, _tmp = project
    now = datetime.now(UTC)
    tag = uuid.uuid4().hex[:8]  # (kind, key) is globally unique: never reuse keys
    with app.state.session_factory() as session:
        session.add(
            Resource(
                project_id=uuid.UUID(project_id),
                kind="port",
                key=f"active-{tag}",
                expires_at=now + timedelta(seconds=600),
            )
        )
        session.add(
            Resource(
                project_id=uuid.UUID(project_id),
                kind="port",
                key=f"expired-{tag}",
                expires_at=now - timedelta(seconds=1),
            )
        )
        session.add(
            Resource(
                project_id=uuid.UUID(project_id),
                kind="port",
                key=f"released-{tag}",
                expires_at=now + timedelta(seconds=600),
                released_at=now,
            )
        )
        session.commit()
    with app.state.session_factory() as session:
        pid = uuid.UUID(project_id)
        assert [lease.key for lease in lease_service.list_leases(session, pid, "active", 100)] == [
            f"active-{tag}"
        ]
        expired = [lease.key for lease in lease_service.list_leases(session, pid, "expired", 100)]
        assert expired == [f"expired-{tag}"]
        released = [lease.key for lease in lease_service.list_leases(session, pid, "released", 100)]
        assert released == [f"released-{tag}"]
        assert len(lease_service.list_leases(session, pid, None, 2)) == 2  # limit in SQL


def test_repeated_hot_reads_do_not_grow_python_memory(app: FastAPI, project: tuple) -> None:
    """Bounded soak regression (tracemalloc Python allocs, not RSS): 60 rounds
    of the hot read paths must not accumulate — growth past warmup stays flat."""
    import tracemalloc

    from app.services.planning.tasks import list_tasks

    _app, _client, project_id, _tmp = project
    with app.state.session_factory() as session:
        _seed_requirements(session, uuid.UUID(project_id), 10)
    pid = uuid.UUID(project_id)
    tracemalloc.start()
    try:
        with app.state.session_factory() as session:
            for _ in range(10):  # warmup
                list_tasks(session, pid, None, limit=50)
                list_requirements(session, pid, limit=50)
            _, warm_peak = tracemalloc.get_traced_memory()
            for _ in range(50):
                list_tasks(session, pid, None, limit=50)
                list_requirements(session, pid, limit=50)
            _, hot_peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    growth_mb = (hot_peak - warm_peak) / 1_000_000
    assert growth_mb < 5, f"hot-read memory grew {growth_mb:.2f} MiB past warmup"

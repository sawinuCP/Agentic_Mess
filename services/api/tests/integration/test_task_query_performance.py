"""Bounded query-count regression, with rollback-only representative task data."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.db.models import Project, Task, TaskAttempt, TaskDependency
from app.services.planning.tasks import list_tasks, task_out

pytestmark = pytest.mark.integration


@pytest.fixture()
def task_dataset(app: FastAPI, project: tuple[Any, ...]) -> Iterator[tuple[Session, uuid.UUID]]:
    with app.state.engine.connect() as connection:
        transaction = connection.begin()
        try:
            with Session(bind=connection) as db:
                pid = uuid.UUID(project[2])
                tasks = [
                    Task(
                        project_id=pid,
                        title=f"Task {i}",
                        request="fixture",
                        priority=i % 5,
                        status="pending" if i % 2 else "completed",
                    )
                    for i in range(100)
                ]
                db.add_all(tasks)
                db.flush()
                db.add_all(
                    [
                        TaskDependency(task_id=task.id, depends_on_task_id=tasks[i - 1].id)
                        for i, task in enumerate(tasks)
                        if i
                    ]
                )
                db.add_all(
                    [
                        TaskAttempt(task_id=task.id, attempt_number=n, outcome="failed")
                        for task in tasks
                        for n in (2, 1)
                    ]
                )
                other = Project(name="Other", root_path=f"/wave4-other/{uuid.uuid4()}")
                db.add(other)
                db.flush()
                db.add(Task(project_id=other.id, title="Private task", request="other project"))
                db.flush()
                yield db, pid
        finally:
            transaction.rollback()


@pytest.mark.parametrize("status, expected_count", [(None, 100), ("pending", 50), ("absent", 0)])
def test_task_list_uses_constant_queries_and_preserves_details(
    task_dataset: tuple[Session, uuid.UUID], status: str | None, expected_count: int
) -> None:
    db, pid = task_dataset
    connection = db.connection()
    queries: list[str] = []

    def observe(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        queries.append(statement)

    event.listen(connection, "before_cursor_execute", observe)
    try:
        rows = list_tasks(db, pid, status)
    finally:
        event.remove(connection, "before_cursor_execute", observe)
    assert len(queries) == (3 if expected_count else 1)
    assert len(rows) == expected_count
    assert all(row.project_id == pid for row in rows)
    for row in rows:
        task = db.get(Task, row.id)
        assert task is not None
        assert row.model_dump() == task_out(db, task).model_dump()
        assert [attempt.attempt_number for attempt in row.attempts] == [1, 2]


def test_task_list_pagination_slices_stably(task_dataset: tuple[Session, uuid.UUID]) -> None:
    db, pid = task_dataset
    first = list_tasks(db, pid, None, limit=30, offset=0)
    second = list_tasks(db, pid, None, limit=30, offset=30)
    rest = list_tasks(db, pid, None, limit=100, offset=60)
    assert [len(first), len(second), len(rest)] == [30, 30, 40]
    ids = [row.id for row in (*first, *second, *rest)]
    assert len(set(ids)) == 100  # pages tile the full set exactly once
    # Related rows stay scoped to the page and ordered.
    for row in first:
        assert [attempt.attempt_number for attempt in row.attempts] == [1, 2]
    assert all(isinstance(row.depends_on, list) for row in first)


def test_task_list_pagination_over_http(project: tuple) -> None:
    _app, client, project_id, _tmp = project
    for i in range(3):
        created = client.post(
            f"/api/projects/{project_id}/tasks",
            json={"title": f"page task {i}", "request": "paginate me"},
        )
        assert created.status_code == 201
    page = client.get(f"/api/projects/{project_id}/tasks?limit=2").json()
    assert len(page) == 2
    tail = client.get(f"/api/projects/{project_id}/tasks?limit=2&offset=2").json()
    assert len(tail) == 1
    assert {row["id"] for row in (*page, *tail)} == {
        row["id"] for row in client.get(f"/api/projects/{project_id}/tasks?limit=500").json()
    }

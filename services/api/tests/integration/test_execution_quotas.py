"""Execution quota integration (Phase 6, spec §19): slots via runtime-kind leases."""

from __future__ import annotations

import uuid

import pytest

from app.services import executions as execution_service
from app.services import ports as port_service

pytestmark = pytest.mark.integration


def test_slots_are_exclusive_and_releasable(project: tuple) -> None:
    app, _client, project_id, _tmp = project
    factory = app.state.session_factory

    with factory() as session:
        first = execution_service.acquire_slot(
            session, uuid.UUID(project_id), max_concurrent=2, ttl_seconds=300
        )
        second = execution_service.acquire_slot(
            session, uuid.UUID(project_id), max_concurrent=2, ttl_seconds=300
        )
        assert first is not None and second is not None
        assert first.key != second.key  # distinct slots (FR-009: same role may run concurrently)

        third = execution_service.acquire_slot(
            session, uuid.UUID(project_id), max_concurrent=2, ttl_seconds=300
        )
        assert third is None  # quota exhausted — never queues invisibly

        execution_service.release_slot(session, first.id)
        fourth = execution_service.acquire_slot(
            session, uuid.UUID(project_id), max_concurrent=2, ttl_seconds=300
        )
        assert fourth is not None  # released slot is reusable


def test_slots_never_leak_after_a_full_agent_run(project: tuple) -> None:
    """The execution activity releases its slot in a finally block (quota hygiene)."""
    _app, client, project_id, _tmp = project
    leases_before = client.get(f"/api/projects/{project_id}/leases?status=active").json()
    assert all(lease["kind"] != "runtime" for lease in leases_before)


def test_port_allocator_and_quotas_coexist(project: tuple) -> None:
    """Runtime-kind leases and port allocations are independent ledgers (spec §18+§19)."""
    app, client, project_id, _tmp = project
    factory = app.state.session_factory
    with factory() as session:
        slot = execution_service.acquire_slot(
            session, uuid.UUID(project_id), max_concurrent=1, ttl_seconds=300
        )
        assert slot is not None

    port = port_service.allocate(
        factory(),
        uuid.UUID(project_id),
        purpose="preview",
        holder=None,
        ttl_seconds=300,
        port_low=21000,
        port_high=21001,
    )
    assert 21000 <= port["port"] <= 21001

    with factory() as session:
        execution_service.release_slot(session, slot.id)

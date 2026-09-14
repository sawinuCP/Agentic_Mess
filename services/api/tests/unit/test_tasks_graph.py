"""Dependency-graph cycle detection (spec §18: detect cycles before scheduling)."""

from __future__ import annotations

import uuid

from app.tasks.graph import find_cycle, ready_status

A = uuid.uuid4()
B = uuid.uuid4()
C = uuid.uuid4()
D = uuid.uuid4()


def test_acyclic_addition_returns_none() -> None:
    existing = {A: [B], B: [C]}
    assert find_cycle(task_id=D, depends_on=[A], existing=existing) is None
    assert find_cycle(task_id=A, depends_on=[D], existing=existing) is None


def test_direct_cycle_is_detected() -> None:
    existing = {A: [B]}
    cycle = find_cycle(task_id=B, depends_on=[A], existing=existing)
    assert cycle is not None


def test_self_cycle_is_detected() -> None:
    cycle = find_cycle(task_id=A, depends_on=[A], existing={})
    assert cycle is not None


def test_transitive_cycle_is_detected() -> None:
    existing = {A: [B], B: [C]}
    cycle = find_cycle(task_id=C, depends_on=[A], existing=existing)
    assert cycle is not None


def test_ready_status_depends_on_completion() -> None:
    assert ready_status([B, C], {B, C}) == "ready"
    assert ready_status([B, C], {B}) == "blocked"
    assert ready_status([], set()) == "ready"

"""Recovery executor activities against live PostgreSQL (Wave 2, prompt §19).

Activity-level tests: idempotency keys deduplicate durable effects, the budget
gate routes expensive recoveries through HITL, terminal failures carry evidence,
agent sessions drain safely, and dependents resolve for dependency waits. The
full Temporal ladder is exercised by scripts/smoke_durable.py against a live
Temporal server.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models import Agent, AgentSession, Event, Task, TaskDependency
from app.durable.activities import (
    end_agent_session_activity,
    init_refs,
    recovery_budget_activity,
    replan_task_activity,
    spawn_child_task_activity,
    task_dependents_activity,
    terminal_failure_activity,
)
from app.durable.activities.hitl import hitl_recovery_gate
from app.services.intelligence import costs as cost_service
from app.services.orchestration import hitl as hitl_service

pytestmark = pytest.mark.integration


@pytest.fixture()
def wired(app: FastAPI, repo_root: Path) -> Iterator[tuple[FastAPI, str]]:
    root = repo_root
    with TestClient(app):
        init_refs(app.state.session_factory, app.state.artifacts, app.state.settings)
        response = TestClient(app).post("/api/projects/open", json={"root_path": str(root)})
        project_id = response.json()["id"]
        yield app, project_id


def _create_task(app: FastAPI, project_id: str, payload: dict | None = None) -> str:
    with app.state.session_factory() as session:
        task = Task(
            project_id=uuid.UUID(project_id),
            title="recovery target",
            request="do work",
            payload=payload or {},
        )
        session.add(task)
        session.commit()
        return str(task.id)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# --- budget gate (prompt §9) ---------------------------------------------------


def test_budget_gate_blocks_expensive_recovery_when_exhausted(
    wired: tuple[FastAPI, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    app, project_id = wired
    task_id = _create_task(app, project_id)
    monkeypatch.setattr(app.state.settings, "model_budget_tokens_per_task", 10)
    with app.state.session_factory() as session:
        cost_service.record_invocation(
            session,
            project_id=uuid.UUID(project_id),
            task_id=uuid.UUID(task_id),
            agent_id=None,
            role="worker",
            provider="rehearsal",
            model="rehearsal-worker",
            prompt_tokens=50,
            completion_tokens=50,
        )
    result = _run(recovery_budget_activity({"task_id": task_id}))
    assert result["within_budget"] is False
    assert result["tokens_used"] >= 100


def test_budget_gate_passes_when_no_budget_configured(wired: tuple[FastAPI, str]) -> None:
    app, project_id = wired
    task_id = _create_task(app, project_id)
    result = _run(recovery_budget_activity({"task_id": task_id}))
    assert result["within_budget"] is True


# --- debugger/integration child tasks + idempotency (prompt §17) ----------------


def test_spawn_debugger_is_idempotent(wired: tuple[FastAPI, str]) -> None:
    app, project_id = wired
    task_id = _create_task(app, project_id)
    key = f"child:{task_id}:attempt-1"
    spawn_input = {
        "idempotency_key": key,
        "task_id": task_id,
        "child_kind": "debug",
        "failure_class": "TOOL_FAILURE",
        "failure_detail": "command 0 failed",
        "attempt_id": str(uuid.uuid4()),
        "evidence_artifact_ids": [],
    }
    first = _run(spawn_child_task_activity(spawn_input))
    second = _run(spawn_child_task_activity(spawn_input))
    assert first["created"] is True
    assert second == {"child_task_id": first["child_task_id"], "created": False}
    with app.state.session_factory() as session:
        children = session.scalars(
            select(Task).where(Task.parent_task_id == uuid.UUID(task_id))
        ).all()
        assert len(children) == 1
        assert children[0].payload["failure_class"] == "TOOL_FAILURE"
        events = session.scalars(
            select(Event).where(
                Event.event_type == "DEBUGGER_SPAWNED", Event.task_id == uuid.UUID(task_id)
            )
        ).all()
        assert len(events) == 1  # the retried activity did not duplicate the event


# --- replanning (REC-003, prompt §7 REPLAN_TASK) ---------------------------------


def test_replan_creates_followup_task_and_is_idempotent(wired: tuple[FastAPI, str]) -> None:
    app, project_id = wired
    task_id = _create_task(app, project_id)
    replan_input = {
        "idempotency_key": f"replan:{task_id}",
        "task_id": task_id,
        "failure_class": "TASK_FAILURE",
        "failure_detail": "exit_code=1",
        "evidence_artifact_ids": [],
    }
    first = _run(replan_task_activity(replan_input))
    second = _run(replan_task_activity(replan_input))
    assert first["created"] is True
    assert second["replan_task_id"] == first["replan_task_id"]
    assert second["created"] is False
    with app.state.session_factory() as session:
        child = session.get(Task, uuid.UUID(first["replan_task_id"]))
        assert child is not None
        assert child.payload["kind"] == "replan"
        assert child.parent_task_id == uuid.UUID(task_id)


# --- terminal failure (prompt §7 FAIL_TERMINALLY) --------------------------------


def test_terminal_failure_records_evidence_once(wired: tuple[FastAPI, str]) -> None:
    app, project_id = wired
    task_id = _create_task(app, project_id)
    payload = {
        "idempotency_key": f"terminal:{task_id}",
        "task_id": task_id,
        "recovery_id": "rec-1",
        "action": "stop",
        "failure_class": "SECURITY_BLOCK",
        "failure_detail": "HITL rejected: allowlist violation",
        "evidence_artifact_ids": ["a" * 32],
        "recommended_action": "Resolve the policy violation",
    }
    assert _run(terminal_failure_activity(payload)) == {"recorded": True}
    assert _run(terminal_failure_activity(payload)) == {"recorded": False}
    with app.state.session_factory() as session:
        task = session.get(Task, uuid.UUID(task_id))
        terminal = (task.payload or {}).get("terminal", {}) if task else {}
        assert terminal["failure_class"] == "SECURITY_BLOCK"
        assert terminal["recommended_action"] == "Resolve the policy violation"
        assert terminal["evidence_artifact_ids"] == ["a" * 32]
        events = session.scalars(
            select(Event).where(
                Event.event_type == "TASK_TERMINALLY_FAILED",
                Event.task_id == uuid.UUID(task_id),
            )
        ).all()
        assert len(events) == 1


# --- agent replacement safety (prompt §11) ----------------------------------------


def test_end_agent_session_drains_and_is_idempotent(wired: tuple[FastAPI, str]) -> None:
    app, project_id = wired
    with app.state.session_factory() as session:
        agent = Agent(
            project_id=uuid.UUID(project_id), name="agent-x", role="worker", state="running"
        )
        session.add(agent)
        session.flush()
        agent_session = AgentSession(agent_id=agent.id, status="running")
        session.add(agent_session)
        session.commit()
        agent_id, session_id = str(agent.id), str(agent_session.id)

    payload = {"agent_id": agent_id, "session_id": session_id}
    assert _run(end_agent_session_activity(payload)) == {"ended": True}
    assert _run(end_agent_session_activity(payload)) == {"ended": True}
    with app.state.session_factory() as session:
        assert session.get(AgentSession, uuid.UUID(session_id)).status == "ended"
        assert session.get(Agent, uuid.UUID(agent_id)).state == "failed"


# --- dependency resolution (prompt §12) --------------------------------------------


def test_task_dependents_resolves_the_graph(wired: tuple[FastAPI, str]) -> None:
    app, project_id = wired
    task_a = _create_task(app, project_id)
    task_b = _create_task(app, project_id)
    with app.state.session_factory() as session:
        session.add(TaskDependency(task_id=uuid.UUID(task_b), depends_on_task_id=uuid.UUID(task_a)))
        session.commit()
    result = _run(task_dependents_activity({"task_id": task_a}))
    assert result["dependent_task_ids"] == [task_b]


# --- HITL recovery gate (prompt §13) ------------------------------------------------


def test_hitl_recovery_gate_approved_flow(wired: tuple[FastAPI, str]) -> None:
    app, project_id = wired
    task_id = _create_task(app, project_id)
    decision = {
        "recovery_id": f"rec-hitl-{uuid.uuid4().hex[:8]}",
        "action": "escalate_model",
        "failure_class": "MODEL_FAILURE",
        "action_reason": "Repeated model failures",
    }
    result_box: dict[str, Any] = {}

    def _gate() -> None:
        result_box["gate"] = asyncio.run(
            hitl_recovery_gate(
                project_id=project_id,
                task_id=uuid.UUID(task_id),
                decision=decision,
                failure_detail="provider openai returned 500",
                evidence_artifact_ids=[],
                timeout_seconds=15,
                poll_seconds=0.2,
            )
        )

    thread = threading.Thread(target=_gate)
    thread.start()
    request_id = None
    for _ in range(100):
        with app.state.session_factory() as session:
            mine = [
                r
                for r in hitl_service.list_requests(session, status="pending")
                if str(r.task_id) == task_id
            ]
            if mine:
                request_id = mine[0].id
                break
        thread.join(timeout=0.2)
    assert request_id is not None, "gate did not create a durable request"
    with app.state.session_factory() as session:
        decided = hitl_service.decide_request(session, request_id, "approved", "human", "go")
        assert decided.status == "approved"
    thread.join(timeout=20)
    gate = result_box["gate"]
    assert gate["approved"] is True
    assert gate["status"] == "approved"


def test_hitl_recovery_gate_timeout_fails_closed(wired: tuple[FastAPI, str]) -> None:
    app, project_id = wired
    task_id = _create_task(app, project_id)
    gate = _run(
        hitl_recovery_gate(
            project_id=project_id,
            task_id=uuid.UUID(task_id),
            decision={
                "recovery_id": f"rec-hitl-{uuid.uuid4().hex[:8]}",
                "action": "spawn_debugger",
                "failure_class": "TASK_FAILURE",
                "action_reason": "needs a debugger",
            },
            failure_detail="command failed",
            evidence_artifact_ids=[],
            timeout_seconds=0.5,
            poll_seconds=0.1,
        )
    )
    assert gate["approved"] is False
    assert gate["status"] == "timeout"


def test_cancelled_request_fails_closed_for_waiters(wired: tuple[FastAPI, str]) -> None:
    import threading

    from app.core.errors import DomainError

    app, project_id = wired
    task_id = _create_task(app, project_id)
    result_box: dict[str, Any] = {}

    def _gate() -> None:
        result_box["gate"] = asyncio.run(
            hitl_recovery_gate(
                project_id=project_id,
                task_id=uuid.UUID(task_id),
                decision={
                    "recovery_id": f"rec-hitl-{uuid.uuid4().hex[:8]}",
                    "action": "request_hitl",
                    "failure_class": "RESOURCE_LIMIT",
                    "action_reason": "needs an operator",
                },
                failure_detail="disk quota exceeded",
                evidence_artifact_ids=[],
                timeout_seconds=15,
                poll_seconds=0.2,
            )
        )

    thread = threading.Thread(target=_gate)
    thread.start()
    request_id = None
    for _ in range(100):
        with app.state.session_factory() as session:
            mine = [
                r
                for r in hitl_service.list_requests(session, status="pending")
                if str(r.task_id) == task_id
            ]
            if mine:
                request_id = mine[0].id
                break
        thread.join(timeout=0.2)
    assert request_id is not None, "gate did not create a durable request"
    with app.state.session_factory() as session:
        cancelled = hitl_service.cancel_request(session, request_id, "operator")
        assert cancelled.status == "cancelled"
        # Terminal requests cannot be cancelled again — or decided.
        with pytest.raises(DomainError):
            hitl_service.cancel_request(session, request_id, "operator")
    thread.join(timeout=20)
    gate = result_box["gate"]
    assert gate["approved"] is False
    assert gate["status"] == "cancelled"


def test_cancel_endpoint_withdraws_pending_requests(project: tuple) -> None:
    _app, client, project_id, _tmp = project
    with _app.state.session_factory() as session:
        request = hitl_service.create_request(
            session,
            project_id=uuid.UUID(project_id),
            kind="approve_command",
            question="May I proceed?",
        )
        request_id = str(request.id)
    cancelled = client.post(
        f"/api/projects/{project_id}/hitl/{request_id}/cancel",
        json={"decided_by": "operator"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    again = client.post(
        f"/api/projects/{project_id}/hitl/{request_id}/cancel",
        json={"decided_by": "operator"},
    )
    assert again.status_code == 409


def test_spawned_children_are_scheduler_visible(wired: tuple[FastAPI, str]) -> None:
    """Child follow-through: debugger/replan children are born `pending`, so
    the next scheduler tick picks them up for durable execution — they do not
    dangle as dead rows."""
    from app.services.orchestration.scheduler import SchedulingLimits, plan_schedule

    app, project_id = wired
    task_id = _create_task(app, project_id)
    for kind in ("debug", "replan"):
        _run(
            spawn_child_task_activity(
                {
                    "idempotency_key": f"child:{task_id}:{kind}",
                    "task_id": task_id,
                    "child_kind": kind,
                    "failure_class": "TASK_FAILURE",
                    "failure_detail": "command failed",
                    "attempt_id": str(uuid.uuid4()),
                    "evidence_artifact_ids": [],
                }
            )
        )
    with app.state.session_factory() as session:
        tick = plan_schedule(
            session,
            uuid.UUID(project_id),
            SchedulingLimits(max_concurrency=4, role_limits={}, spawn_max_depth=2),
        )
        scheduled_ids = {entry.task_id for entry in tick.scheduled}
        children = session.scalars(
            select(Task).where(Task.parent_task_id == uuid.UUID(task_id))
        ).all()
        assert len(children) == 2
        assert all(child.status == "pending" for child in children)
        assert {child.id for child in children} <= scheduled_ids


def test_concurrent_hitl_decisions_have_exactly_one_winner(
    wired: tuple[FastAPI, str],
) -> None:
    """Race: N concurrent deciders on one pending request → one success,
    N-1 clean 409s, single terminal state (no split decision)."""
    import concurrent.futures
    import threading

    from app.core.errors import DomainError

    app, project_id = wired
    task_id = _create_task(app, project_id)
    with app.state.session_factory() as session:
        request = hitl_service.create_request(
            session,
            project_id=uuid.UUID(project_id),
            task_id=uuid.UUID(task_id),
            kind="approve_command",
            question="Race me",
        )
        request_id = request.id

    # Barrier: all voters fire simultaneously for a real collision window.
    gate = threading.Barrier(8)

    def _decide(voter: int) -> str:
        gate.wait(timeout=30)
        try:
            with app.state.session_factory() as session:
                decision = hitl_service.decide_request(
                    session, request_id, "approved", f"voter-{voter}", None
                )
                return str(decision.status)
        except DomainError as exc:
            return f"rejected:{exc.status_code}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(_decide, range(8)))
    assert outcomes.count("approved") == 1, outcomes
    assert all(o == "rejected:409" for o in outcomes if o != "approved")
    with app.state.session_factory() as session:
        final = hitl_service.get_request(session, request_id)
        assert final.status == "approved"
        assert final.decided_by is not None

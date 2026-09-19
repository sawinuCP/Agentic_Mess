"""Evaluation metrics over durable rows: orchestration counts and message health."""

from __future__ import annotations

import uuid

import pytest

from app.db.models import Agent, Event, Message, Task, TaskAttempt
from app.evaluation.metrics import communication_health, execution_metrics

pytestmark = pytest.mark.integration


def _seed_task(db, project_id: uuid.UUID) -> uuid.UUID:
    task = Task(project_id=project_id, title="measured", request="run", payload={})
    db.add(task)
    db.flush()
    agent = Agent(project_id=project_id, name="m-agent", role="worker", state="completed")
    db.add(agent)
    db.flush()
    for number in (1, 2):
        db.add(
            TaskAttempt(
                task_id=task.id,
                attempt_number=number,
                agent_id=agent.id,
                outcome="failed" if number == 1 else "success",
            )
        )
    for event_type in ("RECOVERY_SELECTED", "RETRY_STARTED", "TOOL_STARTED", "TOOL_COMPLETED"):
        db.add(
            Event(
                event_type=event_type,
                source="metrics-test",
                project_id=project_id,
                task_id=task.id,
                payload={},
            )
        )
    task.status = "completed"
    db.commit()
    return task.id


def test_execution_metrics_counts_durable_facts(project: tuple) -> None:
    app, _client, project_id, _tmp = project
    with app.state.session_factory() as session:
        task_id = _seed_task(session, uuid.UUID(project_id))
        metrics = execution_metrics(session, task_id)
    assert metrics["task_status"] == "completed"
    assert metrics["attempt_count"] == 2
    assert metrics["agent_count"] == 1
    assert metrics["retry_count"] == 1
    assert metrics["retry_rate"] == pytest.approx(0.5)
    assert metrics["recovery_count"] == 1
    assert metrics["recovery_success"] is True
    assert metrics["tool_call_count"] == 1
    assert metrics["tool_success_rate"] == pytest.approx(1.0)
    assert metrics["tool_failed_count"] == 0
    assert metrics["terminal_failure"] is False
    assert metrics["input_tokens"] is None  # honestly unavailable, never fabricated


def test_execution_metrics_unknown_task_rejected(project: tuple) -> None:
    app, _client, _project_id, _tmp = project
    with app.state.session_factory() as session, pytest.raises(ValueError, match="Task not found"):
        execution_metrics(session, uuid.uuid4())


def _send(db, conversation_id, **overrides) -> Message:
    params = {
        "conversation_id": conversation_id,
        "type": "request",
        "payload": {},
    }
    params.update(overrides)
    message = Message(**params)
    db.add(message)
    db.flush()
    return message


def test_communication_health_flags_orphans_duplicates_unanswered(
    project: tuple,
) -> None:
    app, _client, _project_id, _tmp = project
    conversation_id = uuid.uuid4()
    with app.state.session_factory() as session:
        first = _send(session, conversation_id, type="request", correlation_id="c1")
        _send(session, conversation_id, type="request", correlation_id="c1")  # duplicate
        _send(
            session,
            conversation_id,
            type="question",
            correlation_id="q9",  # never answered
        )
        _send(session, conversation_id, reply_to=uuid.uuid4())  # orphan reply
        answered = _send(session, conversation_id, type="question", correlation_id="q1")
        _send(
            session,
            conversation_id,
            type="response",
            correlation_id="q1",
            reply_to=answered.id,
        )
        session.commit()
        health = communication_health(session, conversation_id)
    assert health["message_count"] == 6
    assert health["by_type"] == {"request": 3, "question": 2, "response": 1}
    assert health["orphan_reply_count"] == 1
    assert health["duplicate_count"] == 1
    assert health["unanswered_question_count"] == 1
    assert health["healthy"] is False
    assert first.id is not None


def test_communication_health_clean_conversation(project: tuple) -> None:
    app, _client, _project_id, _tmp = project
    conversation_id = uuid.uuid4()
    with app.state.session_factory() as session:
        question = _send(session, conversation_id, type="question", correlation_id="q1")
        _send(
            session,
            conversation_id,
            type="response",
            correlation_id="q1",
            reply_to=question.id,
        )
        session.commit()
        health = communication_health(session, conversation_id)
    assert health["healthy"] is True
    assert health["message_count"] == 2

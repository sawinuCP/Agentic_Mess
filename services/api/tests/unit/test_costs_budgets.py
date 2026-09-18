"""Model budget ledger helpers: per-task/per-agent tokens and invocation counts."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import ModelInvocation
from app.services.intelligence import costs as cost_service


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.tables[ModelInvocation.__tablename__].create(engine)
    with Session(engine) as session:
        yield session


def _record(
    session: Session,
    *,
    task_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    tokens: int = 100,
) -> None:
    cost_service.record_invocation(
        session,
        project_id=None,
        task_id=task_id,
        agent_id=agent_id,
        role="worker",
        provider="rehearsal",
        model="rehearsal-worker",
        prompt_tokens=tokens,
        completion_tokens=0,
        cost_usd=0.0,
    )


def test_tokens_for_task_and_agent(session: Session) -> None:
    task_a, task_b = uuid.uuid4(), uuid.uuid4()
    agent_x, agent_y = uuid.uuid4(), uuid.uuid4()
    _record(session, task_id=task_a, agent_id=agent_x, tokens=100)
    _record(session, task_id=task_a, agent_id=agent_y, tokens=50)
    _record(session, task_id=task_b, agent_id=agent_x, tokens=25)

    assert cost_service.tokens_for_task(session, task_a) == 150
    assert cost_service.tokens_for_task(session, task_b) == 25
    assert cost_service.tokens_for_agent(session, agent_x) == 125
    assert cost_service.tokens_for_agent(session, agent_y) == 50
    assert cost_service.tokens_for_task(session, uuid.uuid4()) == 0
    assert cost_service.tokens_for_agent(session, uuid.uuid4()) == 0


def test_invocations_for_task_and_agent(session: Session) -> None:
    task_a, task_b = uuid.uuid4(), uuid.uuid4()
    agent_x = uuid.uuid4()
    _record(session, task_id=task_a, agent_id=agent_x)
    _record(session, task_id=task_a, agent_id=None)
    _record(session, task_id=task_b, agent_id=agent_x)

    assert cost_service.invocations_for_task(session, task_a) == 2
    assert cost_service.invocations_for_task(session, task_b) == 1
    assert cost_service.invocations_for_task(session, uuid.uuid4()) == 0
    assert cost_service.invocations_for_agent(session, agent_x) == 2
    assert cost_service.invocations_for_agent(session, uuid.uuid4()) == 0

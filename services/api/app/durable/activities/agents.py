"""Agent activities: disposable agent creation + validated lifecycle transitions (spec §11/§12)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from temporalio import activity

from app.agents_runtime.lifecycle import assert_transition
from app.db.models import Agent, AgentSession, Event, TaskAttempt
from app.durable.activities._context import load_task_row, refs


@activity.defn
async def start_agent_activity(input: dict[str, Any]) -> dict[str, Any]:
    """Create the agent for this attempt (spec §11: agents are disposable).

    Replacement semantics (FR-008): attempt N>1 records which failed agent it
    replaces; task identity is preserved across the replacement.
    """
    factory, _store = refs()

    def _start() -> dict[str, Any]:
        with factory() as session:
            task_id = uuid.UUID(input["task_id"])
            attempt_id = uuid.UUID(input["attempt_id"])
            task = load_task_row(session, task_id)
            role = str((task.payload or {}).get("agent_role", "worker"))
            agent = Agent(
                project_id=task.project_id,
                name=f"agent-{task_id.hex[:8]}-a{input['attempt_number']}",
                role=role,
                model=None,  # resolved by the model registry at execution time
                capabilities=["shell"],
                state="created",
            )
            session.add(agent)
            attempt = session.get(TaskAttempt, attempt_id)
            if attempt is not None:
                attempt.agent_id = agent.id
            session_row = AgentSession(
                agent_id=agent.id, runtime="temporal-worker", heartbeat_at=datetime.now(UTC)
            )
            session.add(session_row)
            session.add(
                Event(
                    event_type="AGENT_CREATED",
                    source="temporal",
                    project_id=task.project_id,
                    task_id=task_id,
                    payload={
                        "agent_id": str(agent.id),
                        "role": role,
                        "replaces_agent_id": input.get("replaces_agent_id"),
                        "session_id": str(session_row.id),
                    },
                )
            )
            session.commit()
            return {
                "agent_id": str(agent.id),
                "session_id": str(session_row.id),
                "role": role,
                "state": agent.state,
            }

    return await asyncio.to_thread(_start)


@activity.defn
async def set_agent_state_activity(input: dict[str, Any]) -> dict[str, Any]:
    """Validate + apply an agent lifecycle transition (spec §12) and emit an event."""
    factory, _store = refs()

    def _apply() -> dict[str, Any]:
        with factory() as session:
            agent = session.get(Agent, uuid.UUID(input["agent_id"]))
            if agent is None:
                raise RuntimeError(f"Agent not found: {input['agent_id']}")
            assert_transition(agent.state, input["state"])
            previous = agent.state
            agent.state = input["state"]
            session.add(
                Event(
                    event_type="AGENT_STATUS_CHANGED",
                    source="temporal",
                    project_id=agent.project_id,
                    agent_id=str(agent.id),
                    payload={"from": previous, "to": agent.state},
                )
            )
            session.commit()
            return {"agent_id": str(agent.id), "from": previous, "to": agent.state}

    return await asyncio.to_thread(_apply)


async def heartbeat_session(session_id: str) -> None:
    """Refresh an agent session heartbeat (spec §12: mandatory while running)."""
    if not session_id:
        return
    factory, _store = refs()

    def _beat() -> None:
        with factory() as session:
            row = session.get(AgentSession, uuid.UUID(session_id))
            if row is not None and row.status == "running":
                row.heartbeat_at = datetime.now(UTC)
                session.commit()

    await asyncio.to_thread(_beat)

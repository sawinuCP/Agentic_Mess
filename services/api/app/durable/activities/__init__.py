"""Workflow activities package: every DB write and process execution happens here.

Grouped by concern — ``tasks`` (durable task/attempt lifecycle), ``agents``
(disposable agent lifecycle), ``execution`` (the agent work unit), ``hitl``
(approval gate) — with the public activity surface re-exported so the worker
registration and tests can import from ``app.durable.activities`` unchanged.
"""

from __future__ import annotations

from app.durable.activities._context import init_refs
from app.durable.activities.agents import (
    heartbeat_session,
    set_agent_state_activity,
    start_agent_activity,
)
from app.durable.activities.execution import agent_execute_activity
from app.durable.activities.hitl import hitl_gate
from app.durable.activities.tasks import (
    execute_work_activity,
    finish_attempt_activity,
    load_task_activity,
    record_event_activity,
    set_task_status_activity,
    start_attempt_activity,
)

__all__ = [
    "agent_execute_activity",
    "execute_work_activity",
    "finish_attempt_activity",
    "heartbeat_session",
    "hitl_gate",
    "init_refs",
    "load_task_activity",
    "record_event_activity",
    "set_agent_state_activity",
    "set_task_status_activity",
    "start_agent_activity",
    "start_attempt_activity",
]

"""Temporal worker entrypoint: ``python -m app.durable.worker`` (cwd: services/api).

Requires: Temporal server reachable (compose profile ``temporal``) and
HARNESS_DATABASE_URL pointing at the same database as the API.

Wave 3: when ``HARNESS_NATS_EVENTS_ENABLED`` is on, the worker also runs the
event bus + bridge so activity/workflow event writes (AGENT_*, TASK_*,
HITL_*, recovery events) stream to realtime subscribers exactly like API-side
writes. The gateway itself lives in the API process.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from temporalio.client import Client
from temporalio.worker import Worker

from app.artifacts.store import ArtifactStore
from app.core.config import Settings
from app.core.logging import configure_logging
from app.core.metrics import MetricsRegistry
from app.db.base import build_engine, build_session_factory
from app.durable.activities import (
    agent_execute_activity,
    dependency_status_activity,
    end_agent_session_activity,
    execute_work_activity,
    finish_attempt_activity,
    hitl_recovery_gate_activity,
    init_refs,
    load_task_activity,
    record_event_activity,
    recovery_budget_activity,
    replan_task_activity,
    rollback_attempt_activity,
    set_agent_state_activity,
    set_task_status_activity,
    spawn_child_task_activity,
    start_agent_activity,
    start_attempt_activity,
    task_dependents_activity,
    terminal_failure_activity,
)
from app.durable.workflows import TaskExecutionWorkflow


async def main() -> None:
    settings = Settings()
    configure_logging(settings.log_level)

    client = await Client.connect(settings.temporal_address, namespace="default")
    engine = build_engine(
        settings.database_url, connect_timeout_seconds=settings.readiness_timeout_seconds
    )
    init_refs(build_session_factory(engine), ArtifactStore(Path(settings.artifacts_dir)), settings)

    # Wave 3: stream worker-side durable events to the realtime pipeline.
    bus = None
    bridge = None
    if settings.nats_events_enabled:
        from app.realtime import bridge as realtime_bridge  # noqa: PLC0415
        from app.realtime.bus import EventBus  # noqa: PLC0415

        bus = EventBus(settings, MetricsRegistry())
        await bus.start()
        realtime_bridge.activate_bus(bus)
        realtime_bridge.install_listeners()
        bridge = realtime_bridge

    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[TaskExecutionWorkflow],
        max_concurrent_workflow_tasks=max(1, settings.temporal_max_concurrent_workflows),
        max_concurrent_activities=max(1, settings.temporal_max_concurrent_activities),
        max_activities_per_second=(float(settings.temporal_max_activities_per_second) or None),
        activities=[
            load_task_activity,
            start_attempt_activity,
            agent_execute_activity,
            execute_work_activity,
            finish_attempt_activity,
            set_task_status_activity,
            set_agent_state_activity,
            start_agent_activity,
            record_event_activity,
            recovery_budget_activity,
            spawn_child_task_activity,
            replan_task_activity,
            rollback_attempt_activity,
            terminal_failure_activity,
            end_agent_session_activity,
            task_dependents_activity,
            dependency_status_activity,
            hitl_recovery_gate_activity,
        ],
    )
    print(f"temporal worker ready queue={settings.temporal_task_queue}")  # noqa: T201
    try:
        await worker.run()
    finally:
        if bridge is not None:
            bridge.deactivate_bus()
        if bus is not None:
            await bus.close()
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

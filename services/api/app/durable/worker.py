"""Temporal worker entrypoint: ``python -m app.durable.worker`` (cwd: services/api).

Requires: Temporal server reachable (compose profile ``temporal``) and
HARNESS_DATABASE_URL pointing at the same database as the API.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from temporalio.client import Client
from temporalio.worker import Worker

from app.artifacts.store import ArtifactStore
from app.core.config import Settings
from app.core.logging import configure_logging
from app.db.base import build_engine, build_session_factory
from app.durable.activities import (
    agent_execute_activity,
    execute_work_activity,
    finish_attempt_activity,
    init_refs,
    load_task_activity,
    record_event_activity,
    set_agent_state_activity,
    set_task_status_activity,
    start_agent_activity,
    start_attempt_activity,
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

    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[TaskExecutionWorkflow],
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
        ],
    )
    print(f"temporal worker ready queue={settings.temporal_task_queue}")  # noqa: T201
    await worker.run()
    engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

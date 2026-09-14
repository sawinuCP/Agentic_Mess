"""Temporal client provider and workflow start. Opt-in via HARNESS_TEMPORAL_ENABLED."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.core.config import Settings

logger = logging.getLogger("harness.durable")


class DurableUnavailable(Exception):
    """Temporal is disabled or unreachable; callers map this to HTTP 503."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.message = detail


class DurableTasks:
    """Lazily-connected Temporal client. Never raises for connection issues at
    construction; failures surface on use as ``DurableUnavailable``."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any = None

    @property
    def enabled(self) -> bool:
        return self._settings.temporal_enabled

    async def _connect(self) -> Any:
        from temporalio.client import Client  # noqa: PLC0415 — heavy import, on demand

        return await Client.connect(self._settings.temporal_address, namespace="default")

    async def client(self) -> Any:
        if not self.enabled:
            raise DurableUnavailable(
                "Temporal integration is disabled (set HARNESS_TEMPORAL_ENABLED=true "
                "and start the 'temporal' compose profile)"
            )
        if self._client is None:
            try:
                self._client = await self._connect()
            except Exception as exc:  # noqa: BLE001 — any connect failure is "unavailable"
                logger.warning("temporal_connect_failed error=%s", exc)
                raise DurableUnavailable(
                    f"Temporal server unreachable at {self._settings.temporal_address}: {exc}"
                ) from None
        return self._client

    async def start_task_execution(self, task_id: uuid.UUID) -> dict[str, str]:
        """Start the durable TaskExecutionWorkflow for a task."""
        from app.durable.workflows import TaskExecutionInput, TaskExecutionWorkflow  # noqa: PLC0415

        client = await self.client()
        handle = await client.start_workflow(
            TaskExecutionWorkflow.run,
            TaskExecutionInput(task_id=str(task_id)),
            id=f"task-exec-{task_id}",
            task_queue=self._settings.temporal_task_queue,
        )
        return {
            "workflow_id": handle.id,
            "run_id": handle.result_run_id or handle.first_execution_run_id or "",
        }

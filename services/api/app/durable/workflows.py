"""Durable task-execution workflow.

Deterministic orchestration only: every side effect (DB reads/writes, process
execution) is an activity. Bounded retries with durable backoff timers, attempt
records preserved with evidence (TASK-002/003, REC-001/002).

Activity names are referenced by string; the worker registers functions with
exactly these names (see ``app.durable.activities``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

RETRY_NONE = RetryPolicy(maximum_attempts=1)
RETRY_DB = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=0.5))


@dataclass
class TaskExecutionInput:
    task_id: str


@workflow.defn
class TaskExecutionWorkflow:
    """Execute one durable task: attempts with bounded retries and evidence.

    The Phase 3 agent runtime plugs into ``execute_work_activity``; until then the
    honest work unit is a command supplied on the task payload (``payload.command``).
    """

    @workflow.run
    async def run(self, input: TaskExecutionInput) -> dict:
        task = await workflow.execute_activity(
            "load_task_activity",
            input.task_id,
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RETRY_DB,
        )
        retry_policy = task.get("retry_policy") or {}
        max_attempts = max(1, min(int(retry_policy.get("max_attempts", 3)), 10))
        backoff = max(0.0, float(retry_policy.get("backoff_seconds", 2)))

        await workflow.execute_activity(
            "set_task_status_activity",
            {"task_id": input.task_id, "status": "running"},
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RETRY_DB,
        )

        summary: dict = {"task_id": input.task_id, "attempts": 0, "outcome": "failed"}
        for attempt_number in range(1, max_attempts + 1):
            summary["attempts"] = attempt_number
            attempt = await workflow.execute_activity(
                "start_attempt_activity",
                {"task_id": input.task_id, "attempt_number": attempt_number},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RETRY_DB,
            )
            result = await workflow.execute_activity(
                "execute_work_activity",
                {
                    "task_id": input.task_id,
                    "attempt_id": attempt["id"],
                    "project_id": task["project_id"],
                    "payload": task.get("payload", {}),
                },
                start_to_close_timeout=timedelta(
                    seconds=max(60, float(task.get("payload", {}).get("timeout_seconds", 300)))
                ),
                retry_policy=RETRY_NONE,
            )
            await workflow.execute_activity(
                "finish_attempt_activity",
                {
                    "attempt_id": attempt["id"],
                    "outcome": result["outcome"],
                    "failure_class": result.get("failure_class"),
                    "failure_detail": result.get("failure_detail"),
                    "evidence_artifact_ids": result.get("evidence_artifact_ids", []),
                },
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RETRY_DB,
            )
            if result["outcome"] == "success":
                summary["outcome"] = "success"
                break
            if attempt_number < max_attempts:
                await workflow.sleep(backoff)  # durable timer — survives restarts

        final_status = "completed" if summary["outcome"] == "success" else "failed"
        await workflow.execute_activity(
            "set_task_status_activity",
            {"task_id": input.task_id, "status": final_status},
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RETRY_DB,
        )
        await workflow.execute_activity(
            "record_event_activity",
            {
                "task_id": input.task_id,
                "event_type": "TASK_COMPLETED" if final_status == "completed" else "TASK_FAILED",
                "payload": summary,
            },
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RETRY_DB,
        )
        return summary

"""Durable task-execution workflow — the authoritative RECOVERY coordinator.

Deterministic orchestration only: every side effect (DB reads/writes, process
execution) is an activity; recovery decisions are computed with the pure policy
core (:func:`app.services.orchestration.recovery.recovery_decision`) and executed
through durable activities. Wave 2 invariant: a recovery decision always results
in a real bounded action or an explicit terminal/HITL state — never an advisory
field. Bounded retries with durable backoff timers, attempt records preserved
with evidence (TASK-002/003, REC-001/002/003).

Activity names are referenced by string; the worker registers functions with
exactly these names (see ``app.durable.activities``).
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from app.services.orchestration.recovery import recovery_decision

RETRY_NONE = RetryPolicy(maximum_attempts=1)
RETRY_DB = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=0.5))

_ACTIVITY_TIMEOUT = timedelta(seconds=30)


@dataclass
class TaskExecutionInput:
    task_id: str


@workflow.defn
class TaskExecutionWorkflow:
    """Execute one durable task with a disposable agent (spec §11-§13).

    Pause/resume are first-class: the ``pause``/``resume`` signals set a flag the
    workflow waits on between activities; the agent reaches a safe checkpoint
    (between atomic steps) and its lifecycle state is recorded durably.

    Recovery (Wave 2): after every failed attempt the workflow computes a
    deterministic, bounded recovery decision and EXECUTES it — retry with
    durable backoff, compacted context, model escalation, agent replacement,
    debugger/integration child tasks, dependency waits via durable signals,
    HITL gates (fail-closed) or a terminal failure with evidence. The ladder
    cannot loop: attempt bounds are enforced and every retryable class ends in
    ``escalate_or_replan``.
    """

    def __init__(self) -> None:
        self._paused = False
        self._dependency_completed = False

    @workflow.signal
    def pause(self) -> None:
        self._paused = True

    @workflow.signal
    def resume(self) -> None:
        self._paused = False

    @workflow.signal
    def dependency_completed(self) -> None:
        """A task this task depends on finished (durable resume for WAIT)."""
        self._dependency_completed = True

    async def _checkpoint(self, agent_id: str | None) -> None:
        """Safe checkpoint between activities: suspends new work while pausing."""
        if agent_id is None or not self._paused:
            return
        await workflow.execute_activity(
            "set_agent_state_activity",
            {"agent_id": agent_id, "state": "paused"},
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=RETRY_DB,
        )
        await workflow.wait_condition(lambda: not self._paused)
        await workflow.execute_activity(
            "set_agent_state_activity",
            {"agent_id": agent_id, "state": "resuming"},
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=RETRY_DB,
        )

    async def _record(self, task_id: str, event_type: str, payload: dict[str, Any]) -> None:
        await workflow.execute_activity(
            "record_event_activity",
            {"task_id": task_id, "event_type": event_type, "payload": payload},
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=RETRY_DB,
        )

    async def _set_status(self, task_id: str, status: str) -> None:
        await workflow.execute_activity(
            "set_task_status_activity",
            {"task_id": task_id, "status": status},
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=RETRY_DB,
        )

    async def _wait_for_dependency(self, task_id: str, max_wait: float) -> bool:
        """Durable dependency wait: signal-resumed, never busy-looping (§12)."""
        self._dependency_completed = False
        await self._record(
            task_id,
            "DEPENDENCY_WAIT_STARTED",
            {"max_wait_seconds": max_wait},
        )
        await self._set_status(task_id, "blocked")
        try:
            await workflow.wait_condition(
                lambda: self._dependency_completed, timeout=timedelta(seconds=max_wait)
            )
        except TimeoutError:
            return False
        await self._record(task_id, "DEPENDENCY_RESUMED", {})
        await self._set_status(task_id, "running")
        return True

    @workflow.run
    async def run(self, input: TaskExecutionInput) -> dict:
        task = await workflow.execute_activity(
            "load_task_activity",
            input.task_id,
            start_to_close_timeout=_ACTIVITY_TIMEOUT,
            retry_policy=RETRY_DB,
        )
        retry_policy = task.get("retry_policy") or {}
        recovery_policy = task.get("recovery_policy") or {}
        max_attempts = max(1, min(int(retry_policy.get("max_attempts", 3)), 10))
        dep_wait = float(
            retry_policy.get("dependency_wait_seconds")
            or recovery_policy.get("dependency_wait_seconds", 900.0)
        )

        await self._set_status(input.task_id, "running")

        summary: dict[str, Any] = {
            "task_id": input.task_id,
            "attempts": 0,
            "outcome": "failed",
            "recovery_history": [],
        }
        recovery_params: dict[str, Any] = {}
        prev_agent_id: str | None = None
        prev_session_id: str = ""
        for attempt_number in range(1, max_attempts + 1):
            summary["attempts"] = attempt_number
            attempt = await workflow.execute_activity(
                "start_attempt_activity",
                {"task_id": input.task_id, "attempt_number": attempt_number},
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=RETRY_DB,
            )
            agent = await workflow.execute_activity(
                "start_agent_activity",
                {
                    "task_id": input.task_id,
                    "attempt_number": attempt_number,
                    "attempt_id": attempt["id"],
                    "replaces_agent_id": prev_agent_id,
                },
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=RETRY_DB,
            )
            summary["last_agent_id"] = agent["agent_id"]
            agent_id: str = agent["agent_id"]
            await workflow.execute_activity(
                "set_agent_state_activity",
                {"agent_id": agent_id, "state": "running"},
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=RETRY_DB,
            )

            await self._checkpoint(agent_id)
            result = await workflow.execute_activity(
                "agent_execute_activity",
                {
                    "task_id": input.task_id,
                    "attempt_id": attempt["id"],
                    "attempt_number": attempt_number,
                    "max_attempts": max_attempts,
                    "agent_id": agent_id,
                    "session_id": agent.get("session_id", ""),
                    "project_id": task["project_id"],
                    "payload": task.get("payload", {}),
                    "recovery_params": recovery_params,
                },
                start_to_close_timeout=timedelta(
                    seconds=max(60, float(task.get("payload", {}).get("timeout_seconds", 300)))
                ),
                retry_policy=RETRY_NONE,
            )

            await self._checkpoint(agent_id)
            await workflow.execute_activity(
                "set_agent_state_activity",
                {"agent_id": agent_id, "state": "verifying"},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RETRY_DB,
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
                await workflow.execute_activity(
                    "set_agent_state_activity",
                    {"agent_id": agent_id, "state": "completed"},
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RETRY_DB,
                )
                break
            await workflow.execute_activity(
                "set_agent_state_activity",
                {"agent_id": agent_id, "state": "failed"},
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RETRY_DB,
            )
            # --- Recovery coordinator (Wave 2) --------------------------------
            decision = recovery_decision(
                str(result.get("failure_class") or "TASK_FAILURE"),
                attempt_number,
                max_attempts=max_attempts,
                task_id=input.task_id,
                attempt_id=str(attempt["id"]),
                base_backoff=float(recovery_policy.get("base_backoff", 2.0)),
                factor=float(recovery_policy.get("factor", 2.0)),
                max_backoff=float(recovery_policy.get("max_backoff", 60.0)),
                jitter_ratio=float(recovery_policy.get("jitter_ratio", 0.25)),
            )
            action = str(decision["action"])
            summary["recovery_history"].append(
                {
                    "attempt": attempt_number,
                    "attempt_id": str(attempt["id"]),
                    "recovery_id": decision["recovery_id"],
                    "failure_class": decision["failure_class"],
                    "action": action,
                }
            )
            await self._record(
                input.task_id,
                "RECOVERY_SELECTED",
                {
                    "recovery_id": decision["recovery_id"],
                    "attempt_id": str(attempt["id"]),
                    "agent_id": agent_id,
                    "attempt_number": attempt_number,
                    "failure_class": decision["failure_class"],
                    "action": action,
                    "reason": decision["action_reason"],
                    "parameters": decision["parameters"],
                    "retryable": decision["retryable"],
                },
            )
            failure_detail = str(result.get("failure_detail") or "")
            evidence_ids = list(result.get("evidence_artifact_ids", []))

            if action == "stop":
                # SECURITY_BLOCK / HITL_TIMEOUT / BUDGET_EXCEEDED: fail-closed
                # terminal failure with evidence (prompt §6/§7 FAIL_TERMINALLY).
                await workflow.execute_activity(
                    "terminal_failure_activity",
                    {
                        "idempotency_key": f"terminal:{decision['recovery_id']}",
                        "task_id": input.task_id,
                        "recovery_id": decision["recovery_id"],
                        "action": action,
                        "failure_class": decision["failure_class"],
                        "failure_detail": failure_detail,
                        "evidence_artifact_ids": evidence_ids,
                        "recommended_action": (
                            "Resolve the security/cost policy violation, then retry the task"
                        ),
                    },
                    start_to_close_timeout=_ACTIVITY_TIMEOUT,
                    retry_policy=RETRY_DB,
                )
                break

            if action == "escalate_or_replan":
                # Retry ladder exhausted (REC-003): durable replan follow-up,
                # then a terminal failure referencing it. No loop possible.
                await workflow.execute_activity(
                    "replan_task_activity",
                    {
                        "idempotency_key": f"replan:{decision['recovery_id']}",
                        "task_id": input.task_id,
                        "failure_class": decision["failure_class"],
                        "failure_detail": failure_detail,
                        "evidence_artifact_ids": evidence_ids,
                    },
                    start_to_close_timeout=_ACTIVITY_TIMEOUT,
                    retry_policy=RETRY_DB,
                )
                await workflow.execute_activity(
                    "terminal_failure_activity",
                    {
                        "idempotency_key": f"terminal:{decision['recovery_id']}",
                        "task_id": input.task_id,
                        "recovery_id": decision["recovery_id"],
                        "action": action,
                        "failure_class": decision["failure_class"],
                        "failure_detail": failure_detail,
                        "evidence_artifact_ids": evidence_ids,
                        "recommended_action": "Review and start the created replan task",
                    },
                    start_to_close_timeout=_ACTIVITY_TIMEOUT,
                    retry_policy=RETRY_DB,
                )
                break
            # wave2-continue
            budget = await workflow.execute_activity(
                "recovery_budget_activity",
                {"task_id": input.task_id},
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=RETRY_DB,
            )
            budget_blocked = bool(decision["budget_sensitive"]) and not budget["within_budget"]

            async def _hitl_gate(dec: dict[str, Any], detail: str, ev: list[str]) -> bool:
                """Durable HITL gate for an expensive recovery (fail-closed)."""
                gate = await workflow.execute_activity(
                    "hitl_recovery_gate_activity",
                    {
                        "project_id": task["project_id"],
                        "task_id": input.task_id,
                        "decision": dec,
                        "failure_detail": detail,
                        "evidence_artifact_ids": ev,
                        "timeout_seconds": recovery_policy.get("hitl_timeout_seconds", 300.0),
                        "poll_seconds": recovery_policy.get("hitl_poll_seconds", 1.0),
                    },
                    start_to_close_timeout=timedelta(
                        seconds=float(recovery_policy.get("hitl_timeout_seconds", 300.0)) + 30
                    ),
                    retry_policy=RETRY_NONE,
                )
                return bool(gate["approved"])

            if budget_blocked and not await _hitl_gate(decision, failure_detail, evidence_ids):
                # Recovery never bypasses cost control (prompt §9): a rejected
                # or timed-out gate fails the task terminally with evidence.
                break

            if action in ("spawn_debugger", "create_integration_task"):
                # Durable child task with structured failure evidence (§7), then
                # wait for its completion via the dependency signal (§12).
                await workflow.execute_activity(
                    "spawn_child_task_activity",
                    {
                        "idempotency_key": f"child:{decision['recovery_id']}",
                        "task_id": input.task_id,
                        "child_kind": str(
                            decision["parameters"].get(
                                "child_kind",
                                "debug" if action == "spawn_debugger" else "integration_task",
                            )
                        ),
                        "failure_class": decision["failure_class"],
                        "failure_detail": failure_detail,
                        "attempt_id": str(attempt["id"]),
                        "evidence_artifact_ids": evidence_ids,
                    },
                    start_to_close_timeout=_ACTIVITY_TIMEOUT,
                    retry_policy=RETRY_DB,
                )
                if not await self._wait_for_dependency(input.task_id, dep_wait):
                    break

            elif action == "wait_for_dependency":
                if not await self._wait_for_dependency(input.task_id, dep_wait):
                    break

            elif action == "replace_agent":
                # Old agent drained (session ended), replacement recorded (§11):
                # the next start_agent_activity carries replaces_agent_id.
                await workflow.execute_activity(
                    "end_agent_session_activity",
                    {"agent_id": prev_agent_id, "session_id": prev_session_id},
                    start_to_close_timeout=_ACTIVITY_TIMEOUT,
                    retry_policy=RETRY_DB,
                )
                await self._record(
                    input.task_id,
                    "AGENT_REPLACED",
                    {"recovery_id": decision["recovery_id"], "agent_id": prev_agent_id},
                )
            elif action in ("retry_alternate_model", "escalate_model"):
                await self._record(
                    input.task_id,
                    "MODEL_SWITCHED",
                    {
                        "recovery_id": decision["recovery_id"],
                        "route": str(decision["parameters"].get("model_route", "")),
                        "escalated": action == "escalate_model",
                    },
                )
            elif action == "rebuild_context":
                await self._record(
                    input.task_id,
                    "CONTEXT_COMPACTED",
                    {
                        "recovery_id": decision["recovery_id"],
                        "scale": decision["parameters"].get("context_budget_scale", 0.5),
                    },
                )

            if decision["retryable"]:
                recovery_params.update(decision["parameters"])  # applied on next attempt
                if action in (
                    "retry_if_safe",
                    "retry_then_replan",
                    "recreate_runtime",
                    "throttle_then_retry",
                    "rebuild_context",
                    "retry_alternate_model",
                    "escalate_model",
                    "replace_agent",
                ):
                    await self._record(
                        input.task_id,
                        "RETRY_STARTED",
                        {
                            "recovery_id": decision["recovery_id"],
                            "attempt_number": attempt_number,
                            "backoff_seconds": decision["backoff_seconds"],
                        },
                    )
                    await workflow.sleep(float(decision["backoff_seconds"]))  # durable timer

        final_status = "completed" if summary["outcome"] == "success" else "failed"
        await self._set_status(input.task_id, final_status)
        await self._record(
            input.task_id,
            "TASK_COMPLETED" if final_status == "completed" else "TASK_FAILED",
            {key: value for key, value in summary.items() if key != "task_id"},
        )
        if final_status == "completed":
            # Wake dependents durably (prompt §12: event/dependency resolution).
            deps = await workflow.execute_activity(
                "task_dependents_activity",
                {"task_id": input.task_id},
                start_to_close_timeout=_ACTIVITY_TIMEOUT,
                retry_policy=RETRY_DB,
            )
            for dep_id in deps.get("dependent_task_ids", []):
                handle = workflow.get_external_workflow_handle(f"task-exec-{dep_id}")
                with contextlib.suppress(Exception):  # dependent may not be running
                    await handle.signal("dependency_completed")
        return summary

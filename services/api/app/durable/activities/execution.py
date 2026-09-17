"""Agent work-unit activity: context → model decision → policy-gated execution.

The context broker assembles tiered context; the role-routed model (rehearsal by
default) decides the commands; the tool gateway enforces policy and returns a
compressed observation (FR-023). Raw output is preserved as evidence artifacts.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from sqlalchemy import select
from temporalio import activity

from app.agents_runtime.context_broker import assemble
from app.agents_runtime.gateway import PolicyViolation, ToolInvocation
from app.agents_runtime.gateway import invoke as gateway_invoke
from app.agents_runtime.models_registry import ModelRegistry, extract_commands
from app.agents_runtime.providers import ModelRequest
from app.core.errors import DomainError
from app.db.models import Artifact, Event, Memory, Project, TaskAttempt
from app.durable.activities._context import current_settings, load_task_row, refs
from app.durable.activities.agents import heartbeat_session
from app.durable.activities.hitl import hitl_gate
from app.runtime.runtimes import resolve_spec
from app.schemas.orchestration.leases import LeaseOut
from app.services.orchestration.recovery import classify_failure, recovery_plan


def _run_markers(payload: dict[str, Any]) -> str:
    """Render payload commands as RUN markers for the model prompt."""
    command = payload.get("command", [])
    if command and isinstance(command[0], list):
        return "\n".join("- RUN: " + " ".join(str(a) for a in argv) for argv in command)
    return "- RUN: " + " ".join(str(a) for a in command) if command else ""


def _decide_commands(payload: dict[str, Any], model_text: str) -> list[list[str]]:
    """Determine the argv lists to execute.

    Payload commands (argv lists) take precedence — deterministic and safe. When
    absent, the model decision text is parsed into shell-string commands.
    """

    def _as_argv_list(cmd: Any) -> list[list[str]]:
        if cmd and isinstance(cmd[0], list):
            return [[str(a) for a in argv] for argv in cmd]
        return [[str(a) for a in cmd]]

    payload_commands = _as_argv_list(payload.get("command", []))
    if payload_commands:
        return payload_commands
    return [text.split() for text in extract_commands(model_text)]


async def _retrieve_code(factory, project_id: str | None, query: str, settings) -> str:  # type: ignore[no-untyped-def]
    """Hybrid code retrieval feeding the T3 context tier. Never breaks execution."""
    if not (project_id and query.strip()) or not getattr(
        settings, "context_retrieval_enabled", True
    ):
        return ""

    def _run() -> str:
        from app.codeintel.retrieval import retrieve  # noqa: PLC0415 — keeps codeintel optional

        with factory() as session:
            hits = retrieve(
                session,
                project_id,
                query,
                k=int(getattr(settings, "retrieval_k", 6) or 6),
            )
            return "\n".join(
                f"CODE {hit.path}:{hit.start_line}-{hit.end_line} [{hit.kind}] "
                f"{hit.name} — {hit.signature}"
                for hit in hits
            )

    try:
        return await asyncio.to_thread(_run)
    except Exception as exc:  # noqa: BLE001 — retrieval must never break an agent run
        activity.logger.warning("code_retrieval_failed error=%s", exc)
        return ""


def _within_budget(factory, task_id: uuid.UUID, budget: int) -> bool:  # type: ignore[no-untyped-def]
    from app.services.intelligence import costs as cost_service  # noqa: PLC0415

    with factory() as session:
        return cost_service.tokens_for_task(session, task_id) < budget


async def _record_budget_exceeded(factory, project_id: str | None, task_id: uuid.UUID) -> None:  # type: ignore[no-untyped-def]
    def _write() -> None:
        with factory() as session:
            session.add(
                Event(
                    event_type="MODEL_BUDGET_EXCEEDED",
                    source="temporal",
                    project_id=uuid.UUID(project_id) if project_id else None,
                    task_id=task_id,
                    payload={},
                )
            )
            session.commit()

    await asyncio.to_thread(_write)


async def _record_invocation(factory, *, project_id, task_id, agent_id, role, response) -> None:  # type: ignore[no-untyped-def]
    def _write() -> None:
        from app.services.intelligence import costs as cost_service  # noqa: PLC0415

        with factory() as session:
            cost_service.record_invocation(
                session,
                project_id=uuid.UUID(project_id) if project_id else None,
                task_id=task_id,
                agent_id=uuid.UUID(agent_id) if agent_id else None,
                role=role,
                provider=response.provider,
                model=response.model,
                prompt_tokens=response.prompt_tokens_est,
                completion_tokens=response.output_tokens_est,
            )

    try:
        await asyncio.to_thread(_write)
    except Exception as exc:  # noqa: BLE001 — accounting must never break an agent run
        activity.logger.warning("cost_record_failed error=%s", exc)


@activity.defn
async def agent_execute_activity(input: dict[str, Any]) -> dict[str, Any]:
    factory, store = refs()
    settings = current_settings()
    task_id = uuid.UUID(input["task_id"])
    agent_id: str = input["agent_id"]
    session_id: str = input.get("session_id", "")
    project_id = input.get("project_id")
    recovery_params: dict[str, Any] = input.get("recovery_params") or {}

    def _load_context() -> dict[str, Any]:
        with factory() as session:
            task = load_task_row(session, task_id)
            project = session.get(Project, task.project_id) if task.project_id else None
            memories = session.scalars(
                select(Memory).where(Memory.project_id == task.project_id).limit(20)
            ).all()
            prior = session.scalars(select(TaskAttempt).where(TaskAttempt.task_id == task_id)).all()
            return {
                "title": task.title,
                "request": task.request,
                "expected_output": task.expected_output,
                "allowed_tools": list(task.allowed_tools or []),
                "payload": task.payload or {},
                "project_name": project.name if project else "",
                "project_root": project.root_path if project else ".",
                "memories": [f"{m.kind}: {m.content}" for m in memories],
                "prior_attempts": len(prior),
            }

    context_data = await asyncio.to_thread(_load_context)
    payload = context_data["payload"]

    code_text = await _retrieve_code(factory, project_id, str(context_data["request"]), settings)

    bundle = assemble(
        safety_text=(
            "You are an agent inside the AI Harness. Policy: only execute commands the "
            "task allowlist permits; the gateway denies dangerous commands outside the "
            "model's control. Never claim completion without a successful observation."
        ),
        task_text=(
            f"Task: {context_data['title']}\nRequest: {context_data['request']}\n"
            f"Expected output: {context_data['expected_output'] or '(unspecified)'}\n"
            "Commands from the task payload are listed below with '- RUN:' markers."
        ),
        state_text=f"Project: {context_data['project_name']}",
        code_text=code_text,
        history_text=f"Prior attempts on this task: {context_data['prior_attempts']}",
        evidence_text="\n".join(context_data["memories"]),
        # Recovery (Wave 2): COMPACT_CONTEXT/rebuild_context scales the context
        # budget so the next model invocation receives a rebuilt, smaller bundle.
        budget_tokens=int(
            int(getattr(settings, "context_budget_tokens", 8000) or 8000)
            * float(recovery_params.get("context_budget_scale", 1.0))
        ),
    )

    model_request = ModelRequest(
        role=str(payload.get("agent_role", "worker")),
        system="You are a disciplined software-engineering agent. Output the scripted decision.",
        prompt=bundle.render() + "\n\n" + _run_markers(payload),
        max_output_tokens=1024,
    )
    budget = int(getattr(settings, "model_budget_tokens_per_task", 0) or 0)
    if budget and not await asyncio.to_thread(_within_budget, factory, task_id, budget):
        await _record_budget_exceeded(factory, project_id, task_id)
        return {
            "outcome": "failed",
            "failure_class": "BUDGET_EXCEEDED",
            "failure_detail": (
                f"Model budget exhausted for this task ({budget} tokens/task); "
                "spec §32 bounded-cost policy."
            ),
            "evidence_artifact_ids": [],
        }

    registry = ModelRegistry.load(Path(getattr(settings, "models_config_path", "") or "") or None)
    # Recovery (Wave 2): SWITCH_MODEL/ESCALATE_MODEL route the next attempt to
    # the configured alternate model (the route's policy-defined fallback_role)
    # — never an unapproved provider (prompt §10).
    if str(recovery_params.get("model_route", "")) == "fallback":
        route = registry.route_for(model_request.role)
        fallback_role = str(getattr(route, "fallback_role", "") or "")
        if fallback_role and fallback_role != model_request.role:
            model_request = replace(model_request, role=fallback_role)
    model_response = await registry.complete(model_request)
    await _record_invocation(
        factory,
        project_id=project_id,
        task_id=task_id,
        agent_id=agent_id,
        role=model_request.role,
        response=model_response,
    )

    commands = _decide_commands(payload, model_response.text)

    allowed = frozenset(context_data["allowed_tools"]) or frozenset({"shell"})
    runtime = resolve_spec(settings, payload)
    timeout_cap = float(getattr(settings, "exec_timeout_cap_seconds", 900.0) or 900.0)
    observations: list[dict[str, Any]] = []
    evidence_ids: list[str] = []
    overall, failure_class, failure_detail = "success", None, None

    async def _store_evidence(name: str, data: bytes) -> str | None:
        def _persist() -> str:
            blob = store.put(data)
            with factory() as session:
                artifact = Artifact(
                    project_id=uuid.UUID(project_id) if project_id else None,
                    name=f"agent-{agent_id[:8]}-{name}",
                    kind="raw_output",
                    mime="text/plain",
                    size=blob.size,
                    sha256=blob.sha256,
                    storage_path=blob.storage_path,
                )
                session.add(artifact)
                session.commit()
                return str(artifact.id)

        return await asyncio.to_thread(_persist)

    max_concurrent = int(getattr(settings, "exec_max_concurrent_per_project", 2) or 2)

    def _acquire_slot() -> LeaseOut | None:
        from app.services.execution import executions as execution_service  # noqa: PLC0415

        with factory() as session:
            return execution_service.acquire_slot(
                session,
                uuid.UUID(project_id),
                max_concurrent=max_concurrent,
                holder_session=session_id or None,
            )

    def _release_slot(slot: LeaseOut) -> None:
        from app.services.execution import executions as execution_service  # noqa: PLC0415

        with factory() as session:
            execution_service.release_slot(session, slot.id)

    if project_id:
        slot = await asyncio.to_thread(_acquire_slot)
        if slot is None:
            return {
                "outcome": "failed",
                "failure_class": "QUOTA_EXCEEDED",
                "failure_detail": (
                    f"Execution quota exhausted: {max_concurrent} concurrent runs per project "
                    "(spec §19). Retry when a running task finishes."
                ),
                "evidence_artifact_ids": [],
            }
    else:
        slot = None  # project-less executions are not quota-tracked

    try:
        for index, command in enumerate(commands):
            argv = command.split() if isinstance(command, str) else [str(c) for c in command]
            requested_timeout = float(payload.get("timeout_seconds", 120))
            invocation = ToolInvocation(
                tool="shell",
                command=argv,
                cwd=str(payload.get("cwd") or context_data["project_root"]),
                timeout_seconds=min(requested_timeout, timeout_cap),
                allowed_tools=allowed,
                runtime=runtime,
            )
            try:
                observation = await gateway_invoke(
                    invocation, invocation.command, store_evidence=_store_evidence
                )
            except PolicyViolation as exc:
                if not exc.needs_approval:
                    raise DomainError(exc.reason, 422) from None
                # HITL gate (SEC-004): create a durable request and fail closed on timeout.
                gate = await hitl_gate(
                    project_id=project_id,
                    task_id=task_id,
                    command=argv,
                    timeout_seconds=float(
                        getattr(settings, "hitl_timeout_seconds", 300.0) or 300.0
                    ),
                    poll_seconds=float(getattr(settings, "hitl_poll_seconds", 1.0) or 1.0),
                )
                if not gate["approved"]:
                    return {
                        "outcome": "failed",
                        "failure_class": "SECURITY_BLOCK",
                        "failure_detail": f"HITL {gate['status']}: {exc.reason}",
                        "evidence_artifact_ids": evidence_ids,
                        "observation": {
                            "tool": "shell",
                            "status": "blocked",
                            "hitl": gate["status"],
                        },
                    }
                observation = await gateway_invoke(
                    replace(invocation, pre_approved=True),
                    invocation.command,
                    store_evidence=_store_evidence,
                )
            await heartbeat_session(session_id)
            if activity.in_activity():
                activity.heartbeat()
            observations.append(observation.to_json())
            evidence_ids.extend(observation.artifact_ids)
            if observation.status != "success":
                overall = "timeout" if observation.status == "timeout" else "failed"
                failure_detail = f"command {index} failed: {observation.summary[:200]}"
                failure_class = classify_failure(
                    failure_detail, timed_out=observation.status == "timeout"
                )
                break
    finally:
        if slot is not None:
            await asyncio.to_thread(_release_slot, slot)

    recovery = (
        recovery_plan(
            failure_class,
            int(input.get("attempt_number", 1) or 1),
            max_attempts=int(input.get("max_attempts", 3) or 3),
        )
        if failure_class
        else None
    )
    return {
        "outcome": overall,
        "failure_class": failure_class,
        "failure_detail": failure_detail,
        "recovery": recovery,
        "attempt_number": input.get("attempt_number", 1),
        "evidence_artifact_ids": evidence_ids,
        "observation": observations[0] if observations else None,
        "model": {"provider": model_response.provider, "model": model_response.model},
        "context_tokens": bundle.total_tokens,
    }

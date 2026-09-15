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
from app.db.models import Artifact, Memory, Project, TaskAttempt
from app.durable.activities._context import current_settings, load_task_row, refs
from app.durable.activities.agents import heartbeat_session
from app.durable.activities.hitl import hitl_gate


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


@activity.defn
async def agent_execute_activity(input: dict[str, Any]) -> dict[str, Any]:
    factory, store = refs()
    settings = current_settings()
    task_id = uuid.UUID(input["task_id"])
    agent_id: str = input["agent_id"]
    session_id: str = input.get("session_id", "")
    project_id = input.get("project_id")

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
        history_text=f"Prior attempts on this task: {context_data['prior_attempts']}",
        evidence_text="\n".join(context_data["memories"]),
        budget_tokens=int(getattr(settings, "context_budget_tokens", 8000) or 8000),
    )

    model_request = ModelRequest(
        role=str(payload.get("agent_role", "worker")),
        system="You are a disciplined software-engineering agent. Output the scripted decision.",
        prompt=bundle.render() + "\n\n" + _run_markers(payload),
        max_output_tokens=1024,
    )
    registry = ModelRegistry.load(Path(getattr(settings, "models_config_path", "") or "") or None)
    model_response = await registry.complete(model_request)

    commands = _decide_commands(payload, model_response.text)

    allowed = frozenset(context_data["allowed_tools"]) or frozenset({"shell"})
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

    for index, command in enumerate(commands):
        argv = command.split() if isinstance(command, str) else [str(c) for c in command]
        invocation = ToolInvocation(
            tool="shell",
            command=argv,
            cwd=str(payload.get("cwd") or context_data["project_root"]),
            timeout_seconds=float(payload.get("timeout_seconds", 120)),
            allowed_tools=allowed,
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
                timeout_seconds=float(getattr(settings, "hitl_timeout_seconds", 300.0) or 300.0),
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
            failure_class = "TIMEOUT" if observation.status == "timeout" else "TASK_FAILURE"
            failure_detail = f"command {index} failed: {observation.summary[:200]}"
            break

    return {
        "outcome": overall,
        "failure_class": failure_class,
        "failure_detail": failure_detail,
        "evidence_artifact_ids": evidence_ids,
        "observation": observations[0] if observations else None,
        "model": {"provider": model_response.provider, "model": model_response.model},
        "context_tokens": bundle.total_tokens,
    }

"""Workflow activities: every DB write and process execution happens here.

Dependencies (session factory, artifact store) are injected via ``init_refs``
by the worker entrypoint and by tests.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from temporalio import activity

from app.agents_runtime.context_broker import assemble
from app.agents_runtime.gateway import PolicyViolation, ToolInvocation
from app.agents_runtime.gateway import invoke as gateway_invoke
from app.agents_runtime.lifecycle import assert_transition
from app.agents_runtime.models_registry import ModelRegistry, extract_commands
from app.agents_runtime.providers import ModelRequest
from app.artifacts.store import ArtifactStore
from app.core.errors import DomainError
from app.db.models import (
    Agent,
    AgentSession,
    Artifact,
    Event,
    Memory,
    Project,
    Task,
    TaskAttempt,
)
from app.runtime.runner import run_process

_EVIDENCE_MIN_BYTES = 512


def init_refs(
    session_factory: sessionmaker[Session],
    artifact_store: ArtifactStore,
    settings: Any = None,
) -> None:
    _Refs.session_factory = session_factory
    _Refs.artifact_store = artifact_store
    _Refs.settings = settings


class _Refs:
    session_factory: sessionmaker[Session] | None = None
    artifact_store: ArtifactStore | None = None
    settings: Any = None


def _refs() -> tuple[sessionmaker[Session], ArtifactStore]:
    if _Refs.session_factory is None or _Refs.artifact_store is None:
        raise RuntimeError("Activity refs not initialised (worker startup or test setup)")
    return _Refs.session_factory, _Refs.artifact_store


def _db_task(session: Session, task_id: uuid.UUID) -> Task:
    task = session.get(Task, task_id)
    if task is None:
        raise RuntimeError(f"Task not found: {task_id}")
    return task


async def heartbeat_session(session_id: str) -> None:
    """Refresh an agent session heartbeat (spec §12: mandatory while running)."""
    if not session_id:
        return
    factory, _store = _refs()

    def _beat() -> None:
        with factory() as session:
            row = session.get(AgentSession, uuid.UUID(session_id))
            if row is not None and row.status == "running":
                row.heartbeat_at = datetime.now(UTC)
                session.commit()

    await asyncio.to_thread(_beat)


async def hitl_gate(
    *,
    project_id: str | None,
    task_id: uuid.UUID,
    command: list[str],
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    """Create a durable HITL request and wait (fail-closed) for the decision."""
    from app.services import hitl as hitl_service  # noqa: PLC0415

    factory, _store = _refs()

    def _create() -> dict[str, Any]:
        with factory() as session:
            request = hitl_service.create_request(
                session,
                project_id=uuid.UUID(project_id) if project_id else None,
                task_id=task_id,
                kind="approve_command",
                question="Approve execution of a policy-gated command?",
                choices=["approve", "reject"],
                risk="high",
            )
            return {"request_id": str(request.id), "command": " ".join(command)}

    created = await asyncio.to_thread(_create)
    request_id = uuid.UUID(created["request_id"])

    with factory() as session:
        session.add(
            Event(
                event_type="HITL_REQUESTED",
                source="temporal",
                project_id=uuid.UUID(project_id) if project_id else None,
                task_id=task_id,
                payload={"request_id": created["request_id"], "command": created["command"]},
            )
        )
        session.commit()

    def _wait() -> tuple[Any, bool]:
        with factory() as session:
            return hitl_service.wait_decision(session, request_id, timeout_seconds, poll_seconds)

    request, approved = await asyncio.to_thread(_wait)

    with factory() as session:
        session.add(
            Event(
                event_type="HITL_RESPONDED",
                source="temporal",
                project_id=uuid.UUID(project_id) if project_id else None,
                task_id=task_id,
                payload={
                    "request_id": str(request_id),
                    "status": request.status,
                    "approved": approved,
                },
            )
        )
        session.commit()
    return {"request_id": str(request_id), "status": request.status, "approved": approved}


@activity.defn
async def load_task_activity(task_id: str) -> dict[str, Any]:
    """Load the durable task for orchestration (TASK-002: state lives in the DB)."""
    factory, _store = _refs()

    def _load() -> dict[str, Any]:
        with factory() as session:
            task = _db_task(session, uuid.UUID(task_id))
            return {
                "id": str(task.id),
                "project_id": str(task.project_id) if task.project_id else None,
                "title": task.title,
                "status": task.status,
                "payload": task.payload or {},
                "retry_policy": task.retry_policy or {},
            }

    return await asyncio.to_thread(_load)


@activity.defn
async def start_attempt_activity(input: dict[str, Any]) -> dict[str, Any]:
    """Record the start of attempt N (spec: Attempt 1 -> Agent-12 -> ...)."""
    factory, _store = _refs()

    def _start() -> dict[str, Any]:
        with factory() as session:
            task_id = uuid.UUID(input["task_id"])
            number = session.scalar(select(func.count()).where(TaskAttempt.task_id == task_id)) or 0
            attempt = TaskAttempt(task_id=task_id, attempt_number=int(number) + 1)
            session.add(attempt)
            session.commit()
            return {"id": str(attempt.id), "attempt_number": attempt.attempt_number}

    return await asyncio.to_thread(_start)


@activity.defn
async def execute_work_activity(input: dict[str, Any]) -> dict[str, Any]:
    """Run the task's work unit.

    Phase 2 work unit: ``payload.command`` executed at the project root, with raw
    stdout/stderr preserved as evidence artifacts (TASK-003). Phase 3 replaces
    this with the agent runtime; the durable wrapper is unchanged.
    """
    payload: dict[str, Any] = input.get("payload") or {}
    command = payload.get("command")
    if not command or not isinstance(command, list):
        return {
            "outcome": "failed",
            "failure_class": "TASK_FAILURE",
            "failure_detail": (
                "No executable work on this task: payload.command is missing. The agent "
                "runtime arrives in Phase 3; supply a command payload for durable execution."
            ),
            "evidence_artifact_ids": [],
        }

    factory, store = _refs()
    project_id = input.get("project_id")

    def _project_root() -> str:
        if not project_id:
            return "."
        with factory() as session:
            project = session.get(Project, uuid.UUID(project_id))
            return project.root_path if project else "."

    cwd = str(payload.get("cwd") or (await asyncio.to_thread(_project_root)) or ".")
    result = await run_process(
        [str(arg) for arg in command],
        cwd,
        timeout_seconds=float(payload.get("timeout_seconds", 300)),
    )

    evidence: list[str] = []

    def _store_evidence() -> None:
        for name, mime, text in (
            ("stdout.log", "text/plain", result.stdout),
            ("stderr.log", "text/plain", result.stderr),
        ):
            if len(text.encode("utf-8")) < _EVIDENCE_MIN_BYTES:
                continue
            blob = store.put(text.encode("utf-8"))
            with factory() as session:
                artifact = Artifact(
                    project_id=uuid.UUID(project_id) if project_id else None,
                    name=f"attempt-{input['attempt_id'][:8]}-{name}",
                    kind="raw_output",
                    mime=mime,
                    size=blob.size,
                    sha256=blob.sha256,
                    storage_path=blob.storage_path,
                )
                session.add(artifact)
                session.commit()
                evidence.append(str(artifact.id))

    await asyncio.to_thread(_store_evidence)

    if result.timed_out:
        outcome, failure_class, detail = "timeout", "TIMEOUT", "Work exceeded its time budget"
    elif result.exit_code == 0:
        outcome, failure_class, detail = "success", None, None
    else:
        outcome = "failed"
        failure_class = "TOOL_FAILURE" if payload.get("kind") == "tool" else "TASK_FAILURE"
        detail = f"exit_code={result.exit_code}; see evidence artifacts"
    return {
        "outcome": outcome,
        "failure_class": failure_class,
        "failure_detail": detail,
        "evidence_artifact_ids": evidence,
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms,
    }


@activity.defn
async def finish_attempt_activity(input: dict[str, Any]) -> None:
    factory, _store = _refs()

    def _finish() -> None:
        with factory() as session:
            attempt = session.get(TaskAttempt, uuid.UUID(input["attempt_id"]))
            if attempt is None:
                raise RuntimeError(f"Attempt not found: {input['attempt_id']}")
            attempt.outcome = input["outcome"]
            attempt.failure_class = input.get("failure_class")
            attempt.failure_detail = input.get("failure_detail")
            attempt.evidence_artifact_ids = input.get("evidence_artifact_ids", [])
            attempt.finished_at = datetime.now(UTC)
            session.commit()

    await asyncio.to_thread(_finish)


@activity.defn
async def set_task_status_activity(input: dict[str, Any]) -> None:
    factory, _store = _refs()

    def _set() -> None:
        with factory() as session:
            task = _db_task(session, uuid.UUID(input["task_id"]))
            task.status = input["status"]
            session.commit()

    await asyncio.to_thread(_set)


@activity.defn
async def record_event_activity(input: dict[str, Any]) -> None:
    factory, _store = _refs()

    def _record() -> None:
        with factory() as session:
            task_id = uuid.UUID(input["task_id"])
            task = session.get(Task, task_id)
            session.add(
                Event(
                    event_type=input["event_type"],
                    source="temporal",
                    project_id=task.project_id if task else None,
                    task_id=task_id,
                    payload=input.get("payload", {}),
                )
            )
            session.commit()

    await asyncio.to_thread(_record)


@activity.defn
async def start_agent_activity(input: dict[str, Any]) -> dict[str, Any]:
    """Create the agent for this attempt (spec §11: agents are disposable).

    Replacement semantics (FR-008): attempt N>1 records which failed agent it
    replaces; task identity is preserved across the replacement.
    """
    factory, _store = _refs()

    def _start() -> dict[str, Any]:
        with factory() as session:
            task_id = uuid.UUID(input["task_id"])
            attempt_id = uuid.UUID(input["attempt_id"])
            task = _db_task(session, task_id)
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
    factory, _store = _refs()

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
    """Agent-driven work unit (Phase 3).

    Context broker assembles tiered context; the role-routed model (rehearsal by
    default) decides the commands; the tool gateway enforces policy and returns a
    compressed observation (FR-023). Raw output is preserved as evidence artifacts.
    """
    factory, store = _refs()
    settings = _Refs.settings
    task_id = uuid.UUID(input["task_id"])
    agent_id: str = input["agent_id"]
    session_id: str = input.get("session_id", "")
    project_id = input.get("project_id")

    def _load_context() -> dict[str, Any]:
        with factory() as session:
            task = _db_task(session, task_id)
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
            settings_obj = _Refs.settings
            gate = await hitl_gate(
                project_id=project_id,
                task_id=task_id,
                command=argv,
                timeout_seconds=float(
                    getattr(settings_obj, "hitl_timeout_seconds", 300.0) or 300.0
                ),
                poll_seconds=float(getattr(settings_obj, "hitl_poll_seconds", 1.0) or 1.0),
            )
            if not gate["approved"]:
                return {
                    "outcome": "failed",
                    "failure_class": "SECURITY_BLOCK",
                    "failure_detail": f"HITL {gate['status']}: {exc.reason}",
                    "evidence_artifact_ids": evidence_ids,
                    "observation": {"tool": "shell", "status": "blocked", "hitl": gate["status"]},
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

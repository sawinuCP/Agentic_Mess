"""End-to-end acceptance journey (Wave 11 §1/§35): one requirement through the
whole platform and back, asserting every surface agrees.

Requirement → task → Temporal workflow (real execution) → evidence →
criterion VERIFIED, with cross-surface consistency: tasks API, agents API,
events API, traceability API and costs API must all reflect the same durable
truth. Rehearsal provider only — no model calls.
"""

from __future__ import annotations

import asyncio
import sys

import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.durable.activities import (
    agent_execute_activity,
    dependency_status_activity,
    end_agent_session_activity,
    execute_work_activity,
    finish_attempt_activity,
    hitl_recovery_gate_activity,
    load_task_activity,
    record_event_activity,
    recovery_budget_activity,
    replan_task_activity,
    rollback_attempt_activity,
    set_agent_state_activity,
    set_task_status_activity,
    snapshot_attempt_activity,
    spawn_child_task_activity,
    start_agent_activity,
    start_attempt_activity,
    task_dependents_activity,
    terminal_failure_activity,
)
from app.durable.workflows import TaskExecutionInput, TaskExecutionWorkflow

pytestmark = pytest.mark.integration

_ACTIVITIES = [
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
    snapshot_attempt_activity,
    rollback_attempt_activity,
    spawn_child_task_activity,
    replan_task_activity,
    terminal_failure_activity,
    end_agent_session_activity,
    task_dependents_activity,
    dependency_status_activity,
    hitl_recovery_gate_activity,
]


def test_requirement_to_verified_journey(project: tuple) -> None:
    from app.durable.activities import init_refs

    app, client, project_id, root = project
    init_refs(app.state.session_factory, app.state.artifacts, app.state.settings)
    (root / "release_notes.txt").write_text("v0\n", encoding="utf-8")

    # 1. Requirement with a mandatory acceptance criterion.
    requirement = client.post(
        f"/api/projects/{project_id}/requirements",
        json={
            "title": "Release notes mention the version",
            "description": "notes file contains the release version",
            "criteria": [{"description": "notes contain v1", "kind": "manual", "mandatory": True}],
        },
    )
    assert requirement.status_code == 201, requirement.text
    requirement_id = requirement.json()["id"]
    criterion_id = requirement.json()["criteria"][0]["id"]

    # 2. Task linked to the requirement with a real command.
    created = client.post(
        f"/api/projects/{project_id}/tasks",
        json={
            "title": "Write v1 into release notes",
            "request": "update the notes file",
            "requirement_id": requirement_id,
            "payload": {
                "command": [sys.executable, "-c", "open('release_notes.txt','w').write('v1\\n')"],
                "timeout_seconds": 60,
            },
        },
    )
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]

    # 3. Durable execution through the real Temporal workflow.
    async def _execute() -> dict:
        async with (
            await WorkflowEnvironment.start_time_skipping() as env,
            Worker(
                env.client,
                task_queue="wave11-journey",
                workflows=[TaskExecutionWorkflow],
                activities=_ACTIVITIES,
            ),
        ):
            return await env.client.execute_workflow(
                TaskExecutionWorkflow.run,
                TaskExecutionInput(task_id=task_id),
                id=f"task-exec-{task_id}",
                task_queue="wave11-journey",
            )

    summary = asyncio.run(_execute())
    assert summary["outcome"] == "success", summary
    assert (root / "release_notes.txt").read_text(encoding="utf-8") == "v1\n"

    # 4. Evidence-backed verification (overseer: no evidence → no VERIFIED).
    uploaded = client.post(
        f"/api/projects/{project_id}/artifacts",
        files={"file": ("notes-evidence.txt", b"release_notes.txt contains v1")},
    )
    assert uploaded.status_code == 201, uploaded.text
    verified = client.post(
        f"/api/requirements/{requirement_id}/criteria/{criterion_id}/verify",
        json={
            "evidence_artifact_id": uploaded.json()["id"],
            "task_id": task_id,
        },
    )
    assert verified.status_code == 200, verified.text

    # 5. Cross-surface consistency: every surface agrees with durable state.
    task = client.get(f"/api/tasks/{task_id}").json()
    assert task["status"] == "completed"
    agents = client.get(f"/api/projects/{project_id}/agents").json()
    assert len(agents) >= 1
    assert all(a["project_id"] == project_id for a in agents)
    event_types = {
        e["event_type"] for e in client.get("/api/events", params={"project_id": project_id}).json()
    }
    assert "TASK_COMPLETED" in event_types
    assert "AGENT_CREATED" in event_types
    traceability = client.get(f"/api/projects/{project_id}/oversight/traceability").json()
    entries = traceability.get("requirements", [])
    mine = [e for e in entries if isinstance(e, dict) and e.get("id") == requirement_id]
    assert mine and mine[0]["status"] == "VERIFIED", mine
    costs = client.get(
        f"/api/projects/{project_id}/intelligence/costs", params={"task_id": task_id}
    ).json()
    assert costs["total_tokens"] > 0
    assert costs["invocations"] >= 1

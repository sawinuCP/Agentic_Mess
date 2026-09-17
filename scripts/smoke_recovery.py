"""Recovery smoke (Wave 2): the Temporal workflow executes recovery decisions.

Usage: with the API running (HARNESS_TEMPORAL_ENABLED=true) and a durable worker:
  python scripts/smoke_recovery.py

Scenario A — transient failure: the command fails on attempt 1 and succeeds on
attempt 2; the workflow must RETRY with durable backoff and complete.

Scenario B — exhausted ladder: the command always fails; the workflow must
create a durable REPLAN follow-up task and mark the task terminally failed with
evidence (REC-003) instead of looping.
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8000"


def _events(client: httpx.Client, project_id: str, event_type: str) -> list[dict]:
    rows = client.get(
        "/api/events", params={"project_id": project_id, "event_type": event_type, "limit": 500}
    ).json()
    return rows


def _wait_task(client: httpx.Client, task_id: str) -> dict:
    deadline = time.time() + 240
    task = client.get(f"/api/tasks/{task_id}").json()
    while time.time() < deadline and task["status"] not in ("completed", "failed", "cancelled"):
        time.sleep(2)
        task = client.get(f"/api/tasks/{task_id}").json()
    return task


def main() -> int:
    project_root = Path(tempfile.mkdtemp(prefix="harness-recovery-"))
    client = httpx.Client(base_url=BASE, timeout=30)
    project_id = client.post(
        "/api/projects/open", json={"root_path": str(project_root)}
    ).json()["id"]
    print(f"[1] project: {project_id}")

    # --- Scenario A: transient failure recovers via RETRY ----------------------
    requirement = client.post(
        f"/api/projects/{project_id}/requirements",
        json={
            "title": "Transient recovery",
            "description": "Fails once, then succeeds.",
            "criteria": [{"description": "command eventually succeeds", "kind": "command"}],
        },
    ).json()
    plan = client.post(
        f"/api/requirements/{requirement['id']}/plans",
        json={
            "summary": "transient recovery",
            "tasks": [
                {
                    "title": "Flaky command",
                    "request": "Run the flaky command",
                    "payload": {
                        "command": [
                            sys.executable,
                            "-c",
                            "import pathlib, sys; p = pathlib.Path('marker.txt'); "
                            "print('recovered: ' + p.read_text()) if p.exists() "
                            "else (p.write_text('done'), sys.exit(1))",
                        ]
                    },
                    "retry_policy": {"max_attempts": 3, "backoff_seconds": 1},
                }
            ],
        },
    ).json()
    task_id = plan["task_ids"][0]
    client.post(f"/api/tasks/{task_id}/execute").raise_for_status()
    task = _wait_task(client, task_id)
    assert task["status"] == "completed", f"scenario A ended {task['status']}: {task}"
    assert len(task["attempts"]) == 2, f"expected exactly 2 attempts: {task['attempts']}"
    assert task["attempts"][0]["outcome"] == "failed"
    assert task["attempts"][0]["failure_class"] == "TASK_FAILURE"
    assert task["attempts"][1]["outcome"] == "success"
    selected = [e for e in _events(client, project_id, "RECOVERY_SELECTED")
                if e["task_id"] == task_id]
    retries = [e for e in _events(client, project_id, "RETRY_STARTED")
               if e["task_id"] == task_id]
    assert selected and selected[0]["payload"]["action"] == "retry_then_replan", selected
    assert retries, "expected RETRY_STARTED after the recovery decision"
    print("[2] scenario A: transient failure retried with backoff and completed")

    # --- Scenario B: exhausted ladder escalates to replan + terminal -----------
    requirement2 = client.post(
        f"/api/projects/{project_id}/requirements",
        json={
            "title": "Exhausted recovery",
            "description": "Always fails; must replan terminally.",
            "criteria": [{"description": "never succeeds", "kind": "command"}],
        },
    ).json()
    plan2 = client.post(
        f"/api/requirements/{requirement2['id']}/plans",
        json={
            "summary": "exhausted recovery",
            "tasks": [
                {
                    "title": "Doomed command",
                    "request": "Run the doomed command",
                    "payload": {"command": [sys.executable, "-c", "import sys; sys.exit(2)"]},
                    "retry_policy": {"max_attempts": 2, "backoff_seconds": 1},
                }
            ],
        },
    ).json()
    task2 = plan2["task_ids"][0]
    client.post(f"/api/tasks/{task2}/execute").raise_for_status()
    finished = _wait_task(client, task2)
    assert finished["status"] == "failed", f"scenario B ended {finished['status']}"
    assert len(finished["attempts"]) == 2, "ladder must stop at max_attempts (REC-002)"
    replanned = _events(client, project_id, "TASK_REPLANNED")
    assert any(e["task_id"] == task2 for e in replanned), "expected a durable replan (REC-003)"
    terminated = _events(client, project_id, "TASK_TERMINALLY_FAILED")
    assert any(e["task_id"] == task2 for e in terminated), "expected terminal failure evidence"
    tasks = client.get(f"/api/projects/{project_id}/tasks").json()
    replan_children = [t for t in tasks if (t.get("payload") or {}).get("kind") == "replan"]
    assert replan_children, "expected a replan follow-up task"
    print("[3] scenario B: ladder exhausted -> replan task + terminal failure with evidence")

    client.delete(f"/api/projects/{project_id}")
    print("RECOVERY SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

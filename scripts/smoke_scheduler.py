"""Scheduler smoke (Phase 4): bounded scheduling → Temporal execution → leases honored.

Usage (with the API running and Temporal reachable):
  1. docker compose --profile temporal up -d
  2. Start the worker:  python -m app.durable.worker   (cwd: services/api)
  3. Start the API with HARNESS_TEMPORAL_ENABLED=true
  4. Run:               python scripts/smoke_scheduler.py
"""

from __future__ import annotations

import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx

BASE = "http://localhost:8000"


def _wait_task(client: httpx.Client, task_id: str, timeout: float = 240) -> dict:
    deadline = time.time() + timeout
    task = client.get(f"/api/tasks/{task_id}").json()
    while time.time() < deadline and task["status"] not in ("completed", "failed", "cancelled"):
        time.sleep(2)
        task = client.get(f"/api/tasks/{task_id}").json()
    assert task["status"] == "completed", f"task ended as {task['status']}: {task}"
    return task


def main() -> int:
    project_root = Path(tempfile.mkdtemp(prefix="harness-scheduler-"))
    (project_root / "work.py").write_text("print('scheduled work: ' + 'x' * 700)\n", encoding="utf-8")
    client = httpx.Client(base_url=BASE, timeout=30)

    project_id = client.post("/api/projects/open", json={"root_path": str(project_root)}).json()["id"]
    print(f"[1] project: {project_id}")

    requirement = client.post(
        f"/api/projects/{project_id}/requirements",
        json={
            "title": "Scheduler smoke",
            "description": "Two tasks: one free, one blocked by an active resource lease.",
            "criteria": [{"description": "both tasks run successfully", "kind": "command"}],
        },
    ).json()
    lease_key = f"scheduler-smoke-{uuid.uuid4().hex[:8]}"
    plan = client.post(
        f"/api/requirements/{requirement['id']}/plans",
        json={
            "summary": "scheduler smoke",
            "tasks": [
                {
                    "title": "Free scheduled work",
                    "request": "Run work.py to completion",
                    "payload": {
                        "role": "implementer",
                        "command": [sys.executable, "work.py"],
                    },
                    "retry_policy": {"max_attempts": 2, "backoff_seconds": 1},
                },
                {
                    "title": "Lease-blocked work",
                    "request": "Runs only after the lease is released",
                    "payload": {
                        "role": "implementer",
                        "command": [sys.executable, "work.py"],
                        "resource_requirements": [{"kind": "branch", "key": lease_key}],
                    },
                    "retry_policy": {"max_attempts": 2, "backoff_seconds": 1},
                },
            ],
        },
    ).json()
    free_id, blocked_id = plan["task_ids"]
    print(f"[2] plan tasks: free={free_id} blocked={blocked_id}")

    lease = client.post(
        f"/api/projects/{project_id}/leases",
        json={"kind": "branch", "key": lease_key, "ttl_seconds": 300},
    )
    lease.raise_for_status()
    print(f"[3] lease held on branch/{lease_key}")

    tick = client.post(f"/api/projects/{project_id}/scheduler/tick").json()
    scheduled_titles = {entry["title"] for entry in tick["scheduled"]}
    skipped = {entry["title"]: entry["reason"] for entry in tick["skipped"]}
    assert scheduled_titles == {"Free scheduled work"}, f"unexpected schedule: {tick}"
    assert "actively leased" in skipped["Lease-blocked work"], f"unexpected skips: {tick}"
    print(f"[4] tick #1: free task scheduled, lease-blocked task skipped ({tick['started_count']} started)")

    _wait_task(client, free_id)
    print("[5] free task completed through live Temporal")

    released = client.post(f"/api/leases/{lease.json()['id']}/release")
    released.raise_for_status()
    tick2 = client.post(f"/api/projects/{project_id}/scheduler/tick").json()
    assert tick2["started_count"] == 1, f"expected the blocked task to start: {tick2}"
    _wait_task(client, blocked_id)
    print("[6] lease released -> second tick scheduled and completed the blocked task")

    state = client.get(f"/api/projects/{project_id}/scheduler/state").json()
    assert state["running"] == 0
    assert state["tasks_by_status"].get("completed") == 2
    print("[7] scheduler state: 0 running, 2 completed")

    client.delete(f"/api/projects/{project_id}")
    print("SCHEDULER SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

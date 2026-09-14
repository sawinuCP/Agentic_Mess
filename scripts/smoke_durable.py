"""Durable-core smoke: requirement → plan → task → Temporal execution → evidence.

Usage (with the API running and Temporal reachable):
  1. docker compose --profile temporal up -d
  2. Start the worker:  python -m app.durable.worker   (cwd: services/api)
  3. Start the API with HARNESS_TEMPORAL_ENABLED=true
  4. Run:               python scripts/smoke_durable.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8000"


def main() -> int:
    project_root = Path(tempfile.mkdtemp(prefix="harness-durable-"))
    (project_root / "work.py").write_text(
        "print('durable work complete: ' + 'x' * 700)\n", encoding="utf-8"
    )
    client = httpx.Client(base_url=BASE, timeout=30)

    project_id = client.post(
        "/api/projects/open", json={"root_path": str(project_root)}
    ).json()["id"]
    print(f"[1] project: {project_id}")

    requirement = client.post(
        f"/api/projects/{project_id}/requirements",
        json={
            "title": "Run durable work",
            "description": "A durable command executes to completion with evidence.",
            "criteria": [{"description": "work.py runs successfully", "kind": "command"}],
        },
    ).json()
    plan = client.post(
        f"/api/requirements/{requirement['id']}/plans",
        json={
            "summary": "durable smoke",
            "tasks": [
                {
                    "title": "Execute work command",
                    "request": "Run work.py to completion",
                    "payload": {"command": [sys.executable, "work.py"]},
                    "retry_policy": {"max_attempts": 2, "backoff_seconds": 1},
                }
            ],
        },
    ).json()
    task_id = plan["task_ids"][0]
    print(f"[2] requirement + plan + task: {task_id}")

    started = client.post(f"/api/tasks/{task_id}/execute")
    started.raise_for_status()
    print(f"[3] workflow started: {started.json()['workflow_id']}")

    deadline = time.time() + 240
    task = client.get(f"/api/tasks/{task_id}").json()
    while time.time() < deadline and task["status"] not in ("completed", "failed", "cancelled"):
        time.sleep(2)
        task = client.get(f"/api/tasks/{task_id}").json()
    assert task["status"] == "completed", f"task ended as {task['status']}: {task}"
    print("[4] task completed durably")

    assert task["attempts"], "no attempts recorded"
    assert task["attempts"][-1]["outcome"] == "success"
    evidence = task["attempts"][-1]["evidence_artifact_ids"]
    assert evidence, "expected evidence artifacts"
    content = client.get(f"/api/artifacts/{evidence[0]}/content").content
    assert b"durable work complete" in content
    print(f"[5] evidence verified: {len(evidence)} artifact(s)")

    client.delete(f"/api/projects/{project_id}")
    print("DURABLE SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

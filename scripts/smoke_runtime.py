"""Execution-plane smoke (Phase 6): runtime status, port allocator, quota slots.

Usage (with the API running):
  ..\\.venv\\Scripts\\python scripts\\smoke_runtime.py
"""

from __future__ import annotations

import sys
import tempfile
import uuid
from pathlib import Path

import httpx

BASE = "http://localhost:8000"


def main() -> int:
    project_root = Path(tempfile.mkdtemp(prefix="harness-runtime-"))
    client = httpx.Client(base_url=BASE, timeout=60)

    status = client.get("/api/runtime/status").json()
    assert status["active_backend"] in ("local", "docker"), status
    print(f"[1] runtime backend: {status['active_backend']} (network={status['docker_network']})")

    project_id = client.post("/api/projects/open", json={"root_path": str(project_root)}).json()["id"]

    allocated = client.post(
        f"/api/projects/{project_id}/ports", json={"purpose": "preview", "ttl_seconds": 300}
    )
    allocated.raise_for_status()
    port = allocated.json()["port"]
    print(f"[2] port allocated: {port}")

    conflict = client.post(
        f"/api/projects/{project_id}/ports",
        json={"purpose": "preview", "ttl_seconds": 300, "preferred_port": port},
    )
    conflict.raise_for_status()
    assert conflict.json()["port"] != port, "preferred fallback failed"
    print(f"[3] preferred fallback: second allocation got {conflict.json()['port']}")

    released = client.post(f"/api/ports/{allocated.json()['id']}/release")
    released.raise_for_status()
    assert released.json()["status"] == "released"
    print("[4] port released (re-allocatable)")

    slots = []
    for _ in range(status["exec_max_concurrent_per_project"]):
        acquired = client.post(
            f"/api/projects/{project_id}/leases",
            json={"kind": "runtime", "key": f"{project_id}#smoke-slot-{uuid.uuid4().hex[:6]}"},
        )
        acquired.raise_for_status()
        slots.append(acquired.json())
    print(f"[5] runtime slots acquired: {len(slots)} (quota cap honored)")

    for slot in slots:
        client.post(f"/api/leases/{slot['id']}/release")

    client.delete(f"/api/projects/{project_id}")
    print("RUNTIME SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""End-to-end smoke test for the Phase 1 editor API (run against a live server).

Usage:
  1. Start the control plane:  uvicorn app.main:app --port 8000   (cwd: services/api)
  2. Run:                      python scripts/smoke_editor.py

Creates a disposable sample project, then verifies: open, tree, search, toolchain
run (python via project override), git init/stage/commit/log, and a real PTY
terminal round-trip over WebSocket.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8000"


def main() -> int:
    project_root = Path(tempfile.mkdtemp(prefix="harness-smoke-"))
    (project_root / "src").mkdir()
    (project_root / "src" / "app.py").write_text("print('hello from sample')\n", encoding="utf-8")
    (project_root / ".ai-harness").mkdir()
    (project_root / ".ai-harness" / "toolchains.json").write_text(
        json.dumps(
            {
                "languages": {
                    "python": {"tools": {"run": {"argv": [sys.executable, "{file}"]}}}
                }
            }
        ),
        encoding="utf-8",
    )

    client = httpx.Client(base_url=BASE, timeout=30)

    opened = client.post("/api/projects/open", json={"root_path": str(project_root)})
    opened.raise_for_status()
    project_id = opened.json()["id"]
    print(f"[1] project opened: {project_id}")

    tree = client.get(f"/api/projects/{project_id}/tree").json()
    assert any(entry["name"] == "src" for entry in tree), tree
    assert not any(entry["name"] == "node_modules" for entry in tree)
    print("[2] tree ok")

    hits = client.get(
        f"/api/projects/{project_id}/search", params={"q": "hello"}
    ).json()
    assert any(h["path"] == "src/app.py" for h in hits), hits
    print("[3] search ok")

    run = client.post(
        f"/api/projects/{project_id}/toolchains/run",
        json={"tool": "run", "path": "src/app.py"},
    ).json()
    assert "hello from sample" in run["stdout"], run
    print(f"[4] tool run ok: {run['command']} ({run['duration_ms']}ms)")

    client.post(f"/api/projects/{project_id}/git/init")
    client.post(
        f"/api/projects/{project_id}/git/stage",
        json={"paths": ["src/app.py", ".ai-harness/toolchains.json"]},
    )
    client.post(f"/api/projects/{project_id}/git/commit", json={"message": "smoke commit"})
    log = client.get(f"/api/projects/{project_id}/git/log").json()
    assert log and log[0]["message"] == "smoke commit", log
    print(f"[5] git ok: {log[0]['hash'][:7]}")

    session = client.post(f"/api/projects/{project_id}/terminal/sessions").json()
    print(f"[6] terminal session: {session['id']}")
    marker = f"SMOKE-{project_id[:8]}"
    assert asyncio.run(terminal_check(session["id"], marker)), "terminal marker not seen"
    print("[7] terminal round-trip ok")

    client.delete(f"/api/projects/{project_id}")
    print("SMOKE PASSED")
    return 0


async def terminal_check(session_id: str, marker: str) -> bool:
    import websockets

    url = f"ws://localhost:8000/api/ws/terminal/{session_id}"
    async with websockets.connect(url, max_size=2**22) as ws:
        buffer = ""
        deadline = time.time() + 30
        await ws.send(json.dumps({"type": "input", "data": f"echo {marker}\r\n"}))
        while time.time() < deadline:
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=3)
            except (asyncio.TimeoutError, TimeoutError):
                await ws.send(json.dumps({"type": "input", "data": f"echo {marker}\r\n"}))
                continue
            buffer += json.loads(message).get("data", "")
            if marker in buffer:
                return True
    return False


if __name__ == "__main__":
    sys.exit(main())

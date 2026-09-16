"""Phase-7 integrations smoke: browser debugging + MCP gateway + web research.

Usage (with the API running):
  ..\\.venv\\Scripts\\python scripts\\smoke_integrations.py

Browser/MCP/research all run against localhost only (no external network needed
except the optional research search, whose failure is tolerated gracefully).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import httpx

BASE = "http://localhost:8000"


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=120)
    project_root = Path(tempfile.mkdtemp(prefix="harness-integrations-"))

    status = client.get("/api/runtime/status")
    status.raise_for_status()

    # --- 1. Browser debugging (FR-020): real chromium vs a local page ---------
    project_id = (
        client.post("/api/projects/open", json={"root_path": str(project_root)}).json()["id"]
    )

    opened = client.post(
        f"/api/projects/{project_id}/browser/sessions",
        json={"url": f"{BASE}/healthz"},
    )
    opened.raise_for_status()
    session_id = opened.json()["session_id"]
    print(f"[1] browser session opened: {session_id[:8]}")

    screenshot = client.post(
        f"/api/projects/{project_id}/browser/sessions/{session_id}/screenshot",
        json={"full_page": True},
    )
    screenshot.raise_for_status()
    print(f"[2] screenshot artifact: {screenshot.json()['artifact_id'][:8]}...")

    console = client.get(
        f"/api/projects/{project_id}/browser/sessions/{session_id}/console"
    ).json()
    print(f"[3] console entries captured: {len(console)}")
    client.delete(f"/api/projects/{project_id}/browser/sessions/{session_id}")

    # --- 2. Web research (FR-022): fetch + evidence packet ---------------------
    fetched = client.post(
        f"/api/projects/{project_id}/research/fetch",
        json={"url": f"{BASE}/healthz"},
    )
    fetched.raise_for_status()
    packet = fetched.json()
    print(f"[4] research fetch: title={packet['title']!r} artifact={packet['artifact_id'][:8]}...")

    # --- 3. Web search (FR-022): live DDG (tolerated failure) ------------------
    try:
        search = client.post(
            f"/api/projects/{project_id}/research/search",
            json={"query": "model context protocol", "max_results": 3},
        )
        if search.status_code == 200:
            print(f"[5] web search results: {len(search.json()['results'])}")
        else:
            print("[5] web search unavailable (network/provider) — tolerated")
    except httpx.HTTPError:
        print("[5] web search unavailable — tolerated")

    # --- 4. MCP gateway (FR-021): disabled by default → fail-closed 503 --------
    mcp_status = client.get("/api/mcp/status").json()
    call = client.post(
        "/api/mcp/call", json={"server": "x", "tool": "y", "arguments": {}}
    )
    assert call.status_code == 503, "MCP must fail closed when disabled"
    print(f"[6] MCP fail-closed verified (enabled={mcp_status['enabled']})")

    client.delete(f"/api/projects/{project_id}")
    print("INTEGRATIONS SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

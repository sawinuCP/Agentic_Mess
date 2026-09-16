"""Code-intelligence smoke (Phase 5): index → symbols → retrieval → SCIP.

Usage (with the API running):
  ..\\.venv\\Scripts\\python scripts\\smoke_intelligence.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import httpx

BASE = "http://localhost:8000"

PY_APP = '''\
def process_order(order_id: str) -> str:
    """Process one order end to end."""
    return order_id.strip()


class OrderBook:
    def add(self, order_id: str) -> str:
        return process_order(order_id)
'''

TS_UTIL = '''\
export function format_money(cents: number): string {
  return `$${cents / 100}`;
}
'''


def main() -> int:
    project_root = Path(tempfile.mkdtemp(prefix="harness-intelligence-"))
    (project_root / "src").mkdir()
    (project_root / "src" / "app.py").write_text(PY_APP, encoding="utf-8")
    (project_root / "src" / "util.ts").write_text(TS_UTIL, encoding="utf-8")
    client = httpx.Client(base_url=BASE, timeout=60)

    project_id = client.post("/api/projects/open", json={"root_path": str(project_root)}).json()["id"]
    print(f"[1] project: {project_id}")

    stats = client.post(f"/api/projects/{project_id}/intelligence/index", json={}).json()
    assert stats["indexed"] == 2 and stats["symbols"] == 4, stats
    print(f"[2] indexed: {stats['files']} files, {stats['symbols']} symbols")

    status = client.get(f"/api/projects/{project_id}/intelligence/status").json()
    assert status["engines"]["python"] == "ast"
    assert status["engines"]["typescript"] == "tree-sitter"

    incremental = client.post(f"/api/projects/{project_id}/intelligence/index", json={}).json()
    assert incremental["skipped"] == 2 and incremental["symbols"] == 4
    print("[3] incremental reindex: all files skipped (hash match, PERF-008)")

    hits = client.get(
        f"/api/projects/{project_id}/intelligence/retrieve", params={"q": "process an order"}
    ).json()["hits"]
    assert hits and hits[0]["name"] == "process_order", hits
    print(f"[4] hybrid retrieval top hit: {hits[0]['path']}:{hits[0]['start_line']} {hits[0]['name']}")

    symbols = client.get(f"/api/projects/{project_id}/symbols", params={"q": "order"}).json()
    assert {"process_order", "OrderBook"} <= {s["name"] for s in symbols}

    scip = client.get(f"/api/projects/{project_id}/intelligence/scip").json()
    assert len(scip["documents"]) == 2 and all(d["occurrences"] for d in scip["documents"])
    print("[5] SCIP-JSON export: 2 documents with definition occurrences")

    client.delete(f"/api/projects/{project_id}")
    print("INTELLIGENCE SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

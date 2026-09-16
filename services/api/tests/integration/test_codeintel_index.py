"""Symbol index integration (PERF-008): full/incremental indexing, search, SCIP export."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

PY_APP = '''
def process_order(order_id: str) -> str:
    """Process one order."""
    return order_id

class OrderBook:
    def add(self, order_id: str) -> None:
        process_order(order_id)
'''

TS_UTIL = """
export function format_money(cents: number): string {
  return `$${cents / 100}`;
}
"""


def _write(root: Path, rel: str, content: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _index(client: TestClient, project_id: str, body: dict | None = None) -> dict:
    response = client.post(f"/api/projects/{project_id}/intelligence/index", json=body or {})
    assert response.status_code == 200
    return response.json()


def test_index_full_and_incremental(project: tuple) -> None:
    app, client, project_id, root = project
    _write(root, "src/app.py", PY_APP)
    _write(root, "src/util.ts", TS_UTIL)

    first = _index(client, project_id)
    assert first["indexed"] == 2 and first["skipped"] == 0
    assert first["symbols"] == 4  # process_order, OrderBook, add, format_money

    # Incremental: nothing changed → everything skipped (PERF-008).
    second = _index(client, project_id)
    assert second["indexed"] == 0 and second["updated"] == 0
    assert second["skipped"] == 2 and second["symbols"] == 4

    # Change one file → exactly that file is re-indexed.
    _write(root, "src/app.py", PY_APP + "\ndef cancel_order(order_id: str) -> None:\n    pass\n")
    third = _index(client, project_id)
    assert third["updated"] == 1 and third["skipped"] == 1
    assert third["symbols"] == 5

    # Full rebuild re-extracts everything (counted as updates to existing files).
    fourth = _index(client, project_id, {"full": True})
    assert fourth["updated"] == 2 and fourth["skipped"] == 0
    assert fourth["symbols"] == 5

    # Deleted file → symbols pruned.
    (root / "src" / "util.ts").unlink()
    fifth = _index(client, project_id)
    assert fifth["removed"] == 1
    assert fifth["symbols"] == 4


def test_symbol_search_and_document_symbols(project: tuple) -> None:
    app, client, project_id, root = project
    _write(root, "src/app.py", PY_APP)
    _index(client, project_id)

    hits = client.get(f"/api/projects/{project_id}/symbols?q=order").json()
    names = {hit["name"] for hit in hits}
    assert {"process_order", "OrderBook"} <= names  # name-substring search
    assert all(hit["language"] == "python" for hit in hits)

    method = client.get(f"/api/projects/{project_id}/symbols?q=add&kind=method").json()
    assert [hit["name"] for hit in method] == ["add"]
    assert method[0]["parent"] == "OrderBook"

    doc = client.get(f"/api/projects/{project_id}/symbols/file?path=src/app.py").json()
    assert {symbol["name"] for symbol in doc} == {"process_order", "OrderBook", "add"}

    status = client.get(f"/api/projects/{project_id}/intelligence/status").json()
    assert status["engines"]["python"] == "ast"
    assert status["by_language"] == {"python": 1}


def test_scip_export_contains_definitions(project: tuple) -> None:
    app, client, project_id, root = project
    _write(root, "src/app.py", PY_APP)
    _index(client, project_id)

    export = client.get(f"/api/projects/{project_id}/intelligence/scip").json()
    assert export["metadata"]["toolInfo"]["name"] == "ai-harness"
    (document,) = export["documents"]
    assert document["relativePath"] == "src/app.py"
    assert document["language"] == "python"
    monikers = {occ["symbol"] for occ in document["occurrences"]}
    assert any(moniker.endswith("process_order().") for moniker in monikers)
    assert any("#add()." in moniker for moniker in monikers)

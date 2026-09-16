"""Hybrid retrieval integration (Phase 5): lexical first, embeddings as one ranker."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.codeintel.retrieval import retrieve

pytestmark = pytest.mark.integration

SOURCES = {
    "src/leases_svc.py": (
        "def renew_lease(lease_id: str) -> str:\n"
        '    """Heartbeat renewal extends the lease TTL."""\n'
        "    return lease_id\n"
        "\n"
        "class LeaseBook:\n"
        "    def expire(self) -> None:\n"
        "        pass\n"
    ),
    "src/editor_ui.py": (
        'def render_tab_strip() -> None:\n    """Draw the editor tab strip."""\n    return None\n'
    ),
}


def _indexed_project(project: tuple) -> tuple[FastAPI, TestClient, str]:
    app, client, project_id, root = project
    for rel, content in SOURCES.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    response = client.post(f"/api/projects/{project_id}/intelligence/index", json={})
    assert response.status_code == 200
    return app, client, project_id


def test_retrieval_ranks_the_relevant_symbol_first(project: tuple) -> None:
    app, _client, project_id = _indexed_project(project)
    with app.state.session_factory() as session:
        hits = retrieve(session, project_id, "renew lease heartbeat ttl", k=3)
    assert hits, "expected retrieval hits"
    assert hits[0].name == "renew_lease"
    assert hits[0].matched in ("hybrid", "lexical", "semantic")
    assert hits[0].path == "src/leases_svc.py"


def test_retrieval_endpoint_returns_path_anchored_hits(project: tuple) -> None:
    _app, client, project_id = _indexed_project(project)
    response = client.get(
        f"/api/projects/{project_id}/intelligence/retrieve",
        params={"q": "render tab strip editor"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "render tab strip editor"
    assert body["hits"], "expected hits"
    top = body["hits"][0]
    assert top["name"] == "render_tab_strip"
    assert top["path"].startswith("src/")
    assert 0.0 <= top["score"] <= 1.0


def test_retrieval_never_blows_up_on_an_unindexed_project(project: tuple) -> None:
    app, _client, project_id, _root = project
    with app.state.session_factory() as session:
        assert retrieve(session, project_id, "anything", k=3) == []

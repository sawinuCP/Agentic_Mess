"""Web research integration (FR-022): fetch evidence packets + provenance."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.research import service as research_service

pytestmark = pytest.mark.integration


class _PageHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — http.server API
        body = (
            b"<html><head><title>Research Target</title></head>"
            b"<body><p>the quick brown fact</p><script>var hidden = true;</script></body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        pass


@pytest.fixture(scope="module")
def page_server() -> Iterator[str]:
    server = HTTPServer(("127.0.0.1", 0), _PageHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_fetch_creates_evidence_packet_with_provenance(
    project: tuple, page_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _app, client, project_id, _tmp = project
    # Local targets require the EXPLICIT dev opt-in (Wave 1 SSRF posture):
    # private/loopback destinations are denied by default.
    monkeypatch.setattr(_app.state.settings, "research_private_hosts_allowed", True)

    result = client.post(f"/api/projects/{project_id}/research/fetch", json={"url": page_server})
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["title"] == "Research Target"
    assert "the quick brown fact" in body["excerpt"]
    assert "hidden" not in body["excerpt"]  # script content excluded (facts only)
    assert body["confidence"] == 0.9  # fetched pages: high confidence (spec §22)

    # Raw content is a durable artifact.
    artifact = client.get(f"/api/artifacts/{body['artifact_id']}/content")
    assert artifact.status_code == 200
    assert b"Research Target" in artifact.content

    # Provenance is a T5 context item (retrievable as research evidence).
    items = client.get(f"/api/projects/{project_id}/context-items", params={"tier": 5})
    assert items.status_code == 200
    refs = {item["ref"] for item in items.json()}
    assert page_server in refs


def test_fetch_denies_private_destinations_by_default(project: tuple, page_server: str) -> None:
    """Wave 1 security contract: loopback/private destinations are blocked unless
    ``research_private_hosts_allowed`` is explicitly opted in."""
    _app, client, project_id, _tmp = project
    result = client.post(f"/api/projects/{project_id}/research/fetch", json={"url": page_server})
    assert result.status_code == 403, result.text
    assert "SSRF policy" in result.json()["detail"]


def test_fetch_rejects_non_http_schemes(project: tuple) -> None:
    _app, client, project_id, _tmp = project
    result = client.post(
        f"/api/projects/{project_id}/research/fetch", json={"url": "file:///etc/passwd"}
    )
    assert result.status_code == 422


def test_search_returns_provenance(project: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    _app, client, project_id, _tmp = project

    async def _stub(query: str, *, max_results: int, timeout: float) -> list[dict[str, str]]:
        return [
            {"title": "Result A", "url": "https://a.example.com/x", "source": "duckduckgo"},
            {"title": "Result B", "url": "https://b.example.com/y", "source": "duckduckgo"},
        ]

    monkeypatch.setattr(research_service, "search_web", _stub)
    result = client.post(
        f"/api/projects/{project_id}/research/search",
        json={"query": "harness", "max_results": 2},
    )
    assert result.status_code == 200
    body = result.json()
    assert len(body["results"]) == 2
    assert all(r["source"] == "duckduckgo" for r in body["results"])

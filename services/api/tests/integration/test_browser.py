"""Browser debugging integration (FR-020): real chromium against a local page."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


class _PageHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 — http.server API
        if self.path == "/missing":
            self.send_response(404)
            self.end_headers()
            return
        body = (
            b"<html><head><title>Harness Page</title></head>"
            b"<body><h1>hello</h1><script>console.log('console-captured')</script>"
            b'<img src="/missing"></body></html>'
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
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture()
def browser_client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_browser_session_captures_evidence(
    browser_client: TestClient, project: tuple, page_server: str
) -> None:
    _app, client, project_id, _tmp = project
    opened = client.post(
        f"/api/projects/{project_id}/browser/sessions", json={"url": f"{page_server}/"}
    )
    assert opened.status_code == 201, opened.text
    session_id = opened.json()["session_id"]
    assert opened.json()["title"] == "Harness Page"

    console = client.get(f"/api/projects/{project_id}/browser/sessions/{session_id}/console").json()
    assert any("console-captured" in entry["text"] for entry in console)

    network = client.get(f"/api/projects/{project_id}/browser/sessions/{session_id}/network").json()
    assert any(entry["status"] == 404 for entry in network)  # the missing img

    screenshot = client.post(
        f"/api/projects/{project_id}/browser/sessions/{session_id}/screenshot",
        json={"full_page": True},
    )
    assert screenshot.status_code == 200
    artifact_id = screenshot.json()["artifact_id"]
    content = client.get(f"/api/artifacts/{artifact_id}/content")
    assert content.status_code == 200
    assert content.content[:8] == b"\x89PNG\r\n\x1a\n"  # real PNG

    closed = client.delete(f"/api/projects/{project_id}/browser/sessions/{session_id}")
    assert closed.status_code == 204

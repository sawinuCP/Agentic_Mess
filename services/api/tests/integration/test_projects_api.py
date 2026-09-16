"""Project + filesystem API against live PostgreSQL and disk (integration)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


@pytest.fixture()
def sample_project(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# sample\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("x\n", encoding="utf-8")
    return tmp_path


def _client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_open_tree_read_write_search_flow(app: FastAPI, sample_project: Path) -> None:
    with _client(app) as client:
        opened = client.post("/api/projects/open", json={"root_path": str(sample_project)})
        assert opened.status_code == 200
        project_id = opened.json()["id"]

        # Idempotent open returns the same registration.
        again = client.post("/api/projects/open", json={"root_path": str(sample_project)})
        assert again.json()["id"] == project_id

        tree = client.get(f"/api/projects/{project_id}/tree").json()
        names = {e["name"] for e in tree}
        assert {"src", "README.md"} <= names
        assert "node_modules" not in names

        read = client.get(f"/api/projects/{project_id}/file", params={"path": "README.md"})
        assert read.status_code == 200 and "# sample" in read.json()["content"]

        written = client.put(
            f"/api/projects/{project_id}/file",
            json={"path": "README.md", "content": "# changed\n"},
        )
        assert written.status_code == 200

        hits = client.get(f"/api/projects/{project_id}/search", params={"q": "hello"}).json()
        assert any(h["path"] == "src/app.py" for h in hits)

        quick = client.get(f"/api/projects/{project_id}/files", params={"q": "app"}).json()
        assert "src/app.py" in quick

        escaped = client.get(f"/api/projects/{project_id}/file", params={"path": "../x"})
        assert escaped.status_code == 400

        missing = client.get("/api/projects/00000000-0000-0000-0000-000000000000")
        assert missing.status_code == 404

        deleted = client.delete(f"/api/projects/{project_id}")
        assert deleted.status_code == 204


def test_project_root_must_exist(app: FastAPI) -> None:
    # Absolute on every platform, guaranteed nonexistent — hits the 404 branch
    # (a relative path would 422 before the existence check).
    missing = Path(tempfile.gettempdir()) / "definitely-not-there-harness" / "deeper"
    with _client(app) as client:
        resp = client.post("/api/projects/open", json={"root_path": str(missing)})
        assert resp.status_code == 404


def test_toolchain_detection_endpoint(app: FastAPI, sample_project: Path) -> None:
    (sample_project / ".ai-harness").mkdir()
    exe = sys.executable.replace("\\", "\\\\")
    (sample_project / ".ai-harness" / "toolchains.json").write_text(
        '{"languages": {"python": {"tools": {"run": {"argv": ["' + exe + '", "{file}"]}}}}}',
        encoding="utf-8",
    )
    with _client(app) as client:
        opened = client.post("/api/projects/open", json={"root_path": str(sample_project)})
        project_id = opened.json()["id"]

        info = client.get(f"/api/projects/{project_id}/toolchains").json()
        python = next(lang for lang in info["languages"] if lang["id"] == "python")
        assert python["availability"]["run"]["available"] is True
        assert info["override_file"] is True

        run = client.post(
            f"/api/projects/{project_id}/toolchains/run",
            json={"tool": "run", "path": "src/app.py"},
        )
        assert run.status_code == 200
        body = run.json()
        assert body["exit_code"] == 0
        assert "hello" in body["stdout"]

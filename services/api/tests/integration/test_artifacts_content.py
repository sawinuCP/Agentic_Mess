"""Artifact content serving: streaming full bodies + single-range requests."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _upload(client: object, project_id: str, data: bytes) -> str:
    response = client.post(  # type: ignore[union-attr]
        f"/api/projects/{project_id}/artifacts",
        files={"file": ("log.txt", data, "text/plain")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_full_body_streams_with_accept_ranges(project: tuple) -> None:
    _app, client, project_id, _tmp = project
    data = b"0123456789" * 1000
    artifact_id = _upload(client, project_id, data)
    response = client.get(f"/api/artifacts/{artifact_id}/content")
    assert response.status_code == 200
    assert response.content == data
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(len(data))


def test_single_range_returns_206_with_content_range(project: tuple) -> None:
    _app, client, project_id, _tmp = project
    data = b"0123456789" * 100
    artifact_id = _upload(client, project_id, data)
    response = client.get(f"/api/artifacts/{artifact_id}/content", headers={"Range": "bytes=10-19"})
    assert response.status_code == 206
    assert response.content == data[10:20]
    assert response.headers["content-range"] == f"bytes 10-19/{len(data)}"
    assert response.headers["content-length"] == "10"


def test_open_and_suffix_ranges(project: tuple) -> None:
    _app, client, project_id, _tmp = project
    data = b"0123456789" * 100
    artifact_id = _upload(client, project_id, data)
    tail_open = client.get(f"/api/artifacts/{artifact_id}/content", headers={"Range": "bytes=990-"})
    assert tail_open.status_code == 206
    assert tail_open.content == data[990:]
    suffix = client.get(f"/api/artifacts/{artifact_id}/content", headers={"Range": "bytes=-50"})
    assert suffix.status_code == 206
    assert suffix.content == data[-50:]
    assert suffix.headers["content-range"] == f"bytes {len(data) - 50}-{len(data) - 1}/{len(data)}"


def test_unsatisfiable_and_malformed_ranges_are_416(project: tuple) -> None:
    _app, client, project_id, _tmp = project
    artifact_id = _upload(client, project_id, b"0123456789")
    assert (
        client.get(
            f"/api/artifacts/{artifact_id}/content", headers={"Range": "bytes=100-200"}
        ).status_code
        == 416
    )
    assert (
        client.get(
            f"/api/artifacts/{artifact_id}/content", headers={"Range": "bytes=abc"}
        ).status_code
        == 416
    )
    assert (
        client.get(
            f"/api/artifacts/{artifact_id}/content", headers={"Range": "bytes=0-1,3-4"}
        ).status_code
        == 416
    )


def test_missing_artifact_is_404_not_500(project: tuple) -> None:
    import uuid

    _app, client, _project_id, _tmp = project
    assert client.get(f"/api/artifacts/{uuid.uuid4()}/content").status_code == 404

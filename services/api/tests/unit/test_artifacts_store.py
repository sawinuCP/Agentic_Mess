"""Content-addressed artifact store behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.artifacts.store import ArtifactStore, ArtifactStoreError


@pytest.fixture()
def store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "artifacts")


def test_put_and_open_roundtrip(store: ArtifactStore) -> None:
    blob = store.put(b"hello evidence")
    assert blob.size == len(b"hello evidence")
    assert store.open(blob.storage_path) == b"hello evidence"


def test_identical_content_is_deduplicated(store: ArtifactStore) -> None:
    first = store.put(b"same bytes")
    second = store.put(b"same bytes")
    assert first.sha256 == second.sha256
    assert first.storage_path == second.storage_path


def test_storage_path_is_content_addressed(store: ArtifactStore) -> None:
    blob = store.put(b"x")
    assert blob.storage_path.startswith(f"{blob.sha256[:2]}/{blob.sha256[2:4]}/")


def test_open_rejects_escape_paths(store: ArtifactStore) -> None:
    with pytest.raises(ArtifactStoreError):
        store.open("../outside.txt")

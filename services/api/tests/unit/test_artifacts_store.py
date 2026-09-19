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


def test_blob_size_reports_without_reading(store: ArtifactStore) -> None:
    blob = store.put(b"0123456789")
    assert store.blob_size(blob.storage_path) == 10
    with pytest.raises(ArtifactStoreError):
        store.blob_size("aa/bb/" + "0" * 64)


def test_read_range_returns_bounded_slices(store: ArtifactStore) -> None:
    blob = store.put(b"0123456789")
    assert store.read_range(blob.storage_path, 2, 4) == b"2345"
    assert store.read_range(blob.storage_path, 8, 100) == b"89"  # clamped, not error
    assert store.read_range(blob.storage_path, 10, 10) == b""
    with pytest.raises(ArtifactStoreError):
        store.read_range(blob.storage_path, 11, 1)
    with pytest.raises(ArtifactStoreError):
        store.read_range("../outside.txt", 0, 1)


def test_store_errors_map_onto_http_statuses() -> None:
    from app.core.errors import DomainError

    assert issubclass(ArtifactStoreError, DomainError)

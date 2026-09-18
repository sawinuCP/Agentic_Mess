"""Unit tests: artifact blob retention (bounded, age-based)."""

from __future__ import annotations

import os
import time
from pathlib import Path

from app.realtime.retention import prune_artifact_blobs


def test_prune_removes_only_blobs_past_window(tmp_path: Path) -> None:
    old_blob = tmp_path / "aa" / "bb" / "oldsha"
    new_blob = tmp_path / "cc" / "dd" / "newsha"
    old_blob.parent.mkdir(parents=True)
    new_blob.parent.mkdir(parents=True)
    old_blob.write_bytes(b"old")
    new_blob.write_bytes(b"new")
    past = time.time() - 10 * 24 * 3600
    os.utime(old_blob, (past, past))

    removed = prune_artifact_blobs(tmp_path, older_than_days=1)

    assert removed == 1
    assert not old_blob.exists()
    assert new_blob.exists()


def test_prune_disabled_or_missing_root_is_noop(tmp_path: Path) -> None:
    assert prune_artifact_blobs(tmp_path, older_than_days=0) == 0
    assert prune_artifact_blobs(tmp_path / "missing", older_than_days=5) == 0


def test_prune_keeps_tmp_files(tmp_path: Path) -> None:
    tmp_blob = tmp_path / "ab" / "cd" / "inflight.tmp"
    tmp_blob.parent.mkdir(parents=True)
    tmp_blob.write_bytes(b"partial")
    past = time.time() - 30 * 24 * 3600
    os.utime(tmp_blob, (past, past))

    assert prune_artifact_blobs(tmp_path, older_than_days=1) == 0
    assert tmp_blob.exists()

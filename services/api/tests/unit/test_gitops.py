"""Git client behaviour against a real temp repository (skips if git is missing)."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from app.gitops.client import GitClient, GitError

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    for args in (
        ["init"],
        ["config", "user.email", "test@example.com"],
        ["config", "user.name", "Test"],
    ):
        subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, check=True)
    return tmp_path


def _commit_file(repo: Path, name: str, content: str, message: str) -> None:
    (repo / name).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", name], cwd=repo, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, capture_output=True, check=True)


def test_status_on_non_repository(tmp_path: Path) -> None:
    with pytest.raises(GitError) as excinfo:
        asyncio.run(GitClient(tmp_path).status())
    assert excinfo.value.kind == "not_a_repo"


def test_status_stage_commit_log_cycle(repo: Path) -> None:
    client = GitClient(repo)
    (repo / "hello.txt").write_text("hi\n", encoding="utf-8")

    status = asyncio.run(client.status())
    entry = next(e for e in status.entries if e.path == "hello.txt")
    assert entry.index_status == "?" and entry.worktree_status == "?"

    asyncio.run(client.stage(["hello.txt"]))
    status = asyncio.run(client.status())
    entry = next(e for e in status.entries if e.path == "hello.txt")
    assert entry.index_status == "A"

    asyncio.run(client.commit("add hello"))
    status = asyncio.run(client.status())
    assert status.entries == []
    assert status.branch is not None

    commits = asyncio.run(client.log(10))
    assert len(commits) == 1
    assert commits[0].message == "add hello"
    assert commits[0].hash


def test_diff_and_file_at(repo: Path) -> None:
    _commit_file(repo, "hello.txt", "v1\n", "first")
    (repo / "hello.txt").write_text("v2\n", encoding="utf-8")
    client = GitClient(repo)

    diff = asyncio.run(client.diff("hello.txt"))
    assert "-v1" in diff and "+v2" in diff

    original = asyncio.run(client.file_at("HEAD", "hello.txt"))
    assert original == "v1\n"


def test_branches_and_checkout(repo: Path) -> None:
    _commit_file(repo, "hello.txt", "v1\n", "first")
    client = GitClient(repo)
    asyncio.run(client.checkout("feature/x", create=True))
    current = asyncio.run(client.current_branch())
    assert current == "feature/x"
    assert "feature/x" in asyncio.run(client.branches())


def test_empty_commit_message_rejected(repo: Path) -> None:
    with pytest.raises(GitError):
        asyncio.run(GitClient(repo).commit("   "))

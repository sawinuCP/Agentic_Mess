"""Filesystem service behaviour: path safety, tree, read/write, create/delete/rename."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.files.service import FileServiceError, ProjectFiles


@pytest.fixture()
def project(tmp_path: Path) -> ProjectFiles:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("x", encoding="utf-8")
    return ProjectFiles(tmp_path)


def test_tree_hides_ignored_dirs(project: ProjectFiles) -> None:
    entries = {e.name: e for e in project.tree("")}
    assert {"src", "README.md"} <= set(entries)
    assert "node_modules" not in entries


def test_tree_reports_children_flag(project: ProjectFiles) -> None:
    entries = {e.name: e for e in project.tree("")}
    assert entries["src"].has_children is True
    assert entries["src"].kind == "directory"


def test_path_escape_is_rejected(project: ProjectFiles) -> None:
    # Only paths that actually resolve outside the root are rejected; lexical
    # normalization (e.g. "a/../..") that stays inside the root is allowed.
    evils = ["../outside.txt"]
    if os.name == "nt":
        evils += ["C:/Windows/system32/config", "\\\\server\\share\\file.txt"]
    else:
        evils += ["/etc/passwd"]
    for evil in evils:
        with pytest.raises(FileServiceError):
            project.resolve(evil)


def test_lexically_normalizing_paths_stay_inside_root(project: ProjectFiles) -> None:
    resolved = project.resolve("src/../README.md")
    assert resolved == project.root / "README.md"


def test_write_read_roundtrip(project: ProjectFiles) -> None:
    content = project.write("src/new.py", "x = 1\n")
    assert content.content == "x = 1\n"
    assert project.read("src/new.py").content == "x = 1\n"


def test_binary_file_detected(project: ProjectFiles) -> None:
    (project.root / "img.bin").write_bytes(b"\x00\x01\x02binary")
    assert project.read("img.bin").is_binary is True


def test_create_rename_delete(project: ProjectFiles) -> None:
    project.create("docs", "directory")
    project.create("docs/guide.md", "file")
    project.rename("docs/guide.md", "docs/guide2.md")
    assert (project.root / "docs" / "guide2.md").exists()
    project.delete("docs/guide2.md")
    assert not (project.root / "docs" / "guide2.md").exists()


def test_delete_refuses_root_and_git(project: ProjectFiles) -> None:
    with pytest.raises(FileServiceError):
        project.delete("")
    (project.root / ".git").mkdir()
    with pytest.raises(FileServiceError):
        project.delete(".git")

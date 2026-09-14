"""Search and quick-open listing behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.files.search import ProjectSearch
from app.files.service import FileServiceError, ProjectFiles


@pytest.fixture()
def search(tmp_path: Path) -> ProjectSearch:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text(
        "def alpha():\n    return 'needle'\n", encoding="utf-8"
    )
    (tmp_path / "src" / "util.py").write_text("NEEDLE = 1\n", encoding="utf-8")
    (tmp_path / "data.bin").write_bytes(b"\x00needle\x00")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("needle\n", encoding="utf-8")
    return ProjectSearch(ProjectFiles(tmp_path))


def test_search_finds_matches_and_skips_binary_and_ignored(search: ProjectSearch) -> None:
    matches = search.search("needle")
    paths = {m.path for m in matches}
    assert "src/app.py" in paths
    assert "src/util.py" in paths
    assert "data.bin" not in paths  # binary
    assert all(not p.startswith("node_modules") for p in paths)


def test_search_case_sensitive(search: ProjectSearch) -> None:
    assert search.search("NEEDLE", case_sensitive=True)[0].path == "src/util.py"


def test_search_regex_and_invalid_regex(search: ProjectSearch) -> None:
    matches = search.search(r"'needle'$", is_regex=True)
    assert any(m.path == "src/app.py" and m.line == 2 for m in matches)
    with pytest.raises(FileServiceError):
        search.search("([unclosed", is_regex=True)


def test_search_reports_line_numbers(search: ProjectSearch) -> None:
    match = next(m for m in search.search("return 'needle'"))
    assert match.line == 2 and match.column > 0


def test_list_files_for_quick_open(search: ProjectSearch) -> None:
    all_paths = search.list_files("")
    assert "src/app.py" in all_paths
    ranked = search.list_files("app")
    assert ranked[0] == "src/app.py"

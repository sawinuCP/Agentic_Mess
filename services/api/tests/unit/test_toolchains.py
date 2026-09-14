"""Toolchain registry, detection, overrides and tool execution (LANG-001..003)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from app.files.service import ProjectFiles
from app.toolchains.detection import detect_languages
from app.toolchains.errors import ToolchainError
from app.toolchains.overrides import load_definition
from app.toolchains.registry import definition_for_extension, get_definition
from app.toolchains.service import _substitute, run_tool


@pytest.fixture()
def mixed_project(tmp_path: Path) -> Path:
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text("{}", encoding="utf-8")
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "main.ts").write_text("console.log(1);\n", encoding="utf-8")
    return tmp_path


def test_detection_by_manifest_and_extension(mixed_project: Path) -> None:
    detected = {d.id: d for d in detect_languages(mixed_project)}
    assert {"python", "javascript", "typescript"} <= set(detected)
    assert "pyproject.toml" not in detected["python"].manifests
    assert "package.json" in detected["javascript"].manifests
    assert detected["javascript"].file_count == 0  # manifest-only is still a hit


def test_detection_empty_project(tmp_path: Path) -> None:
    assert detect_languages(tmp_path) == []


def test_registry_lookup() -> None:
    assert definition_for_extension(".PY") is not None  # case-insensitive
    assert definition_for_extension(".zzz") is None
    assert get_definition("python").monaco_language == "python"
    with pytest.raises(ToolchainError):
        get_definition("brainfuck")


def test_override_merging(tmp_path: Path) -> None:
    harness = tmp_path / ".ai-harness"
    harness.mkdir()
    (harness / "toolchains.json").write_text(
        '{"languages": {"python": {"tools": {"format": {"argv": ["ruff", "format", "{file}"], '
        '"in_place": true}, "make_tea": {"argv": ["echo"]}}}}}',
        encoding="utf-8",
    )
    definition, diagnostics = load_definition("python", tmp_path)
    assert definition.tools["format"].argv == ("ruff", "format", "{file}")
    assert definition.tools["format"].in_place is True
    assert any("make_tea" in d for d in diagnostics)  # unknown tool ignored


def test_override_invalid_json_rejected(tmp_path: Path) -> None:
    harness = tmp_path / ".ai-harness"
    harness.mkdir()
    (harness / "toolchains.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(ToolchainError) as excinfo:
        load_definition("python", tmp_path)
    assert excinfo.value.status_code == 422


def test_substitute_placeholders(tmp_path: Path) -> None:
    argv = _substitute(
        ("run", "{file}", "{file_abs}", "{dir}", "{file_stem}"),
        file_rel="src/app.py",
        root=tmp_path,
    )
    assert argv == ["run", "src/app.py", str(tmp_path / "src" / "app.py"), "src", "app"]


def test_placeholder_without_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ToolchainError):
        _substitute(("black", "{file}"), file_rel=None, root=tmp_path)


def test_missing_tool_is_actionable(tmp_path: Path) -> None:
    harness = tmp_path / ".ai-harness"
    harness.mkdir()
    (harness / "toolchains.json").write_text(
        '{"languages": {"python": {"tools": {"format": '
        '{"argv": ["definitely-missing-exe-123", "{file}"]}}}}}',
        encoding="utf-8",
    )
    files = ProjectFiles(tmp_path)
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(ToolchainError) as excinfo:
        asyncio.run(run_tool(tmp_path, files, "format", language_id="python", file_rel="app.py"))
    assert "definitely-missing-exe-123" in excinfo.value.message
    assert "PATH" in excinfo.value.message  # LANG-003: actionable diagnostic
    assert excinfo.value.status_code == 422


def test_run_tool_executes_and_returns_output(tmp_path: Path) -> None:
    harness = tmp_path / ".ai-harness"
    harness.mkdir()
    (harness / "toolchains.json").write_text(
        '{"languages": {"python": {"tools": {"run": {"argv": ["'
        + sys.executable.replace("\\", "\\\\")
        + '", "{file}"]}}}}}',
        encoding="utf-8",
    )
    files = ProjectFiles(tmp_path)
    (tmp_path / "app.py").write_text("print('hello')\n", encoding="utf-8")
    result = asyncio.run(run_tool(tmp_path, files, "run", file_rel="app.py"))
    assert result.ok
    assert "hello" in result.result.stdout

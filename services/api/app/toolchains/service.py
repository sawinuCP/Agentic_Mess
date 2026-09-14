"""Toolchain availability probing and tool execution (FR-019, LANG-003..005)."""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.files.service import ProjectFiles
from app.runtime.runner import ExecResult, run_process
from app.toolchains.errors import ToolchainError
from app.toolchains.overrides import TOOL_LABELS, load_definition
from app.toolchains.registry import LanguageDefinition, definition_for_extension, get_definition

TOOL_TIMEOUT_SECONDS = 180.0
_WHICH_TTL_SECONDS = 60.0
_which_cache: dict[str, tuple[bool, float]] = {}


def which_cached(executable: str) -> bool:
    """Path probe with a small TTL so views stay fast without lying about state."""
    now = time.monotonic()
    cached = _which_cache.get(executable)
    if cached and now - cached[1] < _WHICH_TTL_SECONDS:
        return cached[0]
    found = shutil.which(executable) is not None
    _which_cache[executable] = (found, now)
    return found


@dataclass(slots=True)
class ToolRunResult:
    language: str
    tool: str
    command: list[str]
    result: ExecResult
    diagnostics: list[str]
    file_content: str | None = None

    @property
    def exit_code(self) -> int | None:
        return self.result.exit_code

    @property
    def ok(self) -> bool:
        return self.result.exit_code == 0 and not self.result.timed_out


def availability_for(definition: LanguageDefinition) -> dict[str, dict[str, Any]]:
    """Per-tool availability: executable probed on PATH (LANG-001 metadata)."""
    out: dict[str, dict[str, Any]] = {}
    for tool, spec in sorted(definition.tools.items()):
        exe = spec.argv[0]
        found = which_cached(exe)
        out[tool] = {
            "executable": exe,
            "available": found,
            "argv": list(spec.argv),
            "in_place": spec.in_place,
        }
    return out


def _substitute(argv: tuple[str, ...], *, file_rel: str | None, root: Path) -> list[str]:
    file_placeholders = ("{file}", "{file_abs}", "{file_stem}", "{dir}")
    if file_rel is None and any(p in token for token in argv for p in file_placeholders):
        raise ToolchainError(
            "This tool command references a target file — select a file and retry", 422
        )
    file_abs = str(root / file_rel) if file_rel else ""
    directory = str((root / file_rel).parent.relative_to(root)) if file_rel else "."
    if directory in ("", "."):
        directory = "."
    stem = Path(file_rel).stem if file_rel else ""
    mapping = {
        "{file}": file_rel or "",
        "{file_abs}": file_abs,
        "{dir}": directory,
        "{file_stem}": stem,
    }
    resolved: list[str] = []
    for token in argv:
        for placeholder, value in mapping.items():
            token = token.replace(placeholder, value)
        if "{" in token and "}" in token:
            raise ToolchainError(f"Unknown command placeholder in: '{token}'", 422)
        resolved.append(token)
    return resolved


async def run_tool(
    root: Path,
    files: ProjectFiles,
    tool: str,
    *,
    language_id: str | None = None,
    file_rel: str | None = None,
) -> ToolRunResult:
    """Resolve the tool command for a project and execute it at the project root."""
    if tool not in TOOL_LABELS:
        raise ToolchainError(f"Unknown tool: {tool!r} (known: {sorted(TOOL_LABELS)})", 422)

    if language_id is None:
        if not file_rel:
            raise ToolchainError("A file path is required when no language is given", 422)
        ext = Path(file_rel).suffix
        definition = definition_for_extension(ext)
        if definition is None:
            raise ToolchainError(
                f"No toolchain registered for extension '{ext}' ({file_rel}). "
                f"Register it in {root}/.ai-harness/toolchains.json or add a language "
                f"definition to the registry.",
                422,
            )
    else:
        definition = get_definition(language_id)

    definition, diagnostics = load_definition(definition.id, root)
    spec = definition.tools.get(tool)
    if spec is None:
        raise ToolchainError(
            f"{TOOL_LABELS[tool]} for {definition.name} is not configured. Add it via "
            f'{OVERRIDE_HINT(root)} ("languages.{definition.id}.tools.{tool}").',
            422,
        )

    if file_rel is not None:
        files.resolve(file_rel, must_exist=True)  # validates existence + containment
    argv = _substitute(spec.argv, file_rel=file_rel, root=root)
    executable = argv[0]
    if not which_cached(executable):
        raise ToolchainError(
            f"{TOOL_LABELS[tool]} for {definition.name} requires '{executable}', which was not "
            f"found on PATH. Install it (e.g. '{executable}') or override the command via "
            f"{OVERRIDE_HINT(root)}.",
            422,
        )

    result = await run_process(argv, cwd=root, timeout_seconds=TOOL_TIMEOUT_SECONDS)
    file_content: str | None = None
    if spec.in_place and file_rel and result.exit_code == 0 and not result.timed_out:
        file_content = files.read(file_rel).content
    return ToolRunResult(
        language=definition.id,
        tool=tool,
        command=argv,
        result=result,
        diagnostics=diagnostics,
        file_content=file_content,
    )


def OVERRIDE_HINT(root: Path) -> str:
    return str(root / ".ai-harness" / "toolchains.json")

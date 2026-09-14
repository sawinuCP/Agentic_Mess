"""Project-level toolchain overrides merged over the builtin registry (FR-029)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from app.toolchains.errors import ToolchainError
from app.toolchains.registry import LanguageDefinition, ToolSpec, get_definition

OVERRIDE_REL = ".ai-harness/toolchains.json"
TOOL_NAMES = ("format", "lint", "test", "run", "build")
TOOL_LABELS = {
    "format": "Formatter",
    "lint": "Linter",
    "test": "Test runner",
    "run": "Runner",
    "build": "Build system",
}


def load_definition(language_id: str, root: Path) -> tuple[LanguageDefinition, list[str]]:
    """Base definition merged with project overrides; returns (definition, diagnostics)."""
    definition = get_definition(language_id)
    override_path = root / OVERRIDE_REL
    if not override_path.is_file():
        return definition, []
    try:
        data = json.loads(override_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ToolchainError(
            f"Project toolchain override file is invalid ({OVERRIDE_REL}): {exc}", 422
        ) from None
    languages = data.get("languages") if isinstance(data, dict) else None
    if not isinstance(languages, dict):
        raise ToolchainError(f'{OVERRIDE_REL} must contain {{"languages": {{...}}}}', 422)
    diagnostics: list[str] = []
    entry = languages.get(language_id)
    if entry is None:
        return definition, diagnostics
    if not isinstance(entry, dict):
        raise ToolchainError(
            f"{OVERRIDE_REL}: language '{language_id}' entry must be an object", 422
        )
    tools = entry.get("tools", {})
    if not isinstance(tools, dict):
        raise ToolchainError(f"{OVERRIDE_REL}: 'tools' for '{language_id}' must be an object", 422)
    merged = dict(definition.tools)
    for tool_name, spec in tools.items():
        if tool_name not in TOOL_NAMES:
            diagnostics.append(f"Ignored unknown tool '{tool_name}' for '{language_id}'")
            continue
        if not isinstance(spec, dict) or not isinstance(spec.get("argv"), list) or not spec["argv"]:
            raise ToolchainError(
                f"{OVERRIDE_REL}: '{language_id}.{tool_name}' needs a non-empty 'argv' list", 422
            )
        merged[tool_name] = ToolSpec(
            argv=tuple(str(a) for a in spec["argv"]),
            in_place=bool(spec.get("in_place", False)),
        )
    return replace(definition, tools=merged), diagnostics

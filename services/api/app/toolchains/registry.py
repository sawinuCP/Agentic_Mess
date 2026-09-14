"""Data-driven language/toolchain registry.

Languages are configuration, not code branches: each ``LanguageDefinition``
declares extensions, manifest files and tool commands. Adding a language means
adding a definition here (or a project override file) — never new service logic
(FR-029). Project overrides live in ``<root>/.ai-harness/toolchains.json`` and
are merged by ``overrides.load_definition``.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.toolchains.errors import ToolchainError


@dataclass(frozen=True)
class ToolSpec:
    argv: tuple[str, ...]
    in_place: bool = False  # formatter rewrites the target file on disk


@dataclass(frozen=True)
class LanguageDefinition:
    id: str
    name: str
    extensions: frozenset[str]
    manifests: tuple[str, ...]  # exact names or fnmatch globs (e.g. "*.csproj")
    monaco_language: str
    tools: dict[str, ToolSpec]


def _t(*argv: str, in_place: bool = False) -> ToolSpec:
    return ToolSpec(argv=tuple(argv), in_place=in_place)


BUILTIN_LANGUAGES: dict[str, LanguageDefinition] = {
    "python": LanguageDefinition(
        id="python",
        name="Python",
        extensions=frozenset({".py", ".pyw"}),
        manifests=("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg", "Pipfile"),
        monaco_language="python",
        tools={
            "format": _t("black", "{file}", in_place=True),
            "lint": _t("ruff", "check", "{file}"),
            "test": _t("pytest", "-q"),
            "run": _t("python", "{file}"),
        },
    ),
    "javascript": LanguageDefinition(
        id="javascript",
        name="JavaScript",
        extensions=frozenset({".js", ".jsx", ".mjs", ".cjs"}),
        manifests=("package.json",),
        monaco_language="javascript",
        tools={
            "format": _t("npx", "--yes", "prettier", "--write", "{file}", in_place=True),
            "lint": _t("npx", "--yes", "eslint", "{file}"),
            "test": _t("npm", "test", "--silent"),
            "run": _t("node", "{file}"),
        },
    ),
    "typescript": LanguageDefinition(
        id="typescript",
        name="TypeScript",
        extensions=frozenset({".ts", ".tsx", ".mts", ".cts"}),
        manifests=("tsconfig.json",),
        monaco_language="typescript",
        tools={
            "format": _t("npx", "--yes", "prettier", "--write", "{file}", in_place=True),
            "lint": _t("npx", "--yes", "eslint", "{file}"),
            "test": _t("npm", "test", "--silent"),
            "run": _t("npx", "--yes", "tsx", "{file}"),
        },
    ),
    "go": LanguageDefinition(
        id="go",
        name="Go",
        extensions=frozenset({".go"}),
        manifests=("go.mod",),
        monaco_language="go",
        tools={
            "format": _t("gofmt", "-w", "{file}", in_place=True),
            "lint": _t("go", "vet", "{dir}"),
            "test": _t("go", "test", "./..."),
            "run": _t("go", "run", "{file}"),
            "build": _t("go", "build", "./..."),
        },
    ),
    "rust": LanguageDefinition(
        id="rust",
        name="Rust",
        extensions=frozenset({".rs"}),
        manifests=("Cargo.toml",),
        monaco_language="rust",
        tools={
            "format": _t("rustfmt", "{file}", in_place=True),
            "lint": _t("cargo", "check"),
            "test": _t("cargo", "test"),
            "run": _t("cargo", "run"),
            "build": _t("cargo", "build"),
        },
    ),
    "csharp": LanguageDefinition(
        id="csharp",
        name="C#",
        extensions=frozenset({".cs"}),
        manifests=("*.csproj", "*.sln"),
        monaco_language="csharp",
        tools={
            "format": _t("dotnet", "format", "{dir}"),
            "lint": _t("dotnet", "build", "--no-restore", "{dir}"),
            "test": _t("dotnet", "test"),
            "run": _t("dotnet", "run"),
            "build": _t("dotnet", "build"),
        },
    ),
}

_EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ext: lang_id for lang_id, defn in BUILTIN_LANGUAGES.items() for ext in defn.extensions
}


def get_definition(language_id: str) -> LanguageDefinition:
    try:
        return BUILTIN_LANGUAGES[language_id]
    except KeyError:
        raise ToolchainError(f"Unknown language: {language_id!r}", 404) from None


def definition_for_extension(ext: str) -> LanguageDefinition | None:
    language_id = _EXTENSION_TO_LANGUAGE.get(ext.lower())
    return BUILTIN_LANGUAGES.get(language_id) if language_id else None

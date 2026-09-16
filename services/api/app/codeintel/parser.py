"""Symbol extraction: stdlib ``ast`` for Python, tree-sitter for the other languages.

Layered per ARCHITECTURE §8 — structural parsing first. Engines per language:
``ast`` (Python, exact), ``tree-sitter`` (javascript/typescript/go/rust/c-sharp when
the grammar package is importable), and a documented **regex fallback** so the
index still works on machines without grammars. Line numbers are 1-based inclusive.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass

SIGNATURE_MAX = 200
DOC_MAX = 200


@dataclass(frozen=True, slots=True)
class SymbolSpan:
    name: str
    kind: str  # class|function|method|interface|struct|enum|trait|impl|type
    start_line: int
    end_line: int
    signature: str
    parent: str = ""
    doc: str = ""


LANGUAGE_BY_SUFFIX: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".cs": "csharp",
}

SUPPORTED_LANGUAGES = ("python", "javascript", "typescript", "go", "rust", "csharp")


def detect_language(path: str) -> str | None:
    suffix = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return LANGUAGE_BY_SUFFIX.get(f".{suffix}")


def _first_line(source_lines: list[str], line_no: int) -> str:
    if 1 <= line_no <= len(source_lines):
        return source_lines[line_no - 1].strip()[:SIGNATURE_MAX]
    return ""


# --- Python (stdlib ast — exact) -------------------------------------------------


def _python_symbols(source: str) -> list[SymbolSpan]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return _regex_symbols(source, "python")
    source_lines = source.splitlines()
    spans: list[SymbolSpan] = []
    classes: list[str] = []  # enclosing class names (innermost last)

    def _visit(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = (
                "class" if isinstance(node, ast.ClassDef) else ("method" if classes else "function")
            )
            docstring = ast.get_docstring(node) or ""
            spans.append(
                SymbolSpan(
                    name=node.name,
                    kind=kind,
                    start_line=node.lineno,
                    end_line=node.end_lineno or node.lineno,
                    signature=_first_line(source_lines, node.lineno),
                    parent=classes[-1] if (classes and kind == "method") else "",
                    doc=docstring.splitlines()[0][:DOC_MAX] if docstring else "",
                )
            )
            if isinstance(node, ast.ClassDef):
                classes.append(node.name)
            for child in ast.iter_child_nodes(node):
                _visit(child)
            if isinstance(node, ast.ClassDef):
                classes.pop()
            return
        for child in ast.iter_child_nodes(node):
            _visit(child)

    _visit(tree)
    return spans


# --- tree-sitter (grammars for javascript/typescript/go/rust/c-sharp) -------------

_NODE_KINDS: dict[str, dict[str, str]] = {
    "common": {
        "class_declaration": "class",
        "function_declaration": "function",
        "method_definition": "method",
        "interface_declaration": "interface",
        "function_definition": "function",
        "class_definition": "class",
        "function_item": "function",
        "method_declaration": "method",
        "struct_item": "struct",
        "enum_item": "enum",
        "trait_item": "trait",
        "impl_item": "impl",
        "struct_declaration": "struct",
        "enum_declaration": "enum",
        "type_spec": "type",  # go: refined to struct/interface by child node types
    }
}

_LANGUAGE_PACKAGES: dict[str, tuple[str, str]] = {
    # language -> (module, language-factory attribute)
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "go": ("tree_sitter_go", "language"),
    "rust": ("tree_sitter_rust", "language"),
    "csharp": ("tree_sitter_c_sharp", "language"),
}


def _tree_sitter_language(language: str):  # type: ignore[no-untyped-def]
    import importlib  # noqa: PLC0415 — grammars are optional at import time

    module_name, factory = _LANGUAGE_PACKAGES[language]
    module = importlib.import_module(module_name)
    from tree_sitter import Language  # noqa: PLC0415

    return Language(getattr(module, factory)())


def _tree_sitter_symbols(source: str, language: str) -> list[SymbolSpan]:
    from tree_sitter import Parser  # noqa: PLC0415

    parser = Parser(_tree_sitter_language(language))
    tree = parser.parse(source.encode("utf-8"))
    node_kinds = _NODE_KINDS["common"]
    source_lines = source.splitlines()
    spans: list[SymbolSpan] = []
    stack: list[str] = []  # names of enclosing symbols (innermost last)

    def _visit(node) -> None:  # type: ignore[no-untyped-def]
        kind = node_kinds.get(node.type)
        if node.type == "type_spec":
            child_types = {child.type for child in node.children}
            kind = (
                "interface"
                if "interface_type" in child_types
                else ("struct" if "struct_type" in child_types else "type")
            )
        name_node = node.child_by_field_name("name")
        name = ""
        if name_node is not None and name_node.text:
            name = name_node.text.decode("utf-8", errors="replace")
        if kind and name:
            start = node.start_point[0] + 1
            spans.append(
                SymbolSpan(
                    name=name,
                    kind=kind,
                    start_line=start,
                    end_line=node.end_point[0] + 1,
                    signature=_first_line(source_lines, start),
                    parent=stack[-1] if (stack and kind == "method") else "",
                )
            )
        if kind and name:
            stack.append(name)
        for child in node.children:
            _visit(child)
        if kind and name:
            stack.pop()

    _visit(tree.root_node)
    return spans


# --- Regex fallback (documented heuristics, used when a grammar is unavailable) ---


_REGEX_PATTERNS: dict[str, tuple[str, ...]] = {
    "python": (
        r"^(\s*)(?:async\s+)?def\s+(?P<name>[A-Za-z_]\w*)",
        r"^(\s*)class\s+(?P<name>[A-Za-z_]\w*)",
    ),
    "javascript": (
        r"^\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s+(?P<name>[A-Za-z_$][\w$]*)",
        r"^\s*(?:export\s+default\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)",
    ),
    "typescript": (
        r"^\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s+(?P<name>[A-Za-z_$][\w$]*)",
        r"^\s*(?:export\s+default\s+)?(?:abstract\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)",
        r"^\s*(?:export\s+)?interface\s+(?P<name>[A-Za-z_$][\w$]*)",
    ),
    "go": (
        r"^func\s+(?:\([^)]+\)\s*)?(?P<name>[A-Za-z_]\w*)",
        r"^type\s+(?P<name>[A-Za-z_]\w*)\s+(struct|interface)\b",
    ),
    "rust": (
        r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+(?P<name>[A-Za-z_]\w*)",
        r"^\s*(?:pub\s+)?struct\s+(?P<name>[A-Za-z_]\w*)",
        r"^\s*(?:pub\s+)?enum\s+(?P<name>[A-Za-z_]\w*)",
        r"^\s*(?:pub\s+)?trait\s+(?P<name>[A-Za-z_]\w*)",
    ),
    "csharp": (
        r"^\s*(?:public|private|protected|internal)?\s*(?:sealed\s+|abstract\s+|static\s+)*"
        r"(?:class|interface|struct|enum)\s+(?P<name>[A-Za-z_]\w*)",
    ),
}


def _regex_kind(language: str, pattern: str, line: str) -> str:
    if "class\\s" in pattern or "class\\b" in pattern or "(?:class" in pattern:
        return "class"
    if "interface" in pattern:
        return "interface"
    if "struct" in pattern:
        return "struct"
    if "enum" in pattern:
        return "enum"
    if "trait" in pattern:
        return "trait"
    if language == "python":
        return "method" if line[:1] in (" ", "\t") else "function"
    if language in ("javascript", "typescript"):
        return "method" if line[:1] in (" ", "\t") else "function"
    if language == "go" and line.startswith((" ", "\t")):
        return "method"
    return "function"


def _regex_symbols(source: str, language: str) -> list[SymbolSpan]:
    patterns = _REGEX_PATTERNS.get(language, ())
    if not patterns:
        return []
    compiled = [re.compile(p) for p in patterns]
    spans: list[SymbolSpan] = []
    source_lines = source.splitlines()
    for line_no, line in enumerate(source_lines, start=1):
        for regex in compiled:
            match = regex.match(line)
            if match is None:
                continue
            name = match.group("name").strip()
            if not name:
                break
            spans.append(
                SymbolSpan(
                    name=name,
                    kind=_regex_kind(language, regex.pattern, line),
                    start_line=line_no,
                    end_line=line_no,
                    signature=line.strip()[:SIGNATURE_MAX],
                )
            )
            break
    return spans


# --- Public API --------------------------------------------------------------------


def engines() -> dict[str, str]:
    """Report which extraction engine each language uses (status endpoint)."""
    out: dict[str, str] = {}
    for language in SUPPORTED_LANGUAGES:
        if language == "python":
            out[language] = "ast"
        elif language in _LANGUAGE_PACKAGES:
            try:
                _tree_sitter_language(language)
                out[language] = "tree-sitter"
            except Exception:  # noqa: BLE001 — grammar import may fail on some wheels
                out[language] = "regex"
        else:
            out[language] = "regex"
    return out


def extract_symbols(source: str, language: str) -> list[SymbolSpan]:
    """Extract symbols from ``source`` using the best engine for ``language``."""
    if language == "python":
        return _python_symbols(source)
    if language in _LANGUAGE_PACKAGES:
        try:
            return _tree_sitter_symbols(source, language)
        except Exception:  # noqa: BLE001 — any grammar failure degrades to the fallback
            return _regex_symbols(source, language)
    return _regex_symbols(source, language)

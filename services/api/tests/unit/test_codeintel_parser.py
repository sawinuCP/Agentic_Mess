"""Code-intelligence parser tests: ast (python), tree-sitter (ts/go), regex fallback."""

from __future__ import annotations

from app.codeintel.parser import detect_language, engines, extract_symbols

PY_SOURCE = '''
import os

class Greeter:
    """Says hello."""

    def greet(self, name: str) -> str:
        return f"hi {name}"

async def top_level(x):
    pass
'''

TS_SOURCE = """
export class Foo {
  bar(): void {}
}

export function baz(): void {}

interface Qux {
  id: string;
}
"""

GO_SOURCE = """package main

type Server struct{}

func (s *Server) Start() {}

func main() {}
"""


def test_detect_language_by_suffix() -> None:
    assert detect_language("a/b/c.py") == "python"
    assert detect_language("x.ts") == "typescript"
    assert detect_language("y.go") == "go"
    assert detect_language("z.txt") is None


def test_python_extraction_via_ast() -> None:
    spans = extract_symbols(PY_SOURCE, "python")
    by_name = {s.name: s for s in spans}
    assert set(by_name) == {"Greeter", "greet", "top_level"}
    assert by_name["Greeter"].kind == "class"
    assert by_name["greet"].kind == "method"
    assert by_name["greet"].parent == "Greeter"
    assert by_name["top_level"].kind == "function"
    assert by_name["Greeter"].doc == "Says hello."
    assert by_name["greet"].signature.startswith("def greet")
    assert by_name["greet"].start_line == 7


def test_tree_sitter_extraction_for_typescript_and_go() -> None:
    engines_map = engines()
    assert engines_map["typescript"] == "tree-sitter"
    assert engines_map["go"] == "tree-sitter"

    ts = {s.name: s for s in extract_symbols(TS_SOURCE, "typescript")}
    assert ts["Foo"].kind == "class"
    assert ts["bar"].kind == "method" and ts["bar"].parent == "Foo"
    assert ts["baz"].kind == "function"
    assert ts["Qux"].kind == "interface"

    go = {s.name: s for s in extract_symbols(GO_SOURCE, "go")}
    assert go["Server"].kind == "struct"
    assert go["Start"].kind == "method"
    assert go["main"].kind == "function"


def test_regex_fallback_still_finds_python_and_go_symbols() -> None:
    from app.codeintel.parser import _regex_symbols

    py = {s.name: s for s in _regex_symbols(PY_SOURCE, "python")}
    assert {"Greeter", "greet", "top_level"} <= set(py)

    go = {s.name: s for s in _regex_symbols(GO_SOURCE, "go")}
    assert {"Server", "Start", "main"} <= set(go)


def test_broken_python_source_degrades_gracefully() -> None:
    spans = extract_symbols("def broken(:\n    pass", "python")
    assert any(s.name == "broken" for s in spans)  # regex fallback caught the def


def test_unknown_language_returns_empty() -> None:
    assert extract_symbols("anything", "cobol") == []

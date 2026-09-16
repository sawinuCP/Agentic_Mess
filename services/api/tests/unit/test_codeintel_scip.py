"""SCIP-JSON export shape (documented subset)."""

from __future__ import annotations

from typing import cast

from sqlalchemy.orm import Session

from app.codeintel.scip import _moniker, build_scip_index


class _FakeFile:
    def __init__(self, id: object, path: str, language: str) -> None:
        self.id = id
        self.path = path
        self.language = language


class _FakeSymbol:
    def __init__(
        self, file_id: object, name: str, kind: str, start: int, end: int, parent: str = ""
    ) -> None:
        self.file_id = file_id
        self.name = name
        self.kind = kind
        self.parent = parent
        self.start_line = start
        self.end_line = end


class _FakeDb:
    """Minimal double exposing the two ordered selects build_scip_index makes."""

    def __init__(self, files: list[_FakeFile], symbols: list[_FakeSymbol]) -> None:
        self._calls = 0
        self._files = files
        self._symbols = symbols

    def scalars(self, *_args: object, **_kwargs: object) -> _FakeDb:
        self._calls += 1
        return self

    def all(self) -> list:  # noqa: A003
        return self._files if self._calls == 1 else self._symbols


def test_moniker_follows_the_harness_scheme() -> None:
    assert (
        _moniker("python", "src/a.py", "greet", "method", "Greeter")
        == "python . src/a.py/Greeter#greet()."
    )
    assert _moniker("go", "main.go", "main", "function", "") == "go . main.go/main()."
    assert _moniker("python", "src/a.py", "Greeter", "class", "") == "python . src/a.py/Greeter."


def test_build_scip_index_shape() -> None:
    f1 = _FakeFile("f1", "src/greet.py", "python")
    db = cast(
        Session,
        _FakeDb(
            [f1],
            [
                _FakeSymbol("f1", "Greeter", "class", 3, 10),
                _FakeSymbol("f1", "greet", "method", 6, 7, parent="Greeter"),
            ],
        ),
    )
    doc = build_scip_index(
        db,
        project_root="C:/tmp/proj",
        project_name="proj",
        tool_name="ai-harness",
        tool_version="0.3.0",
        project_id="p1",
    )
    assert doc["metadata"]["toolInfo"]["name"] == "ai-harness"
    assert doc["metadata"]["projectRoot"] == "C:/tmp/proj"
    (document,) = doc["documents"]
    assert document["relativePath"] == "src/greet.py"
    assert document["language"] == "python"
    assert len(document["occurrences"]) == 2
    first = document["occurrences"][0]
    assert first["range"] == [2, 0, 9]  # zero-based SCIP ranges
    assert first["symbolRoles"] == 1  # definition
    assert any("Greeter#greet()." in s for s in document["symbols"])

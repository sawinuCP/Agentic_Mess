"""Terminal manager bookkeeping (fake PTY; real PTYs are covered by live smoke)."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.terminal.manager as manager_module
from app.terminal.manager import TerminalManager


class FakePty:
    def __init__(self) -> None:
        self.closed = False

    @property
    def isalive(self) -> bool:
        return not self.closed

    def close(self) -> None:
        self.closed = True


def test_create_list_close_cycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manager_module, "spawn_pty", lambda cwd, cols=100, rows=30: FakePty())
    manager = TerminalManager()

    session = manager.create(tmp_path)
    assert session.cwd == str(tmp_path)
    assert [s.id for s in manager.list_sessions()] == [session.id]

    assert manager.close(session.id) is True
    assert manager.close(session.id) is False  # already gone
    assert manager.list_sessions() == []


def test_session_limit_is_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(manager_module, "spawn_pty", lambda cwd, cols=100, rows=30: FakePty())
    monkeypatch.setattr(manager_module, "MAX_SESSIONS", 2)
    manager = TerminalManager()

    manager.create(tmp_path)
    manager.create(tmp_path)
    with pytest.raises(RuntimeError, match="limit"):
        manager.create(tmp_path)


def test_get_unknown_session_raises(tmp_path: Path) -> None:
    manager = TerminalManager()
    with pytest.raises(KeyError):
        manager.get("nope")

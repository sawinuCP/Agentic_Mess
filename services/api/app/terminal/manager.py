"""Terminal session manager: bounded, local, per-project shell sessions."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.terminal.backends import PtySession, spawn_pty

MAX_SESSIONS = 8


@dataclass(slots=True)
class ManagedSession:
    id: str
    cwd: str
    pty: PtySession
    output: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    clients: int = 0


class TerminalManager:
    def __init__(self) -> None:
        self._sessions: dict[str, ManagedSession] = {}

    def list_sessions(self) -> list[ManagedSession]:
        return list(self._sessions.values())

    def get(self, session_id: str) -> ManagedSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    def create(self, cwd: Path) -> ManagedSession:
        if len(self._sessions) >= MAX_SESSIONS:
            raise RuntimeError(
                f"Terminal session limit reached ({MAX_SESSIONS}); close one and retry"
            )
        pty = spawn_pty(str(cwd))
        session = ManagedSession(id=uuid.uuid4().hex, cwd=str(cwd), pty=pty)
        self._sessions[session.id] = session
        return session

    def close(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        session.pty.close()
        return True

    def close_all(self) -> None:
        for session_id in list(self._sessions):
            self.close(session_id)

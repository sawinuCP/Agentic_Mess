"""Terminal endpoints: bounded PTY sessions + WebSocket streaming (Phase 1).

Session lifetime is 1:1 with its WebSocket for now (documented limitation):
closing the panel/tab closes the shell. Sessions are bounded by MAX_SESSIONS.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.api.deps import get_project
from app.db.models import Project
from app.terminal.backends import pump_output
from app.terminal.manager import ManagedSession, TerminalManager

router = APIRouter(tags=["terminal"])


class SessionOut(BaseModel):
    id: str
    cwd: str


def _manager(request_or_ws: Request | WebSocket) -> TerminalManager:
    manager = getattr(request_or_ws.app.state, "terminals", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="Terminal subsystem unavailable")
    return manager


@router.post("/api/projects/{project_id}/terminal/sessions", response_model=SessionOut)
def create_session(request: Request, project: Project = Depends(get_project)) -> SessionOut:
    try:
        session = _manager(request).create(Path(project.root_path))
    except RuntimeError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from None
    return SessionOut(id=session.id, cwd=session.cwd)


@router.get("/api/terminal/sessions", response_model=list[SessionOut])
def list_sessions(request: Request) -> list[SessionOut]:
    return [
        SessionOut(id=s.id, cwd=s.cwd) for s in _manager(request).list_sessions() if s.pty.isalive
    ]


@router.delete("/api/terminal/sessions/{session_id}", status_code=204)
def close_session(session_id: str, request: Request) -> None:
    _manager(request).close(session_id)


async def _read_client(session: ManagedSession, websocket: WebSocket) -> None:
    """Relay client input/resize messages into the PTY until disconnect."""
    while True:
        raw = await websocket.receive_text()
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            continue
        kind = message.get("type")
        if kind == "input":
            data = str(message.get("data", ""))
            if data:
                await asyncio.to_thread(session.pty.write, data)
        elif kind == "resize":
            try:
                cols = int(message.get("cols", 100))
                rows = int(message.get("rows", 30))
            except (TypeError, ValueError):
                continue
            await asyncio.to_thread(session.pty.resize, cols, rows)


async def _write_server(session: ManagedSession, websocket: WebSocket) -> None:
    """Stream PTY output to the client until the shell exits."""
    while True:
        data = await session.output.get()
        await websocket.send_text(json.dumps({"type": "output", "data": data}))


@router.websocket("/api/ws/terminal/{session_id}")
async def terminal_socket(websocket: WebSocket, session_id: str) -> None:
    manager = websocket.app.state.terminals
    try:
        session = manager.get(session_id)
    except KeyError:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    session.clients += 1
    pump = asyncio.create_task(pump_output(session.pty, session.output))
    reader = asyncio.create_task(_read_client(session, websocket))
    writer = asyncio.create_task(_write_server(session, websocket))
    try:
        done, _pending = await asyncio.wait({reader, writer}, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            exc = task.exception()
            if exc is not None and not isinstance(exc, WebSocketDisconnect):
                await websocket.close(code=1011)
                return
    except WebSocketDisconnect:
        pass
    finally:
        session.clients -= 1
        for task in (pump, reader, writer):
            task.cancel()
        manager.close(session_id)

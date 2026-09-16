"""Minimal MCP stdio client (FR-021): newline-delimited JSON-RPC 2.0.

Implements the small slice of the Model Context Protocol the harness needs:
``initialize`` handshake → ``notifications/initialized`` → ``tools/list`` →
``tools/call`` → shutdown. One client wraps one server process; requests carry
ids with per-request timeouts; stderr is drained to the log. This is a
deliberately small, auditable client — not a general SDK.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

logger = logging.getLogger("harness.mcp")

PROTOCOL_VERSION = "2024-11-05"
_CLIENT_INFO = {"name": "ai-harness", "version": "0.3.0"}


class McpError(Exception):
    """MCP transport/protocol failure; routes map this to 503."""


class McpStdioClient:
    def __init__(
        self,
        name: str,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        request_timeout: float = 30.0,
    ) -> None:
        self.name = name
        self._command = command
        self._env = env
        self._timeout = request_timeout
        self._proc: asyncio.subprocess.Process | None = None
        self._pending: dict[Any, asyncio.Future[Any]] = {}
        self._reader_task: asyncio.Task[Any] | None = None
        self._server_info: dict[str, Any] = {}

    async def start(self) -> None:
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**({} if self._env is None else self._env)},
            )
        except FileNotFoundError as exc:
            raise McpError(f"MCP server '{self.name}' executable not found: {exc}") from None

        self._reader_task = asyncio.create_task(self._read_loop())
        result = await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": _CLIENT_INFO,
            },
        )
        self._server_info = result.get("serverInfo", {})
        await self._notify("notifications/initialized", {})

    async def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        try:
            while True:
                line = await self._proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("mcp_invalid_json server=%s", self.name)
                    continue
                future = self._pending.pop(message.get("id"), None)
                if future is not None and not future.done():
                    if "error" in message:
                        future.set_exception(McpError(f"MCP error: {message['error']}"))
                    else:
                        future.set_result(message.get("result", {}))
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001 — transport death fails all pending calls
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(McpError(f"MCP transport closed: {exc}"))
            self._pending.clear()

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._proc is None or self._proc.stdin is None:
            raise McpError(f"MCP server '{self.name}' is not running")
        request_id = uuid.uuid4().hex
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        self._proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()
        try:
            return await asyncio.wait_for(future, timeout=self._timeout)
        except TimeoutError:
            self._pending.pop(request_id, None)
            raise McpError(
                f"MCP request '{method}' timed out after {self._timeout}s on '{self.name}'"
            ) from None

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise McpError(f"MCP server '{self.name}' is not running")
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        self._proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()

    async def list_tools(self) -> list[dict[str, Any]]:
        result = await self._request("tools/list", {})
        return list(result.get("tools", []))

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._request("tools/call", {"name": name, "arguments": arguments})

    @property
    def server_info(self) -> dict[str, Any]:
        return self._server_info

    async def close(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except (ProcessLookupError, TimeoutError):
                if self._proc is not None and self._proc.returncode is None:
                    self._proc.kill()
            except Exception:  # noqa: BLE001 — shutdown must never raise
                pass
        if self._reader_task is not None:
            self._reader_task.cancel()
        self._proc = None
        self._reader_task = None

"""MCP registry (FR-021): config-driven servers, discovery, permission checks.

Servers come from a JSON config (``HARNESS_MCP_CONFIG``):
``{"servers": [{"name", "command", "args", "env", "allowed_tools"}]}`` where
``allowed_tools`` is ``"*"`` or a list of tool names. Authorization is checked
at the registry AND again against the harness gateway policy — permission
controls are independent of the model (spec §48).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.errors import DomainError
from app.mcp.protocol import McpError, McpStdioClient


@dataclass(frozen=True, slots=True)
class McpServerConfig:
    name: str
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)
    allowed_tools: tuple[str, ...] = ("*",)  # "*" = every tool on this server


@dataclass(frozen=True, slots=True)
class McpToolEntry:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def qualified_name(self) -> str:
        return f"mcp:{self.server}:{self.name}"


def load_config(config_path: str) -> list[McpServerConfig]:
    """Parse the MCP server config; missing file → no servers (fail-closed, no defaults)."""
    if not config_path:
        return []
    path = Path(config_path)
    if not path.is_file():
        raise DomainError(f"MCP config not found: {config_path}", 503)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DomainError(f"MCP config is not valid JSON: {exc}", 500) from None
    servers: list[McpServerConfig] = []
    for entry in raw.get("servers", []):
        command = [str(part) for part in entry.get("command", [])]
        if not entry.get("name") or not command:
            raise DomainError("MCP config entries need a name and a command", 500)
        allowed = entry.get("allowed_tools", "*")
        servers.append(
            McpServerConfig(
                name=str(entry["name"]),
                command=command,
                env={str(k): str(v) for k, v in (entry.get("env") or {}).items()},
                allowed_tools=("*",) if allowed == "*" else tuple(str(tool) for tool in allowed),
            )
        )
    return servers


def tool_allowed(server: McpServerConfig, tool_name: str) -> bool:
    return "*" in server.allowed_tools or tool_name in server.allowed_tools


async def discover_servers(
    servers: list[McpServerConfig], *, timeout: float
) -> list[dict[str, Any]]:
    """List each server's tools (spec §21 pipeline step 1: discovery)."""
    discovered: list[dict[str, Any]] = []
    for server in servers:
        client = McpStdioClient(
            server.name, server.command, env=server.env, request_timeout=timeout
        )
        try:
            await client.start()
            tools = await client.list_tools()
        except McpError as exc:
            discovered.append({"server": server.name, "error": str(exc), "tools": []})
            continue
        finally:
            await client.close()
        discovered.append(
            {
                "server": server.name,
                "serverInfo": client.server_info,
                "tools": [
                    {
                        "qualified_name": f"mcp:{server.name}:{tool.get('name', '')}",
                        "name": tool.get("name", ""),
                        "description": tool.get("description", ""),
                        "input_schema": tool.get("inputSchema", {}),
                        "allowed": tool_allowed(server, str(tool.get("name", ""))),
                    }
                    for tool in tools
                ],
            }
        )
    return discovered


def validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    """Minimal JSON-Schema check (spec §21: schema validation before invocation).

    Validates the subset the harness relies on: object type and required keys.
    Full json-schema validation is a deliberate non-goal here.
    """
    if schema.get("type") == "object":
        for required in schema.get("required", []):
            if required not in arguments:
                raise DomainError(f"MCP tool argument missing required key: {required}", 422)


async def call_tool(
    server: McpServerConfig,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any]:
    """Authorize → invoke → return the raw MCP result (normalization at the caller)."""
    if not tool_allowed(server, tool_name):
        raise DomainError(f"tool '{tool_name}' is not allowed on MCP server '{server.name}'", 403)
    client = McpStdioClient(server.name, server.command, env=server.env, request_timeout=timeout)
    try:
        await client.start()
        tools = await client.list_tools()
        schema = next(
            (tool.get("inputSchema", {}) for tool in tools if tool.get("name") == tool_name), {}
        )
        validate_arguments(schema, arguments)
        return await client.call_tool(tool_name, arguments)
    except McpError as exc:
        raise DomainError(str(exc), 503) from None
    finally:
        await client.close()

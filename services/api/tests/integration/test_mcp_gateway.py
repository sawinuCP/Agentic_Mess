"""MCP gateway integration (FR-021): discovery, authorization, invocation, audit.

Runs against the real fake MCP server (tests/mcp_echo_server.py) speaking the
newline-delimited JSON-RPC protocol over stdio — a genuine protocol round trip.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.mcp.protocol import McpStdioClient

pytestmark = pytest.mark.integration

SERVER_SCRIPT = Path(__file__).resolve().parent.parent / "mcp_echo_server.py"


@pytest.fixture()
def mcp_app(tmp_path: Path) -> Iterator[tuple[TestClient, Path]]:
    config = tmp_path / "mcp.json"
    config.write_text(
        json.dumps(
            {
                "servers": [
                    {
                        "name": "echo",
                        "command": [sys_executable(), str(SERVER_SCRIPT)],
                        "allowed_tools": ["echo"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        environment="test",
        readiness_timeout_seconds=2.0,
        mcp_enabled=True,
        mcp_config_path=str(config),
        mcp_timeout_seconds=30.0,
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client, config


def sys_executable() -> str:
    import sys  # noqa: PLC0415

    return sys.executable


def test_discovery_lists_tools_with_permission_flags(mcp_app: tuple) -> None:
    client, _config = mcp_app
    result = client.post("/api/mcp/discover")
    assert result.status_code == 200
    (server,) = result.json()["servers"]
    assert server["server"] == "echo"
    assert server["serverInfo"]["name"] == "echo-server"
    names = {tool["name"]: tool for tool in server["tools"]}
    assert set(names) == {"echo", "secret_env"}
    assert names["echo"]["allowed"] is True
    assert names["secret_env"]["allowed"] is False  # not in the allowlist


def test_call_round_trip_through_the_protocol(mcp_app: tuple) -> None:
    client, _config = mcp_app
    result = client.post(
        "/api/mcp/call",
        json={"server": "echo", "tool": "echo", "arguments": {"text": "harness"}},
    )
    assert result.status_code == 200
    body = result.json()
    assert body["content"][0]["text"] == "echo: harness"
    assert body["is_error"] is False


def test_call_denied_for_tools_outside_the_allowlist(mcp_app: tuple) -> None:
    client, _config = mcp_app
    result = client.post(
        "/api/mcp/call",
        json={"server": "echo", "tool": "secret_env", "arguments": {}},
    )
    assert result.status_code == 403
    assert "not allowed" in result.json()["detail"]


def test_call_validates_the_tool_schema(mcp_app: tuple) -> None:
    client, _config = mcp_app
    result = client.post(
        "/api/mcp/call",
        json={"server": "echo", "tool": "echo", "arguments": {}},  # missing required "text"
    )
    assert result.status_code == 422
    assert "required key" in result.json()["detail"]


def test_mcp_disabled_fails_closed(tmp_path: Path) -> None:
    app = create_app(Settings(environment="test", mcp_enabled=False))
    with TestClient(app) as client:
        result = client.post("/api/mcp/call", json={"server": "echo", "tool": "echo"})
        assert result.status_code == 503
        assert "disabled" in result.json()["detail"]


def test_protocol_client_round_trip_standalone() -> None:
    import asyncio  # noqa: PLC0415

    client = McpStdioClient("echo", [sys_executable(), str(SERVER_SCRIPT)], request_timeout=30.0)

    async def _flow() -> None:
        await client.start()
        tools = await client.list_tools()
        assert [tool["name"] for tool in tools] == ["echo", "secret_env"]
        result = await client.call_tool("echo", {"text": "direct"})
        assert result["content"][0]["text"] == "echo: direct"
        await client.close()

    asyncio.run(_flow())

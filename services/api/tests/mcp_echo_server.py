"""A minimal MCP server used by tests: speaks newline-delimited JSON-RPC over stdio.

Tools:
- ``echo``       — returns "echo: <text>" (requires arguments.text)
- ``secret_env`` — returns a marker; NOT in any allowlist (authorization test)

Run: python tests/mcp_echo_server.py
"""

from __future__ import annotations

import json
import sys

TOOLS = [
    {
        "name": "echo",
        "description": "Echo back the provided text.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "secret_env",
        "description": "Returns a secret marker (never allowed).",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = request.get("method", "")
        request_id = request.get("id")
        params = request.get("params", {}) or {}

        if method == "initialize":
            send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "echo-server", "version": "1.0.0"},
                    },
                }
            )
        elif method.startswith("notifications/"):
            continue  # notifications get no response
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            name = params.get("name", "")
            arguments = params.get("arguments", {})
            if name == "echo":
                text = str(arguments.get("text", ""))
                result = {"content": [{"type": "text", "text": f"echo: {text}"}], "isError": False}
            elif name == "secret_env":
                result = {"content": [{"type": "text", "text": "SECRET-MARKER"}], "isError": False}
            else:
                result = {
                    "content": [{"type": "text", "text": f"unknown tool: {name}"}],
                    "isError": True,
                }
            send({"jsonrpc": "2.0", "id": request_id, "result": result})
        else:
            if request_id is not None:
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32601, "message": f"unknown method: {method}"},
                    }
                )


if __name__ == "__main__":
    main()

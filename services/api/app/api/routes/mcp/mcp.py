"""MCP gateway endpoints (Phase 7, FR-021): discovery, tools, authorized invocation."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.errors import DomainError
from app.mcp import registry
from app.services.core.events import record_event

router = APIRouter(tags=["mcp"])


class CallIn(BaseModel):
    server: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


def _config(request: Request) -> list[registry.McpServerConfig]:
    settings = request.app.state.settings
    if not settings.mcp_enabled:
        raise DomainError(
            "MCP gateway is disabled (set HARNESS_MCP_ENABLED=true and HARNESS_MCP_CONFIG_PATH)",
            503,
        )
    return registry.load_config(settings.mcp_config_path)


@router.get("/api/mcp/status")
async def mcp_status(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    return {
        "enabled": settings.mcp_enabled,
        "config_path": settings.mcp_config_path,
        "timeout_seconds": settings.mcp_timeout_seconds,
    }


@router.post("/api/mcp/discover")
async def discover(request: Request) -> dict[str, Any]:
    """Discovery step of the MCP pipeline (spec §21): list each server's tools."""
    servers = _config(request)
    tools = await registry.discover_servers(servers, timeout=settings_timeout(request))
    return {"servers": tools}


def settings_timeout(request: Request) -> float:
    return request.app.state.settings.mcp_timeout_seconds


@router.post("/api/mcp/call")
async def call_tool(request: Request, body: CallIn) -> dict[str, Any]:
    """Authorization → schema validation → invocation → normalization (spec §21).

    The harness gateway policy runs on the qualified tool name + arguments, so
    deny/approval patterns apply to MCP tools exactly as to shell commands.
    Large raw results are stored as artifacts; the response stays compact.
    """
    servers = _config(request)
    server = next((s for s in servers if s.name == body.server), None)
    if server is None:
        raise DomainError(f"MCP server not configured: {body.server}", 404)

    raw = await registry.call_tool(
        server, body.tool, body.arguments, timeout=settings_timeout(request)
    )
    content = raw.get("content", [])
    serialized = json.dumps(raw, default=str)
    artifact_id: str | None = None
    if len(serialized) > 1024:
        store = request.app.state.artifacts
        blob = store.put(serialized.encode("utf-8"))

        def _persist() -> str:
            from app.db.models import Artifact  # noqa: PLC0415

            with request.app.state.session_factory() as session:
                artifact = Artifact(
                    project_id=None,
                    name=f"mcp-{body.server}-{body.tool}",
                    kind="mcp_result",
                    mime="application/json",
                    size=blob.size,
                    sha256=blob.sha256,
                    storage_path=blob.storage_path,
                )
                session.add(artifact)
                session.commit()
                return str(artifact.id)

        import asyncio  # noqa: PLC0415

        artifact_id = await asyncio.to_thread(_persist)

    await record_event(
        request.app.state.session_factory,
        "MCP_TOOL_CALLED",
        payload={
            "server": body.server,
            "tool": body.tool,
            "artifact_id": artifact_id,
            "is_error": bool(raw.get("isError", False)),
        },
    )
    return {
        "server": body.server,
        "tool": body.tool,
        "content": content,
        "is_error": bool(raw.get("isError", False)),
        "artifact_id": artifact_id,
    }

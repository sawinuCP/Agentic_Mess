"""MCP gateway routes (Phase 7, FR-021)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.mcp import mcp

routers: list[APIRouter] = [mcp.router]

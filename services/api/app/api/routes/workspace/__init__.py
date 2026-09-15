"""Workspace routes: projects, file editing/search, git, terminals, toolchains."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.workspace import files, git, projects, terminal, toolchains

routers: list[APIRouter] = [
    projects.router,
    files.router,
    git.router,
    terminal.router,
    toolchains.router,
]

"""Code-intelligence routes (Phase 5): index, symbols/retrieval/SCIP, model costs."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.intelligence import costs, index, symbols

routers: list[APIRouter] = [index.router, symbols.router, costs.router]

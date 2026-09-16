"""Browser debugging routes (Phase 7, FR-020)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.browser import browser

routers: list[APIRouter] = [browser.router]

"""Quality & oversight routes (Phase 8): oversight, reviews, gates."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes.quality import gates, oversight, reviews

routers: list[APIRouter] = [oversight.router, reviews.router, gates.router]

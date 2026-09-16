"""Browser session manager (Phase 7): lazy Playwright startup, bounded sessions.

Playwright's async API runs on the application event loop. The driver starts
lazily on the first session and shuts down with the app. Sessions are capped so
a bug cannot spawn unbounded browsers; availability is probed honestly — when
Playwright or its browsers are missing, the routes fail closed with an
actionable 503.
"""

from __future__ import annotations

import contextlib
import uuid
from typing import Any

from app.browser.session import BrowserSession
from app.core.errors import DomainError


class BrowserManager:
    def __init__(self, *, max_sessions: int = 5) -> None:
        self._max_sessions = max_sessions
        self._playwright: Any = None
        self._browser: Any = None
        self._sessions: dict[str, BrowserSession] = {}

    @staticmethod
    def available() -> bool:
        try:
            import playwright  # noqa: F401,PLC0415 — optional dependency probe
        except ImportError:
            return False
        return True

    async def _ensure_browser(self) -> Any:
        if self._browser is not None:
            return self._browser
        try:
            from playwright.async_api import async_playwright  # noqa: PLC0415
        except ImportError:
            raise DomainError("Playwright is not installed (pip install playwright)", 503) from None
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001 — missing browsers etc. surface as 503
            self._playwright = None
            self._browser = None
            raise DomainError(
                f"browser runtime unavailable (run: playwright install chromium): {exc}", 503
            ) from None
        return self._browser

    async def open_session(
        self, project_id: uuid.UUID, start_url: str | None = None
    ) -> BrowserSession:
        if len(self._sessions) >= self._max_sessions:
            raise DomainError(
                f"browser session limit reached ({self._max_sessions}); close a session first",
                409,
            )
        browser = await self._ensure_browser()
        session = await BrowserSession.open(project_id, browser, start_url)
        self._sessions[session.session_id] = session
        return session

    def get(self, session_id: str) -> BrowserSession:
        session = self._sessions.get(session_id)
        if session is None or session.closed:
            raise DomainError("Browser session not found", 404)
        return session

    async def close_session(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is not None:
            await session.close()

    async def close_all(self) -> None:
        for session in self._sessions.values():
            await session.close()
        self._sessions.clear()
        if self._browser is not None:
            with contextlib.suppress(Exception):  # shutdown must never raise
                await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            with contextlib.suppress(Exception):  # shutdown must never raise
                await self._playwright.stop()
            self._playwright = None

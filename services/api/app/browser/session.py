"""One Playwright browser session: navigation + console/network/screenshot capture.

Console messages and failed/slow-request signals are captured into bounded
buffers via page event handlers (spec §20: capture console errors, inspect
network failures). Screenshots and logs are handed to the caller for artifact
storage — raw evidence is durable, model-facing summaries stay compact.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any

MAX_CAPTURED = 500  # bounded buffers — a runaway page cannot exhaust memory


@dataclass(slots=True)
class ConsoleEntry:
    level: str
    text: str
    ts: float


@dataclass(slots=True)
class NetworkEntry:
    url: str
    method: str
    status: int | None  # None when the request failed before a response
    failure: str | None
    ts: float


@dataclass(slots=True)
class BrowserSession:
    session_id: str
    project_id: uuid.UUID
    playwright_browser: Any  # playwright async Browser
    context: Any
    page: Any
    created_at: float = field(default_factory=time.time)
    console: deque[ConsoleEntry] = field(default_factory=lambda: deque(maxlen=MAX_CAPTURED))
    network: deque[NetworkEntry] = field(default_factory=lambda: deque(maxlen=MAX_CAPTURED))
    closed: bool = False

    @classmethod
    async def open(
        cls, project_id: uuid.UUID, playwright_browser: Any, start_url: str | None
    ) -> BrowserSession:
        context = await playwright_browser.new_context()
        page = await context.new_page()
        session = cls(
            session_id=str(uuid.uuid4()),
            project_id=project_id,
            playwright_browser=playwright_browser,
            context=context,
            page=page,
        )
        page.on(
            "console",
            lambda msg: session.console.append(
                ConsoleEntry(level=msg.type, text=msg.text, ts=time.time())
            ),
        )
        page.on(
            "requestfailed",
            lambda req: session.network.append(
                NetworkEntry(
                    url=req.url,
                    method=req.method,
                    status=None,
                    failure=req.failure,
                    ts=time.time(),
                )
            ),
        )

        def _on_response(response: Any) -> None:
            if response.status >= 400:
                session.network.append(
                    NetworkEntry(
                        url=response.url,
                        method=response.request.method,
                        status=response.status,
                        failure=None,
                        ts=time.time(),
                    )
                )

        page.on("response", _on_response)
        if start_url:
            await page.goto(start_url, wait_until="load")
        return session

    async def navigate(self, url: str) -> dict[str, Any]:
        response = await self.page.goto(url, wait_until="load")
        return {
            "url": url,
            "status": response.status if response else None,
            "title": await self.title(),
        }

    async def title(self) -> str:
        return await self.page.title()

    async def screenshot(self, *, full_page: bool = False) -> bytes:
        return await self.page.screenshot(full_page=full_page)

    async def content(self) -> str:
        return await self.page.content()

    async def evaluate(self, expression: str) -> Any:
        return await self.page.evaluate(expression)

    def console_snapshot(self) -> list[dict[str, Any]]:
        return [
            {"level": entry.level, "text": entry.text, "ts": entry.ts} for entry in self.console
        ]

    def network_snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "url": entry.url,
                "method": entry.method,
                "status": entry.status,
                "failure": entry.failure,
                "ts": entry.ts,
            }
            for entry in self.network
        ]

    async def close(self) -> None:
        if not self.closed:
            self.closed = True
            try:
                await self.context.close()
            except Exception:  # noqa: BLE001 — closing must never raise
                pass

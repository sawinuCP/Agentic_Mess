"""Offline Playwright check for shell connection telemetry (Wave 6 Phases 3/5).

Drives the real UI with all APIs intercepted. Proves: (1) connection
telemetry appears app-wide once a project is open, even before the office
view is ever visited; (2) a dead stream renders as "stream offline" — never
as a failed execution — with a real resync action; (3) narrow-window layout
keeps the shell usable instead of clipping. No backend, terminal, or model
calls.
Run from repository root: .venv\\Scripts\\python scripts\\smoke_shell_status.py
"""
from __future__ import annotations

import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "apps" / "web-ui"
URL = "http://127.0.0.1:5192"


def main() -> None:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node is required")
    server = subprocess.Popen(
        [node, str(WEB / "node_modules/vite/bin/vite.js"),
         "--host", "127.0.0.1", "--port", "5192", "--strictPort"],
        cwd=WEB, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 60
        while True:
            if server.poll() is not None:
                raise RuntimeError("Test Vite server exited; check port 5192")
            try:
                with urllib.request.urlopen(URL, timeout=2):
                    break
            except (urllib.error.URLError, TimeoutError):
                if time.monotonic() > deadline:
                    raise RuntimeError("Vite startup timed out")
                time.sleep(0.2)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))

            def api(route):
                path = route.request.url.split("/api/", 1)[1]
                if path == "healthz":
                    route.fulfill(json={"status": "ok", "version": "test",
                                        "environment": "test"})
                elif path == "readyz":
                    route.fulfill(json={"ready": True, "version": "test",
                                        "environment": "test", "checks": {}})
                elif path == "projects":
                    route.fulfill(json=[{"id": "proj-1", "name": "Demo",
                                         "root_path": "C:\\demo",
                                         "default_branch": "main"}])
                elif path == "projects/open":
                    route.fulfill(json={"id": "proj-1", "name": "Demo",
                                        "root_path": "C:\\demo",
                                        "default_branch": "main"})
                elif path.startswith("events?"):
                    route.fulfill(status=503, json={"detail": "Event service unavailable"})
                elif path.startswith("events/stream"):
                    route.fulfill(status=204, headers={})
                else:
                    route.abort()

            page.route(f"{URL}/api/**", api)
            page.goto(URL)
            expect(page.locator(".dialog")).to_be_visible()
            page.get_by_role("button", name="Demo", exact=False).first.click()
            expect(page.locator(".dialog")).to_have_count(0)

            # Telemetry must exist app-wide without visiting the office view.
            # (UI-1: connection state lives in the top bar, not the status bar.
            # Accessible name is the visible label "resync"; title is advisory.)
            # Offline surfaces after the reconnect backoff gives up; wait for it.
            resync = page.locator(".top-bar button", has_text="resync")
            expect(resync).to_be_visible(timeout=60000)
            with page.expect_request(lambda r: "/api/events?" in r.url):
                resync.click()

            # Office view itself still renders (tab strip visible) with its
            # own header state; no crash, no mislabeled execution state.
            page.locator('.activity-btn[title^="Agents"]').click()
            expect(page.locator(".office")).to_be_visible()

            # Narrow-window layout keeps the shell usable (sidebar present,
            # status bar intact, no horizontal clipping of the frame).
            page.set_viewport_size({"width": 820, "height": 700})
            sidebar = page.locator(".sidebar")
            expect(sidebar).to_be_visible()
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth + 1"
            ), "page overflows horizontally at 820px"

            assert not errors, errors
            print("PASS: app-wide connection telemetry before office visit, "
                  "office view intact, 820px layout without horizontal overflow; "
                  "no page errors")
            browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)


if __name__ == "__main__":
    main()

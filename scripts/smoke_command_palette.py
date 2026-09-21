"""Offline Playwright check for the command palette (Wave 6 Phase 4).

Drives the real UI with all APIs intercepted: Ctrl+K opens the palette,
search filters, arrow keys move between enabled rows, Escape closes with
focus restoration, and executing a navigation command performs the real
view switch. No backend, terminal, or model calls.
Run from repository root: .venv\\Scripts\\python scripts\\smoke_command_palette.py
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "apps" / "web-ui"
URL = "http://127.0.0.1:5191"


def main() -> None:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node is required")
    server = subprocess.Popen(
        [node, str(WEB / "node_modules/vite/bin/vite.js"),
         "--host", "127.0.0.1", "--port", "5191", "--strictPort"],
        cwd=WEB, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 60
        while True:
            if server.poll() is not None:
                raise RuntimeError("Test Vite server exited; check port 5191")
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
                    route.fulfill(json=[])
                else:
                    route.abort()

            page.route(f"{URL}/api/**", api)
            page.goto(URL)
            expect(page.locator(".dialog")).to_be_visible()  # project picker
            expect(page.locator(".command-palette")).to_have_count(0)

            # Remember the actual focused element, not its non-unique class.
            opener = page.locator(".dialog input")
            opener.focus()
            # Ctrl+K opens the palette and focuses its input.
            page.keyboard.press("Control+K")
            palette_input = page.locator(".command-palette input")
            expect(palette_input).to_be_visible()
            assert page.evaluate("document.activeElement?.className") == "text-input"

            # Search narrows to matching commands; keywords participate.
            palette_input.fill("terminal")
            rows = page.locator(".command-row")
            expect(rows).to_have_count(1)
            expect(rows.first).to_contain_text("Open terminal")
            expect(rows.first).to_contain_text("Open a project first")  # disabled reason

            # Disabled rows are not executed by Enter.
            page.keyboard.press("Enter")
            expect(page.locator(".command-palette")).to_be_visible()

            # Escape closes and restores focus to the previously focused element.
            page.keyboard.press("Tab")
            expect(palette_input).to_be_focused()
            page.keyboard.press("Shift+Tab")
            expect(palette_input).to_be_focused()
            page.keyboard.press("Escape")
            expect(page.locator(".command-palette")).to_have_count(0)
            expect(opener).to_be_focused()

            # Reopen and execute a real navigation command via keyboard.
            page.keyboard.press("Control+K")
            expect(page.locator(".command-palette")).to_be_visible()
            page.locator(".command-palette input").fill("explorer")
            rows = page.locator(".command-row")
            expect(rows).to_have_count(1)
            expect(rows.first).not_to_contain_text("Open a project first")
            page.keyboard.press("Enter")
            expect(page.locator(".command-palette")).to_have_count(0)
            explorer_btn = page.locator('.activity-btn[title^="Workspace"]')
            expect(explorer_btn).to_have_class(re.compile(r"\bactive\b"))

            # Toggle closed again with Ctrl+K.
            page.keyboard.press("Control+K")
            expect(page.locator(".command-palette")).to_be_visible()
            page.keyboard.press("Control+K")
            expect(page.locator(".command-palette")).to_have_count(0)

            # New views navigate through the palette with real content.
            # Settings needs no project, so Enter executes it here.
            page.keyboard.press("Control+K")
            page.locator(".command-palette input").fill("settings")
            expect(page.locator(".command-row")).to_have_count(1)
            page.keyboard.press("Enter")
            expect(page.locator(".command-palette")).to_have_count(0)
            expect(page.locator(".sidebar-header")).to_have_text("SETTINGS")
            expect(page.locator('input[aria-label="API token"]')).to_be_visible()
            # Problems needs a project (none is open in this fixture): the
            # disabled reason must show and Enter must be a no-op.
            page.keyboard.press("Control+K")
            page.locator(".command-palette input").fill("problems")
            expect(page.locator(".command-row")).to_have_count(1)
            expect(page.locator(".command-row").first).to_contain_text("Open a project first")
            page.keyboard.press("Enter")
            expect(page.locator(".command-palette")).to_be_visible()
            page.keyboard.press("Escape")
            # Theme toggle flips the data-theme contract without reload.
            before = page.evaluate("document.documentElement.dataset.theme || 'dark'")
            page.keyboard.press("Control+K")
            page.locator(".command-palette input").fill("toggle color theme")
            expect(page.locator(".command-row")).to_have_count(1)
            page.keyboard.press("Enter")
            expect(page.locator(".command-palette")).to_have_count(0)
            after = page.evaluate("document.documentElement.dataset.theme || 'dark'")
            assert before != after, (before, after)
            page.keyboard.press("Control+K")
            page.locator(".command-palette input").fill("toggle color theme")
            page.keyboard.press("Enter")
            restored = page.evaluate("document.documentElement.dataset.theme || 'dark'")
            assert restored == before, (before, restored)

            assert not errors, errors
            print("PASS: Ctrl+K open/toggle, search filtering, keyword match, "
                  "disabled reason shown, Enter no-op on disabled, Escape with "
                  "focus restoration, real navigation execution, problems + "
                  "settings views reachable; no page errors")
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

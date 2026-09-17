"""Offline Playwright check for the Phase-2 design tokens (Wave 6).

Loads the real UI against intercepted APIs and asserts computed styles:
token-driven body/button styling, keyboard focus ring, and the reduced-motion
rule being present in the stylesheet. No backend, terminal, or model calls.
Run from repository root: .venv\\Scripts\\python scripts\\smoke_design_tokens.py
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
URL = "http://127.0.0.1:5190"


def main() -> None:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node is required")
    server = subprocess.Popen(
        [node, str(WEB / "node_modules/vite/bin/vite.js"),
         "--host", "127.0.0.1", "--port", "5190", "--strictPort"],
        cwd=WEB, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 60
        while True:
            if server.poll() is not None:
                raise RuntimeError("Test Vite server exited; check port 5190")
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

            # Tokens drive the base surface and type scale.
            body = page.locator("body")
            assert body.evaluate("el => getComputedStyle(el).fontSize") == "13px"
            assert body.evaluate("el => getComputedStyle(el).backgroundColor") == \
                "rgb(15, 17, 23)", "surface-app token not applied"

            # Button radius comes from --radius-md.
            open_button = page.get_by_role("button", name="Open", exact=True)
            expect(open_button).to_be_visible()
            assert open_button.evaluate("el => getComputedStyle(el).borderRadius") == "6px", \
                "radius-md token not applied"

            # Keyboard focus must be visible (focus-visible ring).
            page.keyboard.press("Tab")
            focused_visible = page.evaluate(
                "() => { const el = document.activeElement;"
                " return el ? el.matches(':focus-visible') &&"
                " getComputedStyle(el).outlineWidth === '2px' : false }",
            )
            assert focused_visible, "no visible focus ring on keyboard focus"

            # Reduced-motion opt-out must exist in the delivered stylesheet.
            has_reduced_motion = page.evaluate(
                "() => [...document.styleSheets].some(sheet => {"
                " try { return [...sheet.cssRules].some(rule =>"
                " rule.media && rule.media.mediaText.includes('prefers-reduced-motion')); }"
                " catch { return false } })",
            )
            assert has_reduced_motion, "prefers-reduced-motion rule missing"

            assert not errors, errors
            print("PASS: token-driven body/button styles, visible keyboard focus "
                  "ring, reduced-motion rule; no page errors")
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

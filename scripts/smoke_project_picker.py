"""Offline Playwright regression for project-picker submission (Wave 6).

Uses the existing Python Playwright environment and Vite; all API traffic is
intercepted. No backend, terminal process, or model provider is invoked.
Run from repository root: .venv\\Scripts\\python scripts\\smoke_project_picker.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "apps" / "web-ui"
URL = "http://127.0.0.1:5189"
RECENT = "C:\\regression\\recent-project"


def main() -> None:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node is required")
    server = subprocess.Popen(
        [node, str(WEB / "node_modules/vite/bin/vite.js"),
         "--host", "127.0.0.1", "--port", "5189", "--strictPort"],
        cwd=WEB, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 60
        while True:
            if server.poll() is not None:
                raise RuntimeError("Test Vite server exited; check port 5189")
            try:
                with urllib.request.urlopen(URL, timeout=2):
                    break
            except (urllib.error.URLError, TimeoutError):
                if time.monotonic() > deadline:
                    raise RuntimeError("Vite startup timed out")
                time.sleep(0.2)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                for initial, recent in [("", True), ("C:\\wrong-project", True),
                                        ("  C:\\typed-project  ", False)]:
                    page = browser.new_page(viewport={"width": 1280, "height": 800})
                    requests: list[str] = []
                    errors: list[str] = []
                    page.on("pageerror", lambda error: errors.append(str(error)))

                    def api(route):
                        path = route.request.url.split("/api/", 1)[1]
                        if path == "projects":
                            route.fulfill(json=[{"id": "recent", "name": "Recent project",
                                                 "root_path": RECENT, "default_branch": "main"}])
                        elif path == "projects/open":
                            requests.append(json.loads(route.request.post_data)["root_path"])
                            # Keep the dialog open to verify its existing failure/retry path.
                            route.fulfill(status=422, json={"detail": "Test directory unavailable"})
                        elif path == "healthz":
                            route.fulfill(json={"status": "ok", "version": "test",
                                                "environment": "test"})
                        else:
                            route.abort()

                    page.route(f"{URL}/api/**", api)
                    page.goto(URL)
                    field = page.locator(".dialog input")
                    expect(field).to_be_visible()
                    if initial:
                        field.fill(initial)
                    if recent:
                        page.get_by_role("button", name="Recent project", exact=False).click()
                    else:
                        page.get_by_role("button", name="Open", exact=True).click()
                    expect(page.get_by_text("Test directory unavailable")).to_be_visible()
                    assert requests == [RECENT if recent else initial.strip()], requests
                    expect(page.get_by_role("button", name="Open", exact=True)).to_be_enabled()
                    expect(page.get_by_role("button", name="Recent project", exact=False)).to_be_enabled()
                    assert not errors, errors
                    page.close()
                print("PASS: empty-input recent, stale-input recent, trimmed typed path; "
                      "failure feedback/re-enabled actions; no page errors (3 cases)")
            finally:
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

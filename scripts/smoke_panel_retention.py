"""Offline real-xterm retention/resize smoke. All API/PTY traffic is intercepted."""
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "apps/web-ui"
URL = "http://127.0.0.1:5193"


def main():
    server = subprocess.Popen([shutil.which("node"), str(WEB / "node_modules/vite/bin/vite.js"),
                               "--host", "127.0.0.1", "--port", "5193", "--strictPort"],
                              cwd=WEB, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(URL, timeout=1).close()
                break
            except OSError:
                time.sleep(.2)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            errors, sockets = [], []
            page.on("pageerror", lambda e: errors.append(e.stack or str(e)))
            def socket(ws):
                sockets.append(ws.url)
                ws.on_message(lambda message: None)
                ws.send(json.dumps({"type": "output", "data": "retained terminal output\r\n"}))
            page.route_web_socket("**/api/ws/terminal/**", socket)
            count = 0
            def api(route):
                nonlocal count
                path = route.request.url.split("/api/")[1]
                project = {"id": "p", "name": "Local", "root_path": "C:\\local", "default_branch": "main"}
                if path == "projects": route.fulfill(json=[project])
                elif path == "projects/open": route.fulfill(json=project)
                elif "terminal/sessions" in path:
                    count += 1
                    route.fulfill(json={"id": f"term-{count}", "cwd": "C:\\local"})
                elif "/tree?" in path: route.fulfill(json=[])
                elif path.endswith("toolchains"):
                    route.fulfill(json={"languages": [], "diagnostics": [], "override_file": False})
                elif path.endswith("git/status"):
                    route.fulfill(json={"branch": "main", "upstream": None, "ahead": 0, "behind": 0, "entries": []})
                elif path == "healthz": route.fulfill(json={"status": "ok", "version": "test", "environment": "test"})
                else: route.fulfill(status=503, json={"detail": "Unavailable in offline fixture"})
            page.route(f"{URL}/api/**", api)
            page.goto(URL)
            page.get_by_role("button", name="Local", exact=False).click()
            expect(page.locator(".terminal-session .xterm")).to_have_count(1)
            page.get_by_title("New terminal", exact=True).click()
            expect(page.locator(".terminal-session .xterm")).to_have_count(2)
            page.locator(".terminal-session .xterm").evaluate_all("els => window.retainedTerms = els")
            before = len(sockets)
            page.locator(".term-chip .link").first.click()
            page.get_by_role("tab", name="OUTPUT", exact=True).click()
            page.get_by_title("Hide panel", exact=True).click()
            expect(page.locator(".bottom-panel")).to_be_hidden()
            page.get_by_title("Toggle panel", exact=True).click()
            page.get_by_role("tab", name="TERMINAL", exact=True).click()
            expect(page.locator(".terminal-session:not([hidden]) .xterm")).to_be_visible()
            assert page.locator(".terminal-session .xterm").evaluate_all(
                "els => els.every((el, i) => el === window.retainedTerms[i])")
            assert len(sockets) == before, (before, sockets)
            handle = page.get_by_role("separator", name="Resize utility panel")
            handle.focus()
            old = int(handle.get_attribute("aria-valuenow"))
            page.keyboard.press("ArrowUp")
            expect(handle).to_have_attribute("aria-valuenow", str(old + 20))
            saved = page.evaluate("JSON.parse(localStorage.getItem('harness.layout.v1'))")
            assert saved["panelHeight"] == old + 20
            # Sidebar stays reachable at narrow widths and restores after collapse.
            sidebar = page.get_by_role("separator", name="Resize sidebar")
            sidebar.focus()
            old_width = int(sidebar.get_attribute("aria-valuenow"))
            page.keyboard.press("ArrowRight")
            expect(sidebar).to_have_attribute("aria-valuenow", str(old_width + 20))
            page.get_by_title("Toggle sidebar", exact=True).click()
            expect(page.locator(".sidebar-container")).to_be_hidden()
            page.get_by_title("Workspace", exact=False).click()
            expect(page.locator(".sidebar-container")).to_be_visible()
            page.set_viewport_size({"width": 640, "height": 800})
            expect(page.get_by_title("New file", exact=True)).to_be_visible()
            # Focus trap and restoration for a real Explorer dialog.
            opener = page.get_by_title("New file", exact=True)
            opener.click()
            field = page.get_by_role("textbox", name="New file", exact=True)
            expect(field).to_be_focused()
            page.keyboard.press("Shift+Tab")
            expect(page.get_by_role("button", name="Cancel", exact=True)).to_be_focused()
            page.keyboard.press("Tab")
            expect(field).to_be_focused()
            page.keyboard.press("Escape")
            expect(field).to_have_count(0)
            expect(opener).to_be_focused()
            assert not errors, errors
            print("PASS: xterm/socket retention; persisted resize; 640px sidebar navigation; dialog Tab/Escape/focus restoration")
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)

if __name__ == "__main__":
    main()

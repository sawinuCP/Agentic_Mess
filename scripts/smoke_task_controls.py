"""Real UI + HTTP adapter task controls; offline fixtures, zero model calls."""
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "apps/web-ui"
URL = "http://127.0.0.1:5194"


def main():
    server = subprocess.Popen([shutil.which("node"), str(WEB / "node_modules/vite/bin/vite.js"),
        "--host", "127.0.0.1", "--port", "5194", "--strictPort"], cwd=WEB,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError("Vite exited")
            try:
                urllib.request.urlopen(URL, timeout=1).close()
                break
            except OSError:
                time.sleep(.2)
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            errors, requests, held = [], [], []
            page.on("pageerror", lambda e: errors.append(e.stack or str(e)))
            page.on("dialog", lambda dialog: dialog.accept())
            decisions = []
            approvals = [{"id": "h", "task_id": "t", "status": "pending", "risk": "high",
                          "kind": "approval", "question": "Approve local change?", "choices": []}]
            task = {"id": "t", "project_id": "p", "requirement_id": None, "title": "Local task",
                    "request": "local test", "status": "pending", "priority": 1,
                    "depends_on": [], "attempts": []}
            def api(route):
                path = route.request.url.split("/api/", 1)[1]
                project = {"id": "p", "name": "Local", "root_path": "C:\\local", "default_branch": "main"}
                if path.endswith("hitl/h/decide"):
                    decisions.append(route.request.post_data_json)
                    held.append(route)
                elif path.startswith("hitl?"): route.fulfill(json=approvals)
                elif path.startswith("tasks/t/"):
                    requests.append((route.request.method, path))
                    held.append(route)
                elif path == "projects": route.fulfill(json=[project])
                elif path == "projects/open": route.fulfill(json=project)
                elif path.endswith("/tasks"): route.fulfill(json=[task])
                elif path.startswith("events/stream"):
                    route.fulfill(content_type="text/event-stream", body='data: {"kind":"GATEWAY_STATUS","state":"live"}\n\n')
                elif "traceability" in path: route.fulfill(json={"requirements": []})
                elif path == "healthz": route.fulfill(json={"status": "ok", "version": "test", "environment": "test"})
                elif "toolchains" in path: route.fulfill(json={"languages": [], "diagnostics": []})
                elif "terminal/sessions" in path: route.fulfill(status=503, json={"detail": "PTY disabled in fixture"})
                elif "git/status" in path: route.fulfill(json={"branch": "main", "entries": []})
                else: route.fulfill(json=[])
            page.route(f"{URL}/api/**", api)
            page.goto(URL)
            page.get_by_role("button", name="Local", exact=False).click()
            page.get_by_title("Engineering office", exact=False).click()
            start = page.get_by_role("button", name="Start execution: Local task", exact=True)
            pause = page.get_by_role("button", name="Request pause: Local task", exact=True)
            resume = page.get_by_role("button", name="Send resume signal: Local task", exact=True)
            expect(start).to_be_enabled()
            expect(pause).to_be_disabled()
            start.click()
            expect(start).to_have_text("Sending…")
            expect(start).to_be_disabled()
            page.wait_for_function("true")
            assert requests == [("POST", "tasks/t/execute")], requests
            task["status"] = "running"
            held.pop(0).fulfill(json={"started": True, "workflow_id": "local"})
            expect(pause).to_be_enabled()
            expect(start).to_be_disabled()
            pause.click()
            expect(resume).to_be_disabled()
            held.pop(0).fulfill(status=204)
            expect(page.get_by_text("pause signal sent.", exact=False)).to_be_visible()
            expect(resume).to_be_enabled()
            resume.click()
            expect(resume).to_have_text("Sending…")
            held.pop(0).fulfill(status=403, json={"detail": "Access refused"})
            expect(page.get_by_role("alert").filter(has_text="Permission denied")).to_be_visible()
            expect(resume).to_be_enabled()
            resume.click()
            expect(resume).to_have_text("Sending…")
            held.pop(0).fulfill(status=204)
            expect(page.get_by_text("resume signal sent.", exact=False)).to_be_visible()
            # Same safe adapter is reachable through the command palette.
            page.keyboard.press("Control+K")
            search = page.get_by_role("combobox", name="Search commands")
            search.fill("Request pause: Local task")
            page.keyboard.press("Enter")
            expect(page.get_by_text("Running command…", exact=True)).to_be_visible()
            held.pop(0).fulfill(status=204)
            expect(search).to_have_count(0)
            assert requests == [("POST", "tasks/t/execute"), ("POST", "tasks/t/pause"),
                ("POST", "tasks/t/resume"), ("POST", "tasks/t/resume"), ("POST", "tasks/t/pause")], requests
            note = page.get_by_role("textbox", name="Approval note: Approve local change?")
            note.fill("Reviewed locally")
            approve = page.get_by_role("button", name="Approve", exact=True)
            reject = page.get_by_role("button", name="Reject", exact=True)
            approve.click()
            expect(approve).to_be_disabled()
            expect(reject).to_be_disabled()
            held.pop(0).fulfill(status=403, json={"detail": "Approval access refused"})
            expect(page.get_by_role("alert").filter(has_text="Approval access refused")).to_be_visible()
            expect(approve).to_be_enabled()
            reject.click()
            expect(reject).to_be_disabled()
            approvals.clear()
            held.pop(0).fulfill(json={"status": "rejected"})
            expect(note).to_have_count(0)
            assert [d["decision"] for d in decisions] == ["approved", "rejected"]
            assert all(d["note"] == "Reviewed locally" for d in decisions)
            assert not errors, errors
            print("PASS: TeamTab + palette task adapters; pending/403/retry; approval note, lockout, failure and reject refresh; no page errors")
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)

if __name__ == "__main__":
    main()

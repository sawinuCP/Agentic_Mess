"""Command Center check (Wave 10): deterministic routing, zero model calls.

Drives the real UI with all APIs intercepted (including the model-backed
review endpoint, which returns a canned verdict — no paid calls). Proves:
intent classification to plan preview, editor-selection context, scoped
implementation dispatch with live handoff, test run, model-backed review
with confirmation, research search/fetch with provenance, cost/unknown/
unsupported handling, palette entries, and no page errors.
Run from repository root: .venv\\Scripts\\python scripts\\smoke_command_center.py
"""
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "apps" / "web-ui"
URL = "http://127.0.0.1:5200"


def main():
    server = subprocess.Popen([shutil.which("node"), str(WEB / "node_modules/vite/bin/vite.js"),
        "--host", "127.0.0.1", "--port", "5200", "--strictPort"], cwd=WEB,
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
            page = browser.new_page(viewport={"width": 1600, "height": 900})
            errors = []
            page.on("pageerror", lambda e: errors.append(e.stack or str(e)))
            page.on("dialog", lambda dialog: dialog.accept())
            project = {"id": "p", "name": "Local", "root_path": "C:\\local", "default_branch": "main"}
            agents = [{"id": "a1", "project_id": "p", "name": "Backend", "role": "backend",
                       "model": None, "capabilities": [], "state": "running"}]
            tasks = [
                {"id": "t1", "project_id": "p", "requirement_id": "r1", "title": "Fix flaky test",
                 "request": "Stabilize", "status": "failed", "priority": 1, "depends_on": [],
                 "attempts": [{"attempt_number": 1, "agent_id": "a1", "outcome": "failed",
                               "failure_class": "TOOL_FAILURE", "failure_detail": "exit 1",
                               "evidence_artifact_ids": []}]},
                {"id": "t2", "project_id": "p", "requirement_id": None, "title": "Write docs",
                 "request": "Document", "status": "pending", "priority": 2, "depends_on": [],
                 "attempts": []},
            ]
            traceability = {"project_id": "p", "generated_at": "2026-09-18T10:00:00Z",
                            "requirements": [{"id": "r1", "title": "OAuth login", "priority": "must",
                                              "status": "UNKNOWN", "implemented": True, "task_ids": ["t1"],
                                              "criteria": [], "evidence_artifact_ids": [],
                                              "validation_evidence_artifact_ids": []}],
                            "coverage": {"total": 1, "verified": 0, "failed": 0, "unknown": 1},
                            "orphan_task_ids": [], "scope_drift": False}
            toolchains = {"languages": [{"id": "py", "name": "Python", "monaco_language": "python",
                                          "manifests": [], "file_count": 1, "tools": ["test"],
                                          "availability": {}}],
                          "diagnostics": [], "override_file": False}
            posted = []

            def api(route):
                path = route.request.url.split("/api/", 1)[1].split("?")[0]
                method = route.request.method
                if path == "projects":
                    route.fulfill(json=[project])
                elif path == "projects/open":
                    route.fulfill(json=project)
                elif path.endswith("/agents"):
                    route.fulfill(json=agents)
                elif path.endswith("/tasks"):
                    if method == "POST":
                        body = route.request.post_data_json
                        posted.append(("tasks", body))
                        created = {"id": "t9", "project_id": "p",
                                   "requirement_id": body.get("requirement_id"), "title": body["title"],
                                   "request": body.get("request", ""), "status": "pending",
                                   "priority": 5, "depends_on": [], "attempts": []}
                        tasks.append(created)
                        route.fulfill(status=201, json=created)
                    else:
                        route.fulfill(json=tasks)
                elif path.startswith("hitl?"):
                    route.fulfill(json=[])
                elif path.startswith("events/stream"):
                    route.fulfill(content_type="text/event-stream",
                                  body='data: {"kind":"GATEWAY_STATUS","state":"live"}\n\n')
                elif path.startswith("events"):
                    route.fulfill(json=[])
                elif path.endswith("/requirements"):
                    route.fulfill(json=[])
                elif "traceability" in path:
                    route.fulfill(json=traceability)
                elif "/symbols" in path and "?" in route.request.url:
                    route.fulfill(json=[{"id": "s1", "path": "auth.py", "name": "authenticate",
                                         "kind": "function", "parent": None, "start_line": 1,
                                         "end_line": 5, "signature": "def authenticate()",
                                         "doc": None, "language": "python"}])
                elif "intelligence/retrieve" in path:
                    route.fulfill(json={"query": "q", "hits": [
                        {"path": "auth.py", "name": "authenticate", "kind": "function",
                         "start_line": 1, "end_line": 5, "signature": "def authenticate()",
                         "score": 0.9, "matched": "hybrid"}]})
                elif path.endswith("toolchains/run"):
                    posted.append(("run", route.request.post_data_json))
                    route.fulfill(json={"language": "Python", "tool": "test", "command": ["pytest", "-q"],
                                        "exit_code": 0, "timed_out": False, "truncated": False,
                                        "duration_ms": 12, "stdout": "1 passed", "stderr": "",
                                        "diagnostics": [], "file_content": None, "artifact_ids": []})
                elif "/reviews" in path:
                    posted.append(("review", route.request.post_data_json))
                    route.fulfill(json={"decision_id": "d1", "verdict": "approve",
                                        "rationale": "Looks good",
                                        "reviews": [], "findings": []})
                elif path.endswith("research/search"):
                    route.fulfill(json={"query": "q", "results": [
                        {"title": "OAuth guide", "url": "https://example.com/oauth",
                         "source": "duckduckgo"}]})
                elif path.endswith("research/fetch"):
                    posted.append(("fetch", route.request.post_data_json))
                    route.fulfill(json={"url": "https://example.com/oauth",
                                        "final_url": "https://example.com/oauth",
                                        "title": "OAuth guide", "fetched_at": "2026-09-18T10:00:00Z",
                                        "sha256": "cc", "excerpt": "Use short-lived tokens.",
                                        "artifact_id": "art9", "context_item_id": "ctx9",
                                        "confidence": 0.9})
                elif "intelligence/costs" in path:
                    route.fulfill(json={"invocations": 12, "total_tokens": 45000,
                                        "by_model": {"test:model": 45000},
                                        "by_role": {"reviewer": 45000}, "task_id": None,
                                        "budget_tokens_per_task": 100000})
                elif path == "healthz":
                    route.fulfill(json={"status": "ok", "version": "test", "environment": "test"})
                elif path == "diagnostics":
                    route.fulfill(json={"app": {"version": "test", "environment": "test",
                                                "python": "3.11", "platform": "win",
                                                "pid": 1, "uptime_seconds": 10},
                                        "database": {"status": "ok", "alembic_head": "h"},
                                        "counts": {}, "artifact_store": {"status": "ok", "detail": ""},
                                        "temp_dir": {"status": "ok", "detail": ""},
                                        "redis": {"status": "ok", "detail": ""},
                                        "nats": {"status": "ok", "detail": ""}, "config": {}})
                elif "toolchains" in path:
                    route.fulfill(json=toolchains)
                elif "terminal/sessions" in path:
                    route.fulfill(status=503, json={"detail": "PTY disabled"})
                elif "git/status" in path:
                    route.fulfill(json={"branch": "main", "upstream": None, "ahead": 0,
                                        "behind": 0, "entries": []})
                elif path.endswith("/tree"):
                    route.fulfill(json=[{"name": "auth.py", "path": "auth.py", "kind": "file",
                                         "size": 30, "has_children": False}])
                elif "/file" in path and "?" in route.request.url:
                    route.fulfill(json={"path": "auth.py", "content": "x = 1\ny = 2\n",
                                        "is_binary": False, "size": 12, "mtime_ms": 0})
                else:
                    route.fulfill(json=[])
            page.route(f"{URL}/api/**", api)
            page.goto(URL)
            page.get_by_role("button", name="Local", exact=False).click()
            page.get_by_role("button", name="Command Center", exact=True).click()

            # Header ledger + scoped implementation dispatch with live handoff.
            expect(page.get_by_text("12 model calls", exact=False)).to_be_visible()
            page.get_by_label("Command scope: requirement").select_option("r1")
            page.get_by_label("Engineering request").fill("Implement OAuth login")
            page.get_by_role("button", name="Ask", exact=True).click()
            expect(page.get_by_text("Implement: Implement OAuth login", exact=False)).to_be_visible()
            expect(page.get_by_text("Confirmation required", exact=False)).to_be_visible()
            page.get_by_role("button", name="Review & start", exact=True).click()
            expect(page.get_by_text("Task created: Implement OAuth login", exact=False)).to_be_visible()
            expect(page.get_by_text("Live status:", exact=False)).to_be_visible()
            assert ("tasks", posted[0][1]) and posted[0][1]["requirement_id"] == "r1", posted

            # Editor selection → palette → deterministic explanation.
            page.get_by_role("button", name="Explorer", exact=True).click()
            page.get_by_text("auth.py", exact=True).click()
            expect(page.locator(".tab-strip").get_by_text("auth.py", exact=False)).to_be_visible()
            page.locator(".monaco-editor textarea.inputarea").wait_for()
            expect(page.locator(".monaco-editor .view-lines")).to_be_visible()
            # Triple-click selects the whole first line regardless of cursor start.
            page.locator(".monaco-editor").click(position={"x": 100, "y": 20}, click_count=3)
            page.get_by_role("button", name="Command Center", exact=True).click()
            expect(page.locator(".cc-context").get_by_text("auth.py", exact=False).first).to_be_visible()
            # Note: Monaco swallows Ctrl+K as a chord prefix, so the palette
            # opens here via its activity button (documented limitation).
            page.get_by_role("button", name="Command palette", exact=True).click()
            search = page.get_by_role("combobox", name="Search commands")
            search.fill("Explain selection")
            expect(page.locator(".command-palette .command-row")).to_have_count(1)
            page.keyboard.press("Enter")
            expect(page.get_by_label("Engineering request")).to_have_value("Explain this")
            page.get_by_role("button", name="Ask", exact=True).click()
            page.get_by_role("button", name="Run", exact=True).click()
            expect(page.get_by_text("1 symbols", exact=False)).to_be_visible()

            # Test run with confirmation + result card.
            page.get_by_label("Engineering request").fill("Run the tests")
            page.get_by_role("button", name="Ask", exact=True).click()
            page.get_by_role("button", name="Review & start", exact=True).click()
            expect(page.get_by_text("Tests passed", exact=False)).to_be_visible()
            assert any(kind == "run" for kind, _ in posted), posted

            # Model-backed review is confirmed and cost-labeled.
            page.get_by_label("Command scope: requirement").select_option("")
            page.get_by_label("Command scope: task").select_option("t2")
            page.get_by_label("Engineering request").fill("Review this implementation")
            page.get_by_role("button", name="Ask", exact=True).click()
            page.get_by_role("button", name="Review & start", exact=True).click()
            expect(page.get_by_text("Reviewers: approve", exact=False)).to_be_visible()
            expect(page.get_by_text("Looks good", exact=False)).to_be_visible()
            assert any(kind == "review" for kind, _ in posted), posted

            # Research search + confirmed fetch with provenance.
            page.get_by_label("Engineering request").fill("What is the current best practice for OAuth?")
            page.get_by_role("button", name="Ask", exact=True).click()
            page.get_by_role("button", name="Review & start", exact=True).click()
            expect(page.get_by_text("1 sources (provenance preserved)", exact=False)).to_be_visible()
            page.get_by_role("button", name="Fetch: OAuth guide", exact=True).click()
            expect(page.get_by_text("Fetched: OAuth guide", exact=False)).to_be_visible()
            assert any(kind == "fetch" for kind, _ in posted), posted

            # Cost, unknown, and unsupported handling without dispatch.
            page.get_by_label("Engineering request").fill("How many tokens have we spent?")
            page.get_by_role("button", name="Ask", exact=True).click()
            expect(page.get_by_text("45.0k tokens", exact=False).first).to_be_visible()
            page.get_by_label("Engineering request").fill("asdkfjhasd")
            page.get_by_role("button", name="Ask", exact=True).click()
            expect(page.get_by_text("could not map", exact=False)).to_be_visible()
            page.get_by_label("Engineering request").fill("Delete everything")
            page.get_by_role("button", name="Ask", exact=True).click()
            expect(page.get_by_text("not supported", exact=False)).to_be_visible()

            assert not errors, errors
            print("PASS: scoped dispatch with live handoff; selection-tracked explanation; "
                  "confirmed test run; confirmed model-backed review with cost label; "
                  "research search + confirmed fetch; cost/unknown/unsupported handling; "
                  "no page errors")
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()

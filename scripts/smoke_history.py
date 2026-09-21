"""Execution history + replay check (Wave 9): durable timeline, zero model calls.

Drives the real UI with all APIs intercepted. Fixtures: 505 filler events
plus 9 meaningful ones (requirement/task/agent lifecycle, failed test with
a secret-bearing payload, recovery chain sharing a correlation id, merge
commit, HITL request). Proves: cursor pagination to exhaustion with the
retention-style boundary note, category/entity/server-type filters, search,
event detail with correlation + redacted raw payload, office/graph/editor/
evidence jumps, true replay (scrubber, speeds, reconstruction, return to
live), and no page errors.
Run from repository root: .venv\\Scripts\\python scripts\\smoke_history.py
"""
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "apps" / "web-ui"
URL = "http://127.0.0.1:5199"


def _ev(i, typ, ts, seq, **kw):
    base = {"id": f"e{i}", "occurred_at": ts, "event_type": typ, "source": "test",
            "project_id": "p", "task_id": None, "agent_id": None,
            "payload": {}, "project_seq": seq, "correlation_id": kw.pop("correlation_id", None)}
    base.update(kw)
    return base


def main():
    server = subprocess.Popen([shutil.which("node"), str(WEB / "node_modules/vite/bin/vite.js"),
        "--host", "127.0.0.1", "--port", "5199", "--strictPort"], cwd=WEB,
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
            project = {"id": "p", "name": "Local", "root_path": "C:\\local", "default_branch": "main"}
            agents = [{"id": "a1", "project_id": "p", "name": "Backend", "role": "backend",
                       "model": None, "capabilities": [], "state": "running"}]
            tasks = [{"id": "t1", "project_id": "p", "requirement_id": "r1", "title": "Implement auth",
                      "request": "Add middleware", "status": "failed", "priority": 1, "depends_on": [],
                      "attempts": [{"attempt_number": 1, "agent_id": "a1", "outcome": "failed",
                                    "failure_class": "TOOL_FAILURE", "failure_detail": "exit 1",
                                    "evidence_artifact_ids": ["art1"]}]}]
            raw_requirements = [{"id": "r1", "project_id": "p", "title": "OAuth login",
                                 "description": "Users can log in.", "desired_outcome": None,
                                 "priority": "must", "status": "open", "criteria": []}]
            traceability = {"project_id": "p", "generated_at": "2026-09-18T10:00:00Z",
                            "requirements": [{"id": "r1", "title": "OAuth login", "priority": "must",
                                              "status": "UNKNOWN", "implemented": True, "task_ids": ["t1"],
                                              "criteria": [], "evidence_artifact_ids": ["art1"],
                                              "validation_evidence_artifact_ids": []}],
                            "coverage": {"total": 1, "verified": 0, "failed": 0, "unknown": 1},
                            "orphan_task_ids": [], "scope_drift": False}
            hitl = [{"id": "h1", "task_id": "t1", "status": "pending", "risk": "high",
                     "kind": "approval", "question": "Approve the flaky fix?", "choices": []}]
            meaningful = [
                _ev("old", "GIT_COMMIT", "2026-09-10T10:00:00Z", 1,
                    payload={"message": "Ancient commit", "paths": ["old.py"]}),
                _ev("req", "REQUIREMENT_CREATED", "2026-09-18T09:00:00Z", 506,
                    payload={"requirement_id": "r1", "title": "OAuth login"}),
                _ev("tc", "TASK_CREATED", "2026-09-18T09:01:00Z", 507,
                    task_id="t1", payload={"title": "Implement auth"}),
                _ev("ac", "AGENT_CREATED", "2026-09-18T09:02:00Z", 508,
                    agent_id="a1", payload={"role": "backend"}),
                _ev("tool", "TOOL_RUN_COMPLETED", "2026-09-18T10:02:00Z", 509,
                    payload={"tool": "test", "exit_code": 1, "duration_ms": 40,
                              "path": "tests/test_auth.py", "artifact_ids": ["art2"],
                              "api_token": "sekret-flaky-token"}),
                _ev("fail", "TASK_FAILED", "2026-09-18T10:03:00Z", 510,
                    task_id="t1", correlation_id="c1",
                    payload={"attempts": [1], "outcome": "failed"}),
                _ev("rec", "RECOVERY_SELECTED", "2026-09-18T10:04:00Z", 511,
                    task_id="t1", agent_id="a1", correlation_id="c1",
                    payload={"action": "retry_if_safe", "failure_class": "TOOL_FAILURE"}),
                _ev("hitl", "HITL_REQUESTED", "2026-09-18T10:05:00Z", 512,
                    task_id="t1", agent_id="a1", payload={"request_id": "h1", "kind": "approval"}),
                _ev("git", "GIT_COMMIT", "2026-09-18T10:06:00Z", 513,
                    payload={"message": "Fix auth bug", "paths": ["auth.py"]}),
            ]
            fillers = [
                _ev(f"f{i}", "TASK_SCHEDULED", f"2026-09-{1 + (i % 9):02d}T08:00:00Z", 2 + i)
                for i in range(504)
            ]
            ascending = sorted(fillers + meaningful, key=lambda e: e["project_seq"])
            artifacts = {"art1": {"id": "art1", "project_id": "p", "name": "failure.log",
                                   "kind": "raw_output", "mime": "text/plain", "size": 120,
                                   "sha256": "aa"},
                         "art2": {"id": "art2", "project_id": "p", "name": "pytest.xml",
                                   "kind": "report", "mime": "text/xml", "size": 340,
                                   "sha256": "bb"}}

            def api(route):
                url = route.request.url
                path = url.split("/api/", 1)[1].split("?")[0]
                query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                if path == "projects":
                    route.fulfill(json=[project])
                elif path == "projects/open":
                    route.fulfill(json=project)
                elif path.endswith("/agents"):
                    route.fulfill(json=agents)
                elif path.endswith("/tasks"):
                    route.fulfill(json=tasks)
                elif path.startswith("hitl?"):
                    route.fulfill(json=hitl)
                elif path.startswith("events/stream"):
                    route.fulfill(content_type="text/event-stream",
                                  body='data: {"kind":"GATEWAY_STATUS","state":"live"}\n\n')
                elif path == "events":
                    rows = [e for e in ascending if e["project_id"] == "p"]
                    if "event_type" in query:
                        rows = [e for e in rows if e["event_type"] == query["event_type"][0]]
                    if "task_id" in query:
                        rows = [e for e in rows if e["task_id"] == query["task_id"][0]]
                    if "since_seq" in query:
                        rows = [e for e in rows if (e["project_seq"] or 0) > int(query["since_seq"][0])]
                    if "before_seq" in query:
                        rows = [e for e in rows if (e["project_seq"] or 0) < int(query["before_seq"][0])]
                    rows = sorted(rows, key=lambda e: e["occurred_at"], reverse=True)
                    route.fulfill(json=rows[:int(query.get("limit", ["500"])[0])])
                elif path.endswith("/requirements"):
                    route.fulfill(json=raw_requirements)
                elif "traceability" in path:
                    route.fulfill(json=traceability)
                elif path.startswith("artifacts/"):
                    route.fulfill(json=artifacts[path.split("/")[-1]])
                elif "intelligence/costs" in path:
                    route.fulfill(json={"invocations": 0, "total_tokens": 0, "by_model": {},
                                        "by_role": {}, "task_id": None, "budget_tokens_per_task": 1})
                elif path == "healthz":
                    route.fulfill(json={"status": "ok", "version": "test", "environment": "test"})
                elif "toolchains" in path:
                    route.fulfill(json={"languages": [], "diagnostics": []})
                elif "terminal/sessions" in path:
                    route.fulfill(status=503, json={"detail": "PTY disabled"})
                elif "git/status" in path:
                    route.fulfill(json={"branch": "main", "entries": []})
                elif "/file?" in path:
                    route.fulfill(json={"path": "auth.py", "content": "x = 1",
                                        "is_binary": False, "size": 5, "mtime_ms": 0})
                else:
                    route.fulfill(json=[])
            page.route(f"{URL}/api/**", api)
            page.goto(URL)
            page.get_by_role("button", name="Local", exact=False).click()
            page.get_by_role("button", name="History", exact=True).click()

            # Live head page + bounded rendering.
            expect(page.get_by_text("● live", exact=True)).to_be_visible()
            expect(page.get_by_text("Fix auth bug", exact=False).first).to_be_visible()
            expect(page.get_by_text("Show more", exact=False)).to_be_visible()

            # Cursor pagination to exhaustion with the boundary note.
            page.get_by_role("button", name="Show more", exact=False).click()
            page.get_by_role("button", name="Show more", exact=False).click()
            page.get_by_role("button", name="Load older events", exact=True).click()
            expect(page.get_by_text("Ancient commit", exact=False)).to_be_visible()
            expect(page.get_by_text("history begins here", exact=False)).to_be_visible()

            # Server-side type narrowing.
            page.get_by_label("Server-side event type filter").select_option("TASK_FAILED")
            expect(page.get_by_text("Task failed: Implement auth", exact=False)).to_be_visible()
            expect(page.get_by_text("Fix auth bug", exact=False)).to_have_count(0)
            page.get_by_label("Server-side event type filter").select_option("all")

            # Client search over loaded rows (labeled scope).
            page.get_by_label("Search loaded history").fill("auth")
            expect(page.locator(".history-list").get_by_text("TOOL_RUN_COMPLETED", exact=False).first).to_be_visible()
            page.get_by_label("Search loaded history").fill("zzz-nonexistent")
            expect(page.get_by_text("No loaded events match", exact=False)).to_be_visible()
            page.get_by_label("Search loaded history").fill("")

            # Failures filter + entity scoping.
            page.get_by_role("button", name="failures", exact=True).click()
            expect(page.get_by_text("Task failed: Implement auth", exact=False)).to_be_visible()
            expect(page.get_by_text("Fix auth bug", exact=False)).to_have_count(0)
            page.get_by_role("button", name="failures", exact=True).click()
            page.get_by_label("Filter history by task").select_option("t1")
            expect(page.get_by_text("Task failed: Implement auth", exact=False)).to_be_visible()
            expect(page.get_by_text("Ancient commit", exact=False)).to_have_count(0)
            page.get_by_label("Filter history by task").select_option("all")

            # Event detail: context, correlation, redacted raw, jumps.
            page.get_by_role("button", name="test test_auth.py", exact=False).click()
            expect(page.get_by_text("Actor:", exact=False)).to_be_visible()
            page.get_by_text("Raw payload (sanitized)", exact=False).click()
            expect(page.get_by_text("[redacted]", exact=False).first).to_be_visible()
            expect(page.get_by_text("sekret-flaky-token", exact=False)).to_have_count(0)
            expect(page.get_by_text("pytest.xml", exact=False)).to_be_visible()
            page.get_by_role("button", name="TASK_FAILED: Task failed: Implement auth", exact=False).click()
            page.get_by_text("Same correlation chain:", exact=False).wait_for()
            page.get_by_role("button", name="RECOVERY_SELECTED: Recovery decision: retry_if_safe (TOOL_FAILURE)", exact=True).click()
            expect(page.get_by_text("Recovery decision: retry_if_safe", exact=False).first).to_be_visible()
            page.get_by_role("button", name="TASK_FAILED: Task failed: Implement auth", exact=False).click()
            expect(page.get_by_text("failure.log", exact=False)).to_be_visible()
            page.get_by_role("button", name="GIT_COMMIT: Fix auth bug", exact=False).click()
            page.locator(".history-detail").get_by_role("button", name="auth.py", exact=True).click()
            expect(page.locator(".tab-strip").get_by_text("auth.py", exact=False)).to_be_visible()
            page.get_by_role("button", name="History", exact=True).click()

            # Replay: scrubber, speeds, reconstruction, return to live.
            page.get_by_role("button", name="Replay", exact=True).click()
            expect(page.get_by_text("Replay — event 1 of", exact=False)).to_be_visible()
            expect(page.get_by_text("Viewing history", exact=False).first).to_be_visible()
            scrubber = page.get_by_label("Replay position")
            scrubber.focus()
            scrubber.press("ArrowRight")
            expect(page.get_by_text("Replay — event 2 of", exact=False)).to_be_visible()
            page.get_by_role("button", name="Step forward", exact=True).click()
            page.get_by_label("Replay speed").select_option("4")
            page.get_by_role("button", name="Play replay", exact=True).click()
            expect(page.get_by_role("button", name="Pause replay", exact=True)).to_be_visible()
            page.get_by_role("button", name="Pause replay", exact=True).click()
            page.get_by_role("button", name="Jump to event", exact=True).click()
            expect(page.get_by_text("Raw payload (sanitized)", exact=False)).to_be_visible()
            page.get_by_role("button", name="Replay", exact=True).click()
            page.get_by_role("button", name="Step forward", exact=True).click()
            expect(page.get_by_text("as of", exact=False).first).to_be_visible()
            page.get_by_role("button", name="Return to live", exact=True).click()
            expect(page.get_by_text("● live", exact=True)).to_be_visible()

            assert not errors, errors
            print("PASS: cursor pagination to exhaustion; server/client filters; search; "
                  "detail with correlation + redaction + jumps; replay scrubber/speeds/"
                  "reconstruction/return-to-live; no page errors")
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()

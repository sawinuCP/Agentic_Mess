"""Execution Graph + traceability check (Wave 8): real lineage, zero model calls.

Drives the real UI with all APIs intercepted. Fixtures: 1 requirement
(UNKNOWN, 2 criteria) with 3 tasks (running/blocked/failed), 2 agents, a
failed test run with evidence, an integration merge commit plus a plain
commit, worktree links, and a traceability report. Proves: real nodes for
every type, requirement detail with criteria + UNKNOWN honesty, task->agent
->test->evidence->file navigation, derived task->commit edge, failure path
with recovery, search/filter/failures modes, text-tree alternative, keyboard
selection, office/timeline/editor integration, server-authoritative refresh,
and no page errors.
Run from repository root: .venv\\Scripts\\python scripts\\smoke_graph.py
"""
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "apps/web-ui"
URL = "http://127.0.0.1:5198"


def main():
    server = subprocess.Popen([shutil.which("node"), str(WEB / "node_modules/vite/bin/vite.js"),
        "--host", "127.0.0.1", "--port", "5198", "--strictPort"], cwd=WEB,
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
            agents = [
                {"id": "a1", "project_id": "p", "name": "Backend", "role": "backend",
                 "model": "test:model", "capabilities": [], "state": "running"},
                {"id": "a2", "project_id": "p", "name": "Tester", "role": "tester",
                 "model": None, "capabilities": [], "state": "waiting"},
            ]
            tasks = [
                {"id": "t1", "project_id": "p", "requirement_id": "r1", "title": "Implement auth",
                 "request": "Add middleware", "status": "running", "priority": 1, "depends_on": [],
                 "attempts": [{"attempt_number": 1, "agent_id": "a1", "outcome": None,
                               "failure_class": None, "failure_detail": None, "evidence_artifact_ids": []}]},
                {"id": "t2", "project_id": "p", "requirement_id": "r1", "title": "Integration tests",
                 "request": "Cover auth", "status": "blocked", "priority": 2, "depends_on": ["t1"],
                 "attempts": [{"attempt_number": 1, "agent_id": "a2", "outcome": None,
                               "failure_class": None, "failure_detail": None, "evidence_artifact_ids": []}]},
                {"id": "t3", "project_id": "p", "requirement_id": "r1", "title": "Fix flaky test",
                 "request": "Stabilize", "status": "failed", "priority": 3, "depends_on": [],
                 "attempts": [{"attempt_number": 1, "agent_id": "a1", "outcome": "failed",
                               "failure_class": "TOOL_FAILURE", "failure_detail": "exit 1",
                               "evidence_artifact_ids": ["art1"]}]},
            ]
            raw_requirements = [{"id": "r1", "project_id": "p", "title": "OAuth login",
                                 "description": "Users can log in with OAuth.",
                                 "desired_outcome": "Working login", "priority": "must",
                                 "status": "open", "version": 1, "criteria": []}]
            traceability = {"project_id": "p", "generated_at": "2026-09-18T10:00:00Z",
                            "requirements": [{"id": "r1", "title": "OAuth login", "priority": "must",
                                              "status": "UNKNOWN", "implemented": True,
                                              "task_ids": ["t1", "t2", "t3"],
                                              "criteria": [
                                                  {"id": "c1", "description": "Login works",
                                                   "kind": "manual", "mandatory": True, "state": "unknown"},
                                                  {"id": "c2", "description": "Logout works",
                                                   "kind": "manual", "mandatory": False, "state": "verified"},
                                              ],
                                              "evidence_artifact_ids": ["art1"],
                                              "validation_evidence_artifact_ids": []}],
                            "coverage": {"total": 1, "verified": 0, "failed": 0, "unknown": 1},
                            "orphan_task_ids": [], "scope_drift": False}
            def ev(i, typ, ts, **kw):
                base = {"id": f"e{i}", "occurred_at": ts, "event_type": typ, "source": "test",
                        "project_id": "p", "task_id": None, "agent_id": None,
                        "payload": {}, "project_seq": i}
                base.update(kw)
                return base
            events = [
                ev(5, "RECOVERY_SELECTED", "2026-09-18T10:05:00Z", task_id="t3",
                   payload={"action": "retry_if_safe", "failure_class": "TOOL_FAILURE"}),
                ev(4, "TOOL_RUN_COMPLETED", "2026-09-18T10:04:00Z",
                   payload={"tool": "test", "exit_code": 1, "duration_ms": 40,
                             "path": "tests/test_auth.py", "artifact_ids": ["art2"]}),
                ev(3, "GIT_COMMIT", "2026-09-18T10:03:00Z",
                   payload={"message": "Integrate agent/task-1 (worktree a1b2c3d4)",
                             "paths": ["auth.py"]}),
                ev(2, "GIT_COMMIT", "2026-09-18T10:02:00Z",
                   payload={"message": "WIP notes", "paths": ["notes.txt"]}),
                ev(1, "DEPENDENCY_WAIT_STARTED", "2026-09-18T10:01:00Z", task_id="t2", agent_id="a2"),
            ]
            worktrees = [{"id": "a1b2c3d4", "project_id": "p", "task_id": "t1",
                          "branch": "agent/task-1", "path": "C:\\local\\.harness\\wt",
                          "status": "merged", "integration_status": "merged",
                          "integration_position": None, "created_at": "2026-09-18T10:00:00Z"}]
            worktrees = [{"id": "a1b2c3d4", "project_id": "p", "task_id": "t1",
                          "branch": "agent/task-1", "path": "C:\\local\\.harness\\wt",
                          "status": "merged", "integration_status": "merged",
                          "integration_position": None, "created_at": "2026-09-18T10:00:00Z"}]
            artifacts = {"art1": {"id": "art1", "project_id": "p", "name": "failure.log",
                                   "kind": "raw_output", "mime": "text/plain", "size": 120,
                                   "sha256": "aa"},
                         "art2": {"id": "art2", "project_id": "p", "name": "pytest.xml",
                                   "kind": "report", "mime": "text/xml", "size": 340,
                                   "sha256": "bb"}}
            def api(route):
                path = route.request.url.split("/api/", 1)[1]
                if path == "projects": route.fulfill(json=[project])
                elif path == "projects/open": route.fulfill(json=project)
                elif path.endswith("/agents"): route.fulfill(json=agents)
                elif path.endswith("/tasks"): route.fulfill(json=tasks)
                elif path.startswith("hitl?"): route.fulfill(json=[])
                elif path.startswith("events/stream"):
                    route.fulfill(content_type="text/event-stream",
                                  body='data: {"kind":"GATEWAY_STATUS","state":"live"}\n\n')
                elif path.startswith("events?"): route.fulfill(json=events)
                elif path.endswith("/requirements"): route.fulfill(json=raw_requirements)
                elif "/worktrees" in path: route.fulfill(json=worktrees)
                elif "traceability" in path: route.fulfill(json=traceability)
                elif path.startswith("artifacts/"): route.fulfill(json=artifacts[path.split("/")[-1]])
                elif "intelligence/costs" in path:
                    route.fulfill(json={"invocations": 0, "total_tokens": 0, "by_model": {},
                                        "by_role": {}, "task_id": None, "budget_tokens_per_task": 1})
                elif path == "healthz": route.fulfill(json={"status": "ok", "version": "test", "environment": "test"})
                elif "toolchains" in path: route.fulfill(json={"languages": [], "diagnostics": []})
                elif "terminal/sessions" in path: route.fulfill(status=503, json={"detail": "PTY disabled"})
                elif "git/status" in path: route.fulfill(json={"branch": "main", "entries": []})
                elif "/file?" in path:
                    route.fulfill(json={"path": "auth.py", "content": "x = 1",
                                        "is_binary": False, "size": 5, "mtime_ms": 0})
                else: route.fulfill(json=[])
            page.route(f"{URL}/api/**", api)
            page.goto(URL)
            page.get_by_role("button", name="Local", exact=False).click()
            page.get_by_role("button", name="Execution Graph", exact=True).click()

            # Real nodes for every type + honest coverage counts.
            expect(page.get_by_text("1 requirements · 0 verified · 0 failed · 1 unknown", exact=False)).to_be_visible()
            expect(page.get_by_role("button", name="requirement: OAuth login, UNKNOWN", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="task: Implement auth, running", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="agent: Backend, running", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="test: test test_auth.py, failed", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="file: auth.py, recorded", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="evidence: art1, recorded", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="commit: Integrate agent/task-1 (worktree a1b2c3d4), integration", exact=True)).to_be_visible()

            # Requirement detail: criteria, UNKNOWN honesty, no invented mapping.
            page.get_by_role("button", name="requirement: OAuth login, UNKNOWN", exact=True).click()
            expect(page.get_by_text("Users can log in with OAuth.", exact=False)).to_be_visible()
            expect(page.get_by_text("Login works", exact=False)).to_be_visible()
            expect(page.get_by_text("stays UNKNOWN", exact=False)).to_be_visible()
            page.locator("details summary", has_text="Login works").click()
            expect(page.get_by_text("no criterion-level mapping", exact=False).first).to_be_visible()

            # Follow requirement → task → agent → evidence.
            page.get_by_role("button", name="Implement auth (running)", exact=True).click()
            expect(page.get_by_text("Agents:", exact=False)).to_be_visible()
            page.locator(".graph-detail").get_by_role("button", name="Backend", exact=True).click()
            expect(page.get_by_text("Inspect in Office", exact=False)).to_be_visible()

            # Test → evidence metadata → file → editor.
            page.get_by_role("button", name="test: test test_auth.py, failed", exact=True).click()
            page.get_by_role("button", name="Evidence: art2", exact=True).click()
            expect(page.get_by_text("pytest.xml", exact=False)).to_be_visible()
            page.get_by_role("button", name="file: auth.py, recorded", exact=True).click()
            page.get_by_role("button", name="Open in editor", exact=True).click()
            expect(page.locator(".tab-strip").get_by_text("auth.py", exact=False)).to_be_visible()
            page.get_by_role("button", name="Execution Graph", exact=True).click()

            # Derived task → commit edge via the deterministic merge message.
            page.get_by_role("button", name="commit: Integrate agent/task-1 (worktree a1b2c3d4), integration", exact=True).click()
            expect(page.get_by_text("derived from the merge message", exact=False)).to_be_visible()

            # Failure path: failed task, recovery, still-blocked requirement.
            page.locator(".graph-toolbar").get_by_role("button", name="failures", exact=True).click()
            expect(page.get_by_role("button", name="task: Fix flaky test, failed", exact=True)).to_be_visible()
            # Unrelated files drop out while requirement context stays intact.
            expect(page.get_by_role("button", name="file: notes.txt, recorded", exact=True)).to_have_count(0)
            page.get_by_role("button", name="task: Fix flaky test, failed", exact=True).click()
            expect(page.get_by_text("Failure path", exact=False)).to_be_visible()
            expect(page.locator(".graph-detail").get_by_text("Recovery decision: retry_if_safe", exact=False)).to_be_visible()
            expect(page.get_by_text("Requirement still blocked", exact=False)).to_be_visible()
            page.locator(".graph-toolbar").get_by_role("button", name="failures", exact=True).click()

            # Search narrows with context; type filter hides with disclosure.
            page.get_by_label("Search graph").fill("flaky")
            expect(page.get_by_role("button", name="task: Fix flaky test, failed", exact=True)).to_be_visible()
            expect(page.get_by_role("button", name="task: Implement auth, running", exact=True)).to_have_count(0)
            page.get_by_label("Search graph").fill("")
            page.locator(".graph-toolbar").get_by_role("button", name="files", exact=True).click()
            expect(page.get_by_role("button", name="file: auth.py, recorded", exact=True)).to_have_count(0)
            expect(page.get_by_text("hidden by filters", exact=False)).to_be_visible()
            page.locator(".graph-toolbar").get_by_role("button", name="files", exact=True).click()

            # Text-tree alternative + keyboard selection.
            page.get_by_role("button", name="Text view", exact=True).click()
            tree_task = page.locator(".graph-text").get_by_role("button", name="Task: Implement auth", exact=True)
            tree_task.focus()
            tree_task.press("Enter")
            expect(page.get_by_text("Open in Office", exact=False).first).to_be_visible()
            page.get_by_role("button", name="Graph view", exact=True).click()

            # Office integration: task → office inspector; activity seed.
            page.get_by_role("button", name="task: Integration tests, blocked", exact=True).click()
            page.get_by_role("button", name="Open in Office", exact=True).click()
            expect(page.get_by_text("Depends on:", exact=False)).to_be_visible()
            page.get_by_role("button", name="Execution Graph", exact=True).click()
            page.get_by_role("button", name="task: Integration tests, blocked", exact=True).click()
            page.locator(".graph-detail").get_by_role("button", name="View activity", exact=True).click()
            expect(page.get_by_text("DEPENDENCY_WAIT_STARTED", exact=False)).to_be_visible()

            # Server-authoritative refresh: mutate, reload, node follows.
            tasks[0]["status"] = "completed"
            page.reload()
            page.get_by_role("button", name="Local", exact=False).click()
            page.get_by_role("button", name="Execution Graph", exact=True).click()
            expect(page.get_by_role("button", name="task: Implement auth, completed", exact=True)).to_be_visible()
            # ...while the requirement stays honestly UNKNOWN.
            page.get_by_role("button", name="requirement: OAuth login, UNKNOWN", exact=True).click()
            expect(page.get_by_text("stays UNKNOWN", exact=False)).to_be_visible()

            assert not errors, errors
            print("PASS: real nodes per type; requirement detail + UNKNOWN honesty; "
                  "task->agent->test->evidence->file navigation; derived commit edge; "
                  "failure path + recovery; search/filter/failures; text tree + keyboard; "
                  "office/timeline/editor integration; authoritative refresh; no page errors")
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()

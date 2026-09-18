"""Agent Office control-room check (Wave 7): real derived state, zero model calls.

Drives the real UI with all APIs intercepted. Fixtures: 3 agents (running /
waiting / recovering), 3 tasks (running / blocked-on-dependency / failed with
recovery events), agent messages, worktrees, costs, HITL approval, and a
durable event feed. Proves: execution summary, waiting reasons, recovery
chains, agent detail, comms thread + message detail, grouped activity with
filters, approval flow, and no page errors.
Run from repository root: .venv\\Scripts\\python scripts\\smoke_agent_office.py
"""
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "apps" / "web-ui"
URL = "http://127.0.0.1:5195"


def main():
    server = subprocess.Popen([shutil.which("node"), str(WEB / "node_modules/vite/bin/vite.js"),
        "--host", "127.0.0.1", "--port", "5195", "--strictPort"], cwd=WEB,
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
            errors = []
            page.on("pageerror", lambda e: errors.append(e.stack or str(e)))
            project = {"id": "p", "name": "Local", "root_path": "C:\\local", "default_branch": "main"}
            agents = [
                {"id": "a1", "project_id": "p", "name": "Backend", "role": "backend",
                 "model": "test:model", "capabilities": ["python"], "state": "running"},
                {"id": "a2", "project_id": "p", "name": "Tester", "role": "tester",
                 "model": "test:model", "capabilities": [], "state": "waiting"},
                {"id": "a3", "project_id": "p", "name": "Debugger", "role": "debugger",
                 "model": None, "capabilities": [], "state": "recovering"},
            ]
            tasks = [
                {"id": "t1", "project_id": "p", "requirement_id": None, "title": "Implement auth",
                 "request": "Add middleware", "status": "running", "priority": 1, "depends_on": [],
                 "attempts": [{"attempt_number": 1, "agent_id": "a1", "outcome": None,
                               "failure_class": None, "failure_detail": None, "evidence_artifact_ids": []}]},
                {"id": "t2", "project_id": "p", "requirement_id": None, "title": "Integration tests",
                 "request": "Cover auth", "status": "blocked", "priority": 2, "depends_on": ["t1"],
                 "attempts": [{"attempt_number": 1, "agent_id": "a2", "outcome": None,
                               "failure_class": None, "failure_detail": None, "evidence_artifact_ids": []}]},
                {"id": "t3", "project_id": "p", "requirement_id": None, "title": "Fix flaky test",
                 "request": "Stabilize", "status": "failed", "priority": 3, "depends_on": [],
                 "attempts": [{"attempt_number": 1, "agent_id": "a1", "outcome": "failed",
                               "failure_class": "TOOL_FAILURE", "failure_detail": "exit 1",
                               "evidence_artifact_ids": ["art1"]},
                              {"attempt_number": 2, "agent_id": "a3", "outcome": "failed",
                               "failure_class": "MODEL_FAILURE", "failure_detail": None,
                               "evidence_artifact_ids": []}]},
            ]
            def ev(i, typ, ts, **kw):
                base = {"id": f"e{i}", "occurred_at": ts, "event_type": typ, "source": "test",
                        "project_id": "p", "task_id": None, "agent_id": None,
                        "payload": {}, "project_seq": i}
                base.update(kw)
                return base
            events = [
                ev(12, "HITL_REQUESTED", "2026-09-18T10:06:00Z", task_id="t1", agent_id="a1"),
                ev(11, "DEBUGGER_SPAWNED", "2026-09-18T10:05:00Z", task_id="t3", agent_id="a3"),
                ev(10, "RETRY_STARTED", "2026-09-18T10:04:00Z", task_id="t3", agent_id="a3"),
                ev(9, "RECOVERY_SELECTED", "2026-09-18T10:03:00Z", task_id="t3", agent_id="a3",
                   payload={"action": "retry_if_safe", "failure_class": "TOOL_FAILURE"}),
                ev(8, "TOOL_RUN_COMPLETED", "2026-09-18T10:02:00Z", task_id="t1", agent_id="a1",
                   payload={"tool": "pytest", "exit_code": 1, "duration_ms": 40, "path": "tests/test_auth.py"}),
                ev(7, "DEPENDENCY_WAIT_STARTED", "2026-09-18T10:01:00Z", task_id="t2", agent_id="a2"),
                ev(6, "TASK_EXECUTION_STARTED", "2026-09-18T10:00:30Z", task_id="t1", agent_id="a1"),
                ev(5, "AGENT_STARTED", "2026-09-18T10:00:20Z", agent_id="a3"),
                ev(4, "AGENT_STARTED", "2026-09-18T10:00:10Z", agent_id="a2"),
                ev(3, "AGENT_STARTED", "2026-09-18T10:00:00Z", agent_id="a1"),
                ev(2, "AGENT_CREATED", "2026-09-18T09:59:00Z", agent_id="a2",
                   payload={"name": "Tester", "role": "tester"}),
                ev(1, "AGENT_CREATED", "2026-09-18T09:58:00Z", agent_id="a1",
                   payload={"name": "Backend", "role": "backend"}),
            ]
            inbox = {
                "a1": [{"id": "m1", "conversation_id": "c1", "sender_agent_id": "a1",
                        "recipient_agent_id": "a2", "task_id": "t1", "type": "request",
                        "payload": {"summary": "Auth middleware implemented. Please validate."},
                        "payload_ref": None, "priority": 5, "correlation_id": "corr1",
                        "reply_to": None, "created_at": "2026-09-18T10:03:00Z",
                        "expires_at": None, "delivered_at": "2026-09-18T10:03:01Z", "delivery_attempts": 1},
                       {"id": "m2", "conversation_id": "c1", "sender_agent_id": "a2",
                        "recipient_agent_id": "a1", "task_id": "t1", "type": "response",
                        "payload": {"summary": "2 integration tests failing. Details attached."},
                        "payload_ref": "art1", "priority": 5, "correlation_id": "corr1",
                        "reply_to": "m1", "created_at": "2026-09-18T10:04:00Z",
                        "expires_at": None, "delivered_at": None, "delivery_attempts": 0}],
                "a2": [],
                "a3": [],
            }
            inbox["a2"] = list(inbox["a1"])
            approvals = [{"id": "h", "task_id": "t1", "status": "pending", "risk": "high",
                          "kind": "approval", "question": "Approve local change?", "choices": []}]
            worktrees = [{"id": "w1", "project_id": "p", "task_id": "t1", "branch": "agent/task-1",
                          "path": "C:\\local\\.harness\\worktrees\\agent-task-1", "status": "active",
                          "integration_status": "none", "integration_position": None,
                          "created_at": "2026-09-18T10:00:00Z"}]
            costs = {"invocations": 12, "total_tokens": 45000, "by_model": {"test:model": 45000},
                     "by_role": {"backend": 30000, "tester": 15000}, "task_id": None,
                     "budget_tokens_per_task": 100000}
            def api(route):
                path = route.request.url.split("/api/", 1)[1]
                if path == "projects": route.fulfill(json=[project])
                elif path == "projects/open": route.fulfill(json=project)
                elif path.endswith("/agents"): route.fulfill(json=agents)
                elif path.endswith("/tasks"): route.fulfill(json=tasks)
                elif path.startswith("hitl?"): route.fulfill(json=approvals)
                elif path.endswith("hitl/h/decide"):
                    approvals.clear()
                    route.fulfill(json={"status": "approved"})
                elif path.startswith("events/stream"):
                    route.fulfill(content_type="text/event-stream",
                                  body='data: {"kind":"GATEWAY_STATUS","state":"live"}\n\n')
                elif path.startswith("events?"): route.fulfill(json=events)
                elif "/messages" in path:
                    parts = path.split("agents/")
                    agent_id = parts[1].split("/")[0].split("?")[0] if len(parts) > 1 else ""
                    route.fulfill(json=inbox.get(agent_id, []))
                elif path.endswith("/worktrees"): route.fulfill(json=worktrees)
                elif "intelligence/costs" in path:
                    route.fulfill(json=costs if "task_id" not in path else {**costs, "task_id": "t1"})
                elif "traceability" in path: route.fulfill(json={"requirements": []})
                elif path == "healthz": route.fulfill(json={"status": "ok", "version": "test", "environment": "test"})
                elif "toolchains" in path: route.fulfill(json={"languages": [], "diagnostics": []})
                elif "terminal/sessions" in path: route.fulfill(status=503, json={"detail": "PTY disabled"})
                elif "git/status" in path: route.fulfill(json={"branch": "main", "entries": []})
                else: route.fulfill(json=[])
            page.route(f"{URL}/api/**", api)
            page.goto(URL)
            page.get_by_role("button", name="Local", exact=False).click()
            page.get_by_title("Engineering office", exact=False).click()

            # Header: derived execution state, counts, cost snapshot.
            expect(page.get_by_text("Needs attention", exact=True)).to_be_visible()
            expect(page.get_by_text("3 agents · 3 tasks")).to_be_visible()
            expect(page.get_by_text("45.0k tokens")).to_be_visible()

            # Team: live work, waiting reason, recovery badge.
            expect(page.get_by_text("▸ Implement auth (running)")).to_be_visible()
            expect(page.get_by_text("Waiting for Implement auth (running)", exact=False).first).to_be_visible()
            expect(page.get_by_text("Recovery attempted · still failing", exact=False).first).to_be_visible()

            # Agent detail: overview, activity, tasks, tools, files, recovery, cost.
            page.get_by_role("button", name="Inspect agent Backend", exact=True).click()
            expect(page.get_by_text("Current work:", exact=False)).to_be_visible()
            expect(page.get_by_text("task execution started", exact=False).first).to_be_visible()
            expect(page.get_by_text("pytest · exit 1 · 40ms", exact=False)).to_be_visible()
            expect(page.get_by_text("tests/test_auth.py", exact=False).first).to_be_visible()
            page.locator("details summary", has_text="Fix flaky test").click()
            expect(page.get_by_text("Attempt 1 failed", exact=False)).to_be_visible()
            expect(page.get_by_text("Recovery decision: retry_if_safe", exact=False)).to_be_visible()
            page.get_by_role("button", name="← Back to team", exact=True).click()

            # Task inspector with dependency + owner navigation.
            page.get_by_role("button", name="Inspect task Integration tests", exact=True).click()
            expect(page.get_by_text("Depends on:", exact=False)).to_be_visible()
            expect(page.get_by_text("Dependencies completed", exact=False)).to_have_count(0)
            page.get_by_role("button", name="Tester", exact=True).click()
            expect(page.get_by_text("Current work:", exact=False)).to_be_visible()
            page.get_by_role("button", name="← Back to team", exact=True).click()

            # Comms: thread + selectable message detail.
            page.get_by_role("button", name="Comms", exact=True).click()
            expect(page.get_by_text("Backend → Tester", exact=False).first).to_be_visible()
            page.get_by_role("button", name="Message request Backend → Tester", exact=False).click()
            expect(page.get_by_text("corr1", exact=False).first).to_be_visible()
            expect(page.get_by_text("delivered", exact=False).first).to_be_visible()

            # Activity: burst grouping + recovery filter + agent filter.
            page.get_by_role("button", name="Activity", exact=True).click()
            expect(page.get_by_text("3 × AGENT_STARTED", exact=False)).to_be_visible()
            page.get_by_role("button", name="recovery", exact=True).click()
            expect(page.get_by_text("RECOVERY_SELECTED", exact=False)).to_be_visible()
            expect(page.get_by_text("AGENT_STARTED", exact=False)).to_have_count(0)
            page.get_by_role("button", name="all", exact=True).click()
            page.get_by_label("Filter activity by agent").select_option("a1")
            expect(page.get_by_text("TOOL_RUN_COMPLETED", exact=False)).to_be_visible()
            expect(page.get_by_text("DEPENDENCY_WAIT_STARTED", exact=False)).to_have_count(0)

            # Approval: prominent card with task link, approve refreshes.
            page.get_by_role("button", name="Team", exact=False).click()
            expect(page.get_by_label("approvals needed")).to_be_visible()
            page.get_by_role("button", name="Approve", exact=True).click()
            expect(page.get_by_text("Approve local change?", exact=False)).to_have_count(0)

            assert not errors, errors
            print("PASS: office summary/cards/waiting/recovery; detail/tools/files; "
                  "task inspector navigation; comms thread + detail; grouped activity "
                  "with filters; approval flow; no page errors")
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()

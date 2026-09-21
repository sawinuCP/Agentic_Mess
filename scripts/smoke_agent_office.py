"""Agent Office control-room check (Wave 7): real derived state, zero model calls.

Drives the real UI with all APIs intercepted. Fixtures: 3 agents (running /
waiting / recovering), 3 tasks (running / blocked-on-dependency / failed with
recovery events), agent messages, worktrees, costs, HITL approval, and a
durable event feed. Proves: execution summary, waiting reasons, recovery
chains, agent detail, comms thread + message detail, grouped activity with
filters, approval flow, and no page errors.
Run from repository root: .venv\\Scripts\\python scripts\\smoke_agent_office.py
"""
import re
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
            page.on("dialog", lambda dialog: dialog.accept())
            task_requests = []
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
                {"id": "t2", "project_id": "p", "requirement_id": "r1", "title": "Integration tests",
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
            traceability = {"project_id": "p", "generated_at": "2026-09-18T10:00:00Z",
                            "requirements": [{"id": "r1", "title": "Auth requirement", "priority": "high",
                                              "status": "in_progress", "implemented": False, "task_ids": ["t2"],
                                              "criteria": [], "evidence_artifact_ids": [],
                                              "validation_evidence_artifact_ids": []}],
                            "coverage": {"total": 1, "verified": 0, "failed": 0, "unknown": 1},
                            "orphan_task_ids": [], "scope_drift": False}
            costs = {"invocations": 12, "total_tokens": 45000, "by_model": {"test:model": 45000},
                     "by_role": {"backend": 30000, "tester": 15000}, "task_id": None,
                     "budget_tokens_per_task": 100000}
            sessions = {
                "a1": [{"id": "s1", "agent_id": "a1", "runtime": "temporal-worker",
                        "status": "running", "started_at": "2026-09-18T10:00:00Z",
                        "heartbeat_at": "2026-09-18T10:05:00Z", "finished_at": None},
                       {"id": "s0", "agent_id": "a1", "runtime": "local",
                        "status": "ended", "started_at": "2026-09-18T09:00:00Z",
                        "heartbeat_at": "2026-09-18T09:30:00Z",
                        "finished_at": "2026-09-18T09:31:00Z"}],
                "a2": [],
                "a3": [],
            }
            sent_messages = []
            def api(route):
                path = route.request.url.split("/api/", 1)[1]
                method = route.request.method
                if path == "projects": route.fulfill(json=[project])
                elif path == "projects/open": route.fulfill(json=project)
                elif path.endswith("/agents"):
                    if method == "POST":
                        body = route.request.post_data_json
                        agent = {"id": "a9", "project_id": "p", "name": body["name"],
                                 "role": body.get("role", "worker"), "model": body.get("model"),
                                 "capabilities": [], "state": "created"}
                        agents.append(agent)
                        route.fulfill(status=201, json=agent)
                    else:
                        route.fulfill(json=agents)
                elif path.endswith("/tasks"):
                    if method == "POST":
                        body = route.request.post_data_json
                        created_task = {"id": "t9", "project_id": "p", "requirement_id": body.get("requirement_id"),
                                        "title": body["title"], "request": body.get("request", ""),
                                        "status": "pending", "priority": body.get("priority", 5),
                                        "depends_on": body.get("depends_on", []), "attempts": []}
                        tasks.append(created_task)
                        route.fulfill(status=201, json=created_task)
                    else:
                        route.fulfill(json=tasks)
                elif path == "messages" and method == "POST":
                    body = route.request.post_data_json
                    sent_messages.append(body)
                    message = {"id": "m9", "conversation_id": "c9",
                               "sender_agent_id": body.get("sender_agent_id"),
                               "recipient_agent_id": body.get("recipient_agent_id"),
                               "task_id": body.get("task_id"), "type": body.get("type", "request"),
                               "payload": body.get("payload", {}), "payload_ref": None,
                               "priority": 5, "correlation_id": None, "reply_to": None,
                               "created_at": "2026-09-18T10:07:00Z", "expires_at": None,
                               "delivered_at": None, "delivery_attempts": 0}
                    if message["recipient_agent_id"] in inbox:
                        inbox[message["recipient_agent_id"]].append(message)
                    route.fulfill(status=201, json=message)
                elif path.startswith("hitl?"): route.fulfill(json=approvals)
                elif path.endswith("hitl/h/decide"):
                    approvals.clear()
                    route.fulfill(json={"status": "approved"})
                elif "/symbols?" in path:
                    route.fulfill(json=[{"id": "s1", "path": "services/api/app/core/auth.py",
                                         "name": "authenticate", "kind": "function", "parent": None,
                                         "start_line": 42, "end_line": 60,
                                         "signature": "def authenticate(token)", "doc": None,
                                         "language": "python"}])
                elif "/file?" in path:
                    route.fulfill(json={"path": "services/api/app/core/auth.py",
                                        "content": "def authenticate(token): pass",
                                        "is_binary": False, "size": 30, "mtime_ms": 0})
                elif path.startswith("tasks/t"):
                    task_requests.append((route.request.method, path))
                    if path == "tasks/t3/execute":
                        tasks[2]["status"] = "ready"
                        route.fulfill(json={"started": True, "workflow_id": "w1"})
                    else:
                        route.fulfill(status=204)
                elif path.startswith("events/stream"):
                    route.fulfill(content_type="text/event-stream",
                                  body='data: {"kind":"GATEWAY_STATUS","state":"live"}\n\n')
                elif path.startswith("events?"): route.fulfill(json=events)
                elif "/messages" in path:
                    parts = path.split("agents/")
                    agent_id = parts[1].split("/")[0].split("?")[0] if len(parts) > 1 else ""
                    route.fulfill(json=inbox.get(agent_id, []))
                elif "/sessions" in path:
                    parts = path.split("agents/")
                    agent_id = parts[1].split("/")[0].split("?")[0] if len(parts) > 1 else ""
                    route.fulfill(json=sessions.get(agent_id, []))
                elif path.endswith("/worktrees"): route.fulfill(json=worktrees)
                elif "intelligence/costs" in path:
                    route.fulfill(json=costs if "task_id" not in path else {**costs, "task_id": "t1"})
                elif "traceability" in path: route.fulfill(json=traceability)
                elif path == "healthz": route.fulfill(json={"status": "ok", "version": "test", "environment": "test"})
                elif "toolchains" in path: route.fulfill(json={"languages": [], "diagnostics": []})
                elif "terminal/sessions" in path: route.fulfill(status=503, json={"detail": "PTY disabled"})
                elif "git/status" in path: route.fulfill(json={"branch": "main", "entries": []})
                else: route.fulfill(json=[])
            page.route(f"{URL}/api/**", api)
            page.goto(URL)
            page.get_by_role("button", name="Local", exact=False).click()
            expect(page.locator('button.activity-btn[title^="Agents"]')).to_be_visible()
            page.wait_for_timeout(2500)
            page.locator('button.activity-btn[title^="Agents"]').click()

            # Header: derived execution state, counts, cost snapshot.
            expect(page.get_by_text("Needs attention", exact=True)).to_be_visible()
            expect(page.get_by_text("3 agents · 3 tasks")).to_be_visible()
            expect(page.get_by_text("45.0k tokens")).to_be_visible()
            expect(page.locator(".office-summary", has_text="Local")).to_be_visible()

            # Team: live work, waiting reason, attention flags.
            expect(page.locator(".agent-row", has_text="Backend").get_by_text("Implement auth", exact=True)).to_be_visible()
            notes = page.locator(".agent-roster div[role=note]")
            expect(notes).to_have_count(4)
            expect(notes.nth(0)).to_contain_text("1 failed task")
            expect(notes.nth(1)).to_contain_text("1 failed task")
            expect(notes.nth(2)).to_contain_text("Waiting for Implement auth (running)")
            expect(notes.nth(3)).to_contain_text("1 blocked task")

            # Bulk execution: one confirmation fans out over per-task endpoints.
            page.get_by_role("button", name="Pause 2 tasks", exact=True).click()
            page.get_by_role("alertdialog").get_by_role("button", name="Pause", exact=True).click()
            expect(page.get_by_text("Pause signal sent to 2 of 2 tasks", exact=False)).to_be_visible()
            assert task_requests == [("POST", "tasks/t1/pause"), ("POST", "tasks/t2/pause")], task_requests

            # Retry re-dispatches the failed task through the execute endpoint.
            page.get_by_role("button", name="Retry task: Fix flaky test", exact=True).click()
            page.get_by_role("alertdialog").get_by_role("button", name="Retry task", exact=True).click()
            expect(page.get_by_text("Retry dispatched.", exact=False)).to_be_visible()
            assert ("POST", "tasks/t3/execute") in task_requests, task_requests

            # Agent detail: overview, activity, tasks, tools, files, recovery, cost.
            page.locator(".agent-row", has_text="Backend").get_by_role("button", name=re.compile(r"^Open agent Backend")).click()
            expect(page.get_by_text("Current work:", exact=False)).to_be_visible()
            expect(page.get_by_text("temporal-worker · running", exact=False)).to_be_visible()
            expect(page.get_by_text("local · ended", exact=False)).to_be_visible()
            expect(page.get_by_text("task execution started", exact=False).first).to_be_visible()
            expect(page.get_by_text("pytest · exit 1 · 40ms", exact=False)).to_be_visible()
            expect(page.get_by_text("tests/test_auth.py", exact=False).first).to_be_visible()
            expect(page.get_by_text("1 artifact(s)", exact=False)).to_be_visible()
            expect(page.get_by_text("(sole contributor)", exact=False)).to_be_visible()
            expect(page.get_by_text("(shared with 1 other agent)", exact=False)).to_be_visible()
            # Agent scope: pause only this agent's eligible tasks (t1 + t3).
            page.locator(".agent-detail").get_by_role(
                "button", name="Pause Backend's 2 eligible tasks", exact=True).click()
            page.get_by_role("alertdialog").get_by_role("button", name="Pause", exact=True).click()
            expect(page.get_by_text("Pause signal sent to 2 of 2 tasks", exact=False)).to_be_visible()
            assert task_requests[-2:] == [("POST", "tasks/t1/pause"), ("POST", "tasks/t3/pause")], task_requests
            page.locator("details summary", has_text="Fix flaky test").click()
            expect(page.get_by_text("Attempt 1 failed", exact=False)).to_be_visible()
            expect(page.get_by_text("Recovery decision: retry_if_safe", exact=False)).to_be_visible()
            page.get_by_role("button", name="← Back to team", exact=True).click()

            # Dependency map: layered SVG nodes navigate to the inspector.
            expect(page.locator(".dep-map svg .dep-node")).to_have_count(3)
            page.locator(".dep-map").get_by_role("button", name="Inspect task Implement auth, running", exact=True).click()
            expect(page.get_by_text("Add middleware", exact=False)).to_be_visible()

            # Task inspector with dependency + owner navigation.
            page.get_by_role("button", name="Inspect task Integration tests", exact=True).click()
            expect(page.get_by_text("Depends on:", exact=False)).to_be_visible()
            expect(page.get_by_text("· waiting", exact=False).first).to_be_visible()
            page.get_by_role("button", name="Tester", exact=True).click()
            expect(page.get_by_text("Current work:", exact=False)).to_be_visible()
            page.get_by_role("button", name="← Back to team", exact=True).click()

            # Spawn agent: registry insert + roster refresh, no session started.
            page.get_by_role("button", name="New agent", exact=True).click()
            spawn_dialog = page.get_by_role("dialog", name="New agent")
            spawn_dialog.get_by_label("Agent name").fill("Scout")
            spawn_dialog.get_by_role("button", name="Create agent", exact=True).click()
            expect(page.get_by_text("Scout", exact=False)).to_be_visible()
            expect(page.locator(".agent-row", has_text="Scout").get_by_text("no task recorded", exact=False)).to_be_visible()

            # New task: creation + roster refresh, starts pending.
            page.get_by_role("button", name="New task", exact=True).click()
            create_dialog = page.get_by_role("dialog", name="Create task")
            create_dialog.get_by_label("Task title").fill("Write docs")
            create_dialog.get_by_label("Task request").fill("Document the API")
            create_dialog.get_by_role("button", name="Create task", exact=True).click()
            expect(page.get_by_role("button", name="Inspect task Write docs", exact=True)).to_be_visible()

            # Related requirement jumps to the requirements surface.
            page.get_by_role("button", name="Inspect task Integration tests", exact=True).click()
            page.get_by_role("button", name="linked to requirement", exact=False).click()
            page.wait_for_timeout(1500)
            # Requirement explorer: expand, follow the linked task back.
            row = page.locator(".req-row", has_text="Auth requirement")
            expect(row).to_be_visible()
            row.click()
            expect(page.get_by_text("1 linked task", exact=False)).to_be_visible()
            page.locator(".req-detail").get_by_role("button", name="Integration tests", exact=True).click()
            expect(page.get_by_text("Depends on:", exact=False)).to_be_visible()

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
            page.get_by_label("Filter activity by agent").select_option("all")
            page.get_by_label("Filter activity by task").select_option("t2")
            expect(page.get_by_text("DEPENDENCY_WAIT_STARTED", exact=False)).to_be_visible()
            expect(page.get_by_text("TOOL_RUN_COMPLETED", exact=False)).to_have_count(0)

            # Replay: frozen snapshot, step navigation, play/pause, exit.
            page.get_by_role("button", name="all", exact=True).click()
            page.get_by_role("button", name="replay", exact=True).click()
            expect(page.get_by_text("Step 1 of 12", exact=False)).to_be_visible()
            expect(page.get_by_text("agent created", exact=False).first).to_be_visible()
            expect(page.get_by_role("button", name="Previous event", exact=True)).to_be_disabled()
            page.get_by_role("button", name="Next event", exact=True).click()
            expect(page.get_by_text("Step 2 of 12", exact=False)).to_be_visible()
            page.get_by_role("button", name="Play replay", exact=True).click()
            expect(page.get_by_role("button", name="Pause replay", exact=True)).to_be_visible()
            page.get_by_role("button", name="Pause replay", exact=True).click()
            expect(page.get_by_role("button", name="Play replay", exact=True)).to_be_visible()
            page.get_by_role("button", name="Exit replay", exact=True).click()
            expect(page.get_by_text("3 × AGENT_STARTED", exact=False)).to_be_visible()

            # Symbol search: palette command → index lookup → editor jump.
            page.keyboard.press("Control+K")
            search_sym = page.get_by_role("combobox", name="Search commands")
            search_sym.fill("Search symbols")
            page.keyboard.press("Enter")
            expect(page.get_by_role("dialog", name="Search symbols")).to_be_visible()
            page.get_by_role("textbox", name="Search symbols").fill("auth")
            expect(page.get_by_text("authenticate", exact=False)).to_be_visible()
            page.keyboard.press("Enter")
            expect(page.locator(".tab-strip").get_by_text("auth.py", exact=False)).to_be_visible()

            # Approval: prominent card with task link, approve refreshes.
            # (The symbol jump left the sidebar on the explorer — go back.)
            page.locator('button.activity-btn[title^="Agents"]').click()
            page.get_by_role("button", name="Team", exact=False).click()
            page.wait_for_timeout(1500)
            # Approvals pill renders inside the office summary (DOM-truth wait:
            # locator text matching is unreliable for this live-updating pill).
            page.wait_for_function(
                "document.querySelector('.office-summary')?.innerText.includes('1 approval')", timeout=8000)
            page.get_by_role("button", name="Approve", exact=True).click()
            expect(page.get_by_text("Approve local change?", exact=False)).to_have_count(0)

            assert not errors, errors
            print("PASS: office summary/cards/waiting-duration/recovery; bulk + agent-scoped pause; "
                  "retry dispatch; spawn agent; create task; detail/sessions/tools/files/evidence/attribution; "
                  "dep map navigation; task inspector + requirement explorer; operator compose; "
                  "comms thread + detail; grouped activity with agent/task filters; event replay; "
                  "symbol search to editor; approval flow; no page errors")
            browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()

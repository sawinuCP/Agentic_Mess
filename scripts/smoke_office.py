"""Phase-9 office UI smoke: drives the real UI with Playwright (live).

Usage (with the API running on :8000):
  ..\\.venv\\Scripts\\python scripts\\smoke_office.py

Starts the vite dev server (which proxies /api to the control plane), seeds
requirements/tasks plus a pending HITL request, then verifies the Engineering
Office view renders live data: team tab, timeline events, the fail-closed
completion gate, and an interactive HITL approval card.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text

BASE = os.environ.get("SMOKE_BASE_URL", "http://localhost:8000")
UI = os.environ.get("SMOKE_UI_URL", "http://localhost:5173")
WEB_UI = Path(__file__).resolve().parent.parent / "apps" / "web-ui"
DATABASE_URL = os.environ.get(
    "HARNESS_DATABASE_URL",
    "postgresql+psycopg://harness:harness@localhost:15432/harness",
)


def wait_for(url: str, timeout: float) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            httpx.get(url, timeout=2)
            return
        except httpx.HTTPError:
            time.sleep(0.5)
    raise RuntimeError(f"server at {url} did not come up within {timeout}s")


def seed_hitl_request(project_id: str, task_id: str) -> str:
    """Insert a pending HITL request the way the durable gate would (dev smoke aid)."""
    engine = create_engine(DATABASE_URL)
    request_id = str(uuid.uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO hitl_requests (id, project_id, task_id, kind, question, "
                "choices, risk, status, created_at) "
                "VALUES (:id, :project_id, :task_id, 'approve_plan', "
                ":question, CAST(:choices AS jsonb), 'medium', 'pending', now())"
            ),
            {
                "id": request_id,
                "project_id": project_id,
                "task_id": task_id,
                "question": "Approve the plan for the search feature?",
                "choices": '["Approve plan", "Request changes"]',
            },
        )
    return request_id


def main() -> int:
    ui_port = str(httpx.URL(UI).port or 5173)
    dev = subprocess.Popen(
        ["npm", "run", "dev", "--", "--port", ui_port, "--strictPort"],
        cwd=str(WEB_UI),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=True,
    )
    try:
        wait_for(UI, 90)
        run_ui_smoke()
        print("OFFICE UI SMOKE PASSED")
        return 0
    finally:
        dev.terminate()


def run_ui_smoke() -> None:
    from playwright.sync_api import expect, sync_playwright

    root = Path(tempfile.mkdtemp(prefix="harness-office-"))
    client = httpx.Client(base_url=BASE, timeout=30)
    project_id = client.post("/api/projects/open", json={"root_path": str(root)}).json()["id"]

    requirement = client.post(
        f"/api/projects/{project_id}/requirements",
        json={
            "title": "Editor search",
            "description": "Search across the project",
            "priority": "must",
            "criteria": [{"description": "returns line hits", "kind": "manual"}],
        },
    ).json()
    planned = client.post(
        f"/api/requirements/{requirement['id']}/plans",
        json={"tasks": [{"title": "Implement search", "request": "add search"}]},
    ).json()
    task_id = str(planned["task_ids"][0])
    seed_hitl_request(project_id, task_id)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(UI)

            # Open the seeded project through the dialog and wait for it to load.
            page.fill("input.text-input", str(root))
            page.click("button.button")
            try:
                expect(page.locator(".overlay")).to_have_count(0, timeout=60000)
            except AssertionError:
                error_text = page.locator(".error-text").text_content() or "(no error text)"
                page.screenshot(path="tmp-office-fail.png")
                Path("tmp-office-fail.txt").write_text(
                    f"dialog error: {error_text}\n", encoding="utf-8"
                )
                raise
            expect(page.locator(".status-bar")).to_be_visible(timeout=20000)

            # The HITL approval card renders even before switching to the office.
            page.click('button.activity-btn[title^="Agents"]')
            expect(page.locator(".office-title")).to_have_text("Engineering office")
            expect(page.locator(".approval-card")).to_contain_text(
                "Approve the plan for the search feature?", timeout=15000
            )
            expect(page.locator(".risk-badge")).to_have_text("medium risk")

            # Team tab: the task board lists the planned task (assert the
            # accessible name — the visible label carries a status glyph).
            page.get_by_role("button", name="Team").click()
            expect(
                page.get_by_role("button", name="Inspect task Implement search").first
            ).to_be_visible(timeout=15000)

            # Oversight tab: the completion gate is fail-closed without evidence...
            page.get_by_role("button", name="Oversight").click()
            expect(page.locator(".gate-card")).to_contain_text("blocked", timeout=15000)
            # ...and requesting the report surfaces the explicit blockers.
            page.click("button.wide")
            expect(page.locator(".gate-blocker").first).to_contain_text(
                "is unknown", timeout=15000
            )

            # Timeline tab: the durable event stream shows the requirement creation.
            page.get_by_role("button", name="Activity").click()
            expect(
                page.locator(".event-row", has_text="REQUIREMENT_CREATED").first
            ).to_be_visible(timeout=15000)

            # Approve the HITL card interactively; the durable row flips to approved.
            page.click("button.approve")
            expect(page.locator(".approval-card")).to_have_count(0, timeout=15000)
            decided = client.get(
                f"/api/hitl", params={"project_id": project_id}
            ).json()
            assert any(r["status"] == "approved" for r in decided), decided

            # Problems view triages the live project state through the palette.
            page.keyboard.press("Control+K")
            page.locator(".command-palette input").fill("problems")
            page.keyboard.press("Enter")
            expect(page.locator(".command-palette")).to_have_count(0)
            expect(page.locator(".sidebar-header")).to_have_text("PROBLEMS")

            # Runtime view lists ports/leases (empty on a fresh fixture).
            page.keyboard.press("Control+K")
            page.locator(".command-palette input").fill("runtime")
            page.keyboard.press("Enter")
            expect(page.locator(".command-palette")).to_have_count(0)
            expect(page.locator(".sidebar-header")).to_have_text("RUNTIME")

            browser.close()
    finally:
        client.delete(f"/api/projects/{project_id}")


if __name__ == "__main__":
    sys.exit(main())

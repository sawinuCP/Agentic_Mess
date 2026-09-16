"""Phase-8 oversight smoke: traceability, security gate, review pipeline, completion.

Usage (with the API running):
  ..\\.venv\\Scripts\\python scripts\\smoke_oversight.py

Covers the full spec §23/§24 chain live: requirement -> criteria -> task ->
evidence -> VERIFIED -> completion gate, plus the bounded review pipeline
(rehearsal provider -> needs_evidence, never a fake approval).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import httpx

BASE = "http://localhost:8000"


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=120)
    root = Path(tempfile.mkdtemp(prefix="harness-oversight-"))
    (root / "settings.py").write_text("DEBUG = True\n", encoding="utf-8")

    project_id = client.post("/api/projects/open", json={"root_path": str(root)}).json()["id"]
    print(f"[1] project: {project_id[:8]}...")

    requirement = client.post(
        f"/api/projects/{project_id}/requirements",
        json={
            "title": "Editor search",
            "description": "Users can search across the project",
            "priority": "must",
            "criteria": [
                {"description": "search returns line hits", "kind": "manual", "mandatory": True},
                {"description": "search is case-insensitive", "kind": "manual", "mandatory": False},
            ],
        },
    )
    requirement.raise_for_status()
    req_body = requirement.json()
    criterion_id = req_body["criteria"][0]["id"]
    print(f"[2] requirement with mandatory criteria: {req_body['id'][:8]}...")

    plan = client.post(
        f"/api/requirements/{req_body['id']}/plans",
        json={"tasks": [{"title": "Implement search", "request": "add search"}]},
    )
    plan.raise_for_status()
    task_id = str(plan.json()["task_ids"][0])

    # Completion must be blocked before evidence (FR-026).
    blocked = client.post(f"/api/projects/{project_id}/oversight/completion")
    assert blocked.status_code == 409, "completion must fail closed without evidence"
    print("[3] completion blocked while criteria unverified (fail-closed)")

    # Security gate: planted credential fails, cleanup passes.
    (root / "settings.py").write_text(
        "AWS_ACCESS_KEY_ID = 'AKIAIOSFODNN7EXAMPLE'\n", encoding="utf-8"
    )
    scan_failed = client.post(
        f"/api/projects/{project_id}/quality/security-scan", json={"task_id": task_id}
    ).json()
    assert scan_failed["status"] == "failed" and scan_failed["findings"]
    print(f"[4] security scan failed on planted credential: {scan_failed['findings'][0]['kind']}")

    (root / "settings.py").write_text("DEBUG = True\n", encoding="utf-8")
    scan_ok = client.post(
        f"/api/projects/{project_id}/quality/security-scan", json={"task_id": task_id}
    ).json()
    assert scan_ok["status"] == "passed"
    print("[5] security scan passes after cleanup")

    # Evidence-backed criterion verification (VERIFIED only with evidence).
    evidence = client.post(
        f"/api/projects/{project_id}/artifacts",
        files={"file": ("search-results.txt", b"line 12: match 'query'")},
    )
    evidence.raise_for_status()
    artifact_id = evidence.json()["id"]
    verified = client.post(
        f"/api/requirements/{req_body['id']}/criteria/{criterion_id}/verify",
        json={"evidence_artifact_id": artifact_id, "task_id": task_id},
    )
    verified.raise_for_status()
    print("[6] criterion VERIFIED with evidence artifact")

    # Review pipeline via the real registry (rehearsal): honest needs_evidence.
    review = client.post(
        f"/api/tasks/{task_id}/reviews",
        json={"title": "Search implementation", "proposal": "Ship regex-based search"},
    )
    review.raise_for_status()
    review_body = review.json()
    assert review_body["verdict"] == "needs_evidence"
    assert len(review_body["reviews"]) == 5  # reviewers + critic + verifier + adjudicator
    print("[7] review pipeline bounded and fail-closed (needs_evidence, 5 reviews)")

    trace = client.get(f"/api/projects/{project_id}/oversight/traceability").json()
    assert trace["coverage"]["verified"] == 1
    print("[8] traceability report: requirement VERIFIED")

    completion = client.post(f"/api/projects/{project_id}/oversight/completion")
    completion.raise_for_status()
    assert completion.json()["completion_allowed"] is True
    assert completion.json()["artifact_id"]
    print("[9] completion allowed with durable report artifact (FR-027)")

    client.delete(f"/api/projects/{project_id}")
    print("OVERSIGHT SMOKE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())

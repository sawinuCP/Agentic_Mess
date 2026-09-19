"""Phase G13–G15: critical use-case end-to-end flows (live PostgreSQL).

Each flow drives the real product path (HTTP API → application → persistence
→ events) and asserts durable state, not just status codes:

- Flow A (UC-02 → UC-03 → UC-14 → UC-22): requirement → plan → evidence →
  criterion verification → traceability VERIFIED → completion gate, plus the
  fail-closed negatives (409 before verification, 404 without evidence, 422
  for vague requirements / bad plan links).
- Flow B (UC-04 → UC-06): spawn agent → session lifecycle → durable message →
  inbox replay → clean end, plus 404 negatives.
- Flow C (boundary proofs for the G3 refactors C2/C3): event-query paging and
  symbol search/file-symbols through the moved read contracts, over data
  produced by the real flows above.

Temporal-gated execution and the realtime live hop are intentionally out of
scope here (covered by test_recovery_workflow.py / test_realtime_stream.py,
both Wave-12-frozen): these flows prove the synchronous product core.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REQUIREMENT_BODY = {
    "title": "Login flow",
    "description": "Users must be able to sign in with credentials.",
    "desired_outcome": "Working login flow with tests",
    "priority": "must",
    "criteria": [
        {
            "description": "Login endpoint returns 200 for valid credentials",
            "kind": "automated_test",
        },
        {"description": "Invalid credentials return 401", "kind": "automated_test"},
    ],
}

PLAN_BODY = {
    "summary": "Build login then harden it",
    "tasks": [
        {"title": "Backend login", "request": "Implement /login endpoint"},
        {
            "title": "Login hardening",
            "request": "Add 401 handling",
            "depends_on": ["Backend login"],
        },
    ],
}


def _upload(client: object, project_id: str, data: bytes = b"suite output: ok") -> str:
    response = client.post(  # type: ignore[union-attr]
        f"/api/projects/{project_id}/artifacts",
        files={"file": ("evidence.txt", data, "text/plain")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _event_types(client: object, project_id: str, **params: object) -> list[dict]:
    response = client.get(  # type: ignore[union-attr]
        "/api/events", params={"project_id": project_id, "limit": 500, **params}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_requirement_to_verified_completion(project: tuple) -> None:
    """UC-02 → UC-03 → UC-14 → UC-22 with fail-closed negatives (G13/G14/G15)."""
    _app, client, project_id, _root = project

    # --- Requirement leg (UC-02): created + durable event -------------------
    created = client.post(f"/api/projects/{project_id}/requirements", json=REQUIREMENT_BODY)
    assert created.status_code == 201, created.text
    requirement = created.json()
    assert len(requirement["criteria"]) == 2
    criteria_ids = [c["id"] for c in requirement["criteria"]]

    events = _event_types(client, project_id, event_type="REQUIREMENT_CREATED")
    assert any(e["payload"].get("requirement_id") == requirement["id"] for e in events), (
        "REQUIREMENT_CREATED must name the new requirement"
    )

    # --- Negative: completion is blocked before anything is proven ----------
    blocked = client.post(f"/api/projects/{project_id}/oversight/completion")
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["report"]["completion_allowed"] is False

    # --- Planning leg (UC-03): plan links tasks to the requirement ----------
    planned = client.post(f"/api/requirements/{requirement['id']}/plans", json=PLAN_BODY)
    assert planned.status_code == 201, planned.text
    tasks = client.get(f"/api/projects/{project_id}/tasks").json()
    assert len(tasks) == 2
    task_ids = [t["id"] for t in tasks]

    # --- Verification leg (UC-14): evidence-backed, one criterion at a time -
    artifact_id = _upload(client, project_id)

    # Negative: claims without evidence never verify (FR-026).
    no_evidence = client.post(
        f"/api/requirements/{requirement['id']}/criteria/{criteria_ids[0]}/verify",
        json={"evidence_artifact_id": str(uuid.uuid4()), "task_id": task_ids[0]},
    )
    assert no_evidence.status_code == 404, no_evidence.text

    first = client.post(
        f"/api/requirements/{requirement['id']}/criteria/{criteria_ids[0]}/verify",
        json={"evidence_artifact_id": artifact_id, "task_id": task_ids[0]},
    )
    assert first.status_code == 200, first.text
    assert first.json()["state"] == "verified"

    mid = client.get(f"/api/projects/{project_id}/oversight/traceability").json()
    entry = next(r for r in mid["requirements"] if r["id"] == requirement["id"])
    assert entry["status"] == "UNKNOWN"  # one mandatory criterion still open
    assert client.post(f"/api/projects/{project_id}/oversight/completion").status_code == 409

    second = client.post(
        f"/api/requirements/{requirement['id']}/criteria/{criteria_ids[1]}/verify",
        json={"evidence_artifact_id": artifact_id, "task_id": task_ids[1]},
    )
    assert second.status_code == 200, second.text

    trace = client.get(f"/api/projects/{project_id}/oversight/traceability").json()
    entry = next(r for r in trace["requirements"] if r["id"] == requirement["id"])
    assert entry["status"] == "VERIFIED"
    assert entry["implemented"] is True
    assert trace["coverage"]["verified"] == 1

    # --- Completion + evidence legs (UC-14/UC-22): report artifact streams ---
    done = client.post(f"/api/projects/{project_id}/oversight/completion")
    assert done.status_code == 200, done.text
    report = done.json()
    assert report["completion_allowed"] is True
    assert report["artifact_id"]
    content = client.get(f"/api/artifacts/{report['artifact_id']}/content")
    assert content.status_code == 200
    assert b"Login flow" in content.content  # the report names the requirement

    # --- Negatives: vague requirements and bad plan links stay 422 ---------
    vague = client.post(
        f"/api/projects/{project_id}/requirements",
        json={"title": "vague", "description": "do the thing"},
    )
    assert vague.status_code == 422
    bad_plan = client.post(
        f"/api/requirements/{requirement['id']}/plans",
        json={"tasks": [{"title": "T2", "request": "t2", "depends_on": ["nope"]}]},
    )
    assert bad_plan.status_code == 422


def test_agent_spawn_message_inbox_and_clean_end(project: tuple) -> None:
    """UC-04 → UC-06: spawn, session lifecycle, durable message, replay (G14)."""
    _app, client, project_id, _root = project

    agent = client.post(
        f"/api/projects/{project_id}/agents", json={"name": "worker-1", "role": "worker"}
    )
    assert agent.status_code == 201, agent.text
    agent_id = agent.json()["id"]

    session = client.post(f"/api/agents/{agent_id}/sessions")
    assert session.status_code == 201, session.text
    session_id = session.json()["id"]

    heartbeat = client.post(f"/api/sessions/{session_id}/heartbeat")
    assert heartbeat.status_code == 200, heartbeat.text

    sent = client.post(
        "/api/messages",
        json={
            "sender_agent_id": agent_id,
            "recipient_agent_id": agent_id,
            "type": "progress",
            "payload": {"text": "login endpoint sketched"},
        },
    )
    assert sent.status_code == 201, sent.text
    message_id = sent.json()["id"]

    inbox = client.get(f"/api/agents/{agent_id}/messages").json()
    assert any(m["id"] == message_id for m in inbox)
    stored = next(m for m in inbox if m["id"] == message_id)
    assert stored["payload"] == {"text": "login endpoint sketched"}
    assert stored["delivered_at"] is None  # live hop off in tests: durable, pending

    conversation_id = sent.json()["conversation_id"]
    replay = client.get(f"/api/conversations/{conversation_id}/messages").json()
    assert [m["id"] for m in replay] == [message_id]

    ended = client.post(f"/api/sessions/{session_id}/end")
    assert ended.status_code == 200, ended.text
    assert ended.json()["status"] == "ended"
    assert client.get(f"/api/agents/{agent_id}").json()["state"] == "waiting"

    # --- Negatives ----------------------------------------------------------
    assert client.get(f"/api/agents/{uuid.uuid4()}/sessions").status_code == 404
    assert client.post(f"/api/sessions/{uuid.uuid4()}/end").status_code == 404


def test_event_paging_and_symbol_reads_use_owner_contracts(project: tuple) -> None:
    """C2/C3 proofs: moved read contracts serve real data (G3 regression net)."""
    _app, client, project_id, root = project

    # Seed events through the product (not fixtures): two requirements.
    for index in range(2):
        created = client.post(
            f"/api/projects/{project_id}/requirements",
            json={
                "title": f"req {index}",
                "description": "Users must be able to sign in.",
                "desired_outcome": "Working login flow",
                "priority": "must",
                "criteria": [{"description": "It works", "kind": "automated_test"}],
            },
        )
        assert created.status_code == 201, created.text

    asc = _event_types(client, project_id, order="asc")
    seqs = [e["project_seq"] for e in asc if e["project_seq"] is not None]
    assert len(seqs) >= 2 and seqs == sorted(seqs)
    head = seqs[0]
    tail = _event_types(client, project_id, order="asc", since_seq=head)
    assert all(e["project_seq"] > head for e in tail if e["project_seq"] is not None)
    desc = _event_types(client, project_id, order="desc", limit=1)
    assert len(desc) == 1

    # Seed a real symbol via the product indexer, read it via the moved helpers.
    target = Path(str(root)) / "phase_g_probe.py"
    target.write_text("def phase_g_probe_function():\n    return 42\n", encoding="utf-8")
    indexed = client.post(f"/api/projects/{project_id}/intelligence/index", json={})
    assert indexed.status_code == 200, indexed.text
    assert indexed.json()["symbols"] >= 1

    found = client.get(f"/api/projects/{project_id}/symbols", params={"q": "phase_g_probe"})
    assert found.status_code == 200, found.text
    assert any(s["name"] == "phase_g_probe_function" for s in found.json())

    doc_symbols = client.get(
        f"/api/projects/{project_id}/symbols/file", params={"path": "phase_g_probe.py"}
    )
    assert doc_symbols.status_code == 200, doc_symbols.text
    assert [s["name"] for s in doc_symbols.json()] == ["phase_g_probe_function"]

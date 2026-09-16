"""Review/debate/adjudication integration (FR-017, AC-012): scripted-provider pipeline.

Uses a deterministic scripted model provider through the real orchestration logic
(stages, persistence, adjudication) against the live database.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents_runtime.providers import ModelProviderError, ModelRequest, ModelResponse
from app.services.quality import review as review_service

pytestmark = pytest.mark.integration


def _response(text: str) -> ModelResponse:
    return ModelResponse(
        text=text,
        provider="scripted",
        model="scripted-1",
        prompt_tokens_est=1,
        output_tokens_est=1,
    )


class ScriptedProvider:
    """Returns a role-keyed canned response; raises for roles containing 'boom'."""

    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = responses

    async def complete(self, request: ModelRequest, route: Any) -> ModelResponse:
        if "boom" in request.role:
            raise ModelProviderError("scripted failure")
        return _response(self._responses.get(request.role, self._responses["*"]))


_APPROVE = json.dumps(
    {
        "verdict": "approve",
        "summary": "evidence supports the proposal",
        "findings": [
            {"severity": "info", "claim": "tests cover the change", "evidence": "artifact-1"}
        ],
    }
)
_REJECT = json.dumps(
    {
        "verdict": "reject",
        "summary": "no evidence for the core claim",
        "findings": [{"severity": "blocker", "claim": "no test evidence attached", "evidence": ""}],
    }
)


def _run(app: FastAPI, project_id: str, **kwargs: Any) -> Any:
    with app.state.session_factory() as session:
        return asyncio.run(
            review_service.run_review(
                session,
                app.state.session_factory,
                project_id=uuid.UUID(project_id),
                **kwargs,
            )
        )


def test_full_pipeline_persists_decision_and_reviews(app: FastAPI, project: tuple) -> None:
    _app, _client, project_id, _tmp = project
    provider = ScriptedProvider(
        {
            "reviewer-1": _APPROVE,
            "reviewer-2": _APPROVE,
            "critic": json.dumps(
                {"verdict": "approve", "summary": "findings are supported", "findings": []}
            ),
            "evidence_verifier": json.dumps(
                {"verdict": "approve", "summary": "all claims supported", "findings": []}
            ),
            "adjudicator": json.dumps(
                {"verdict": "approve", "summary": "approved with evidence", "findings": []}
            ),
            "*": _APPROVE,
        }
    )
    outcome = _run(
        _app,
        project_id,
        proposal="Adopt approach X because of constraint Y",
        proposal_title="Approve approach X",
        evidence=["artifact-1"],
        provider_override=provider,
    )
    assert outcome.verdict == "approved"
    roles = [entry["role"] for entry in outcome.reviews]
    assert roles == ["reviewer-1", "reviewer-2", "critic", "evidence_verifier", "adjudicator"]
    assert all(entry["model"] for entry in outcome.reviews)  # model identity persisted

    with TestClient(_app) as client:
        body = client.get(f"/api/decisions/{outcome.decision_id}").json()
        assert body["status"] == "accepted"  # evidence-backed approval
        assert len(body["reviews"]) == 5


def test_unsupported_rejection_stays_proposed(app: FastAPI, project: tuple) -> None:
    _app, _client, project_id, _tmp = project
    outcome = _run(
        _app,
        project_id,
        proposal="Risky change without evidence",
        proposal_title="Risky change",
        provider_override=ScriptedProvider(
            {"reviewer-1": _REJECT, "reviewer-2": _REJECT, "*": _REJECT}
        ),
    )
    assert outcome.verdict == "changes_requested"
    assert any(finding["severity"] == "blocker" for finding in outcome.findings)
    with TestClient(_app) as client:
        body = client.get(f"/api/decisions/{outcome.decision_id}").json()
        assert body["status"] == "proposed"  # rejected decisions stay open for humans


def test_provider_failure_fails_closed(app: FastAPI, project: tuple) -> None:
    _app, _client, project_id, _tmp = project
    outcome = _run(
        _app,
        project_id,
        proposal="Anything",
        proposal_title="Broken provider",
        reviewer_roles=["boom-1", "boom-2"],
        provider_override=ScriptedProvider({"*": _APPROVE}),
    )
    assert outcome.verdict == "error"
    with TestClient(_app) as client:
        body = client.get(f"/api/decisions/{outcome.decision_id}").json()
        assert body["status"] == "proposed"  # never adjudicated on failure


def test_review_endpoint_uses_the_real_registry(project: tuple) -> None:
    _app, client, project_id, _tmp = project
    requirement = client.post(
        f"/api/projects/{project_id}/requirements",
        json={
            "title": "R",
            "description": "D",
            "priority": "should",
            "criteria": [{"description": "criterion", "kind": "manual"}],
        },
    ).json()
    planned = client.post(
        f"/api/requirements/{requirement['id']}/plans",
        json={"tasks": [{"title": "T", "request": "R"}]},
    ).json()
    task_id = str(planned["task_ids"][0])

    result = client.post(
        f"/api/tasks/{task_id}/reviews",
        json={"title": "Rehearsal review", "proposal": "Use the default registry"},
    )
    assert result.status_code == 201
    body = result.json()
    # The rehearsal provider has no review verdicts — every stage resolves to
    # needs_evidence and the decision stays proposed (fail-closed, honest default).
    assert body["verdict"] == "needs_evidence"
    assert len(body["reviews"]) == 5
    assert body["reviews"][0]["model"]  # model identity recorded per participant

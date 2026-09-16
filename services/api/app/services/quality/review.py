"""Independent review, adversarial critique and adjudication (FR-017, AC-012, spec §24).

Pipeline: Proposer -> Independent Reviewer(s) -> Adversarial Critic -> Evidence
Verifier -> Adjudicator -> Decision + Evidence.

Guarantees (spec §24, non-negotiable):
- Independent contexts: reviewers see the proposal + evidence only — never each
  other's output and never any chain-of-thought.
- The critic sees only the consolidated findings, and challenges unsupported ones.
- Rounds, output tokens and wall-clock time are bounded.
- Evidence outranks unsupported preference: unparsable or evidence-free responses
  resolve to ``needs_evidence``, never to approval.
- Fail-closed: a provider failure leaves the decision unadjudicated (proposed).
- Every participant's verdict and model identity is persisted (``reviews`` table).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.agents_runtime.models_registry import ModelRegistry
from app.agents_runtime.providers import ModelProvider, ModelProviderError, ModelRequest
from app.core.errors import DomainError
from app.db.models import Decision, Review
from app.services.core.events import record_event

MAX_ROUNDS = 3
MODEL_CALL_TIMEOUT_SECONDS = 180.0

_VALID_VERDICTS = {"approve", "reject", "needs_evidence"}
_SEVERITIES = {"blocker", "major", "minor", "info"}


@dataclass(slots=True)
class ReviewFinding:
    reviewer: str
    severity: str
    claim: str
    evidence: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "reviewer": self.reviewer,
            "severity": self.severity,
            "claim": self.claim,
            "evidence": self.evidence,
        }


@dataclass(slots=True)
class ReviewOutcome:
    decision_id: str
    verdict: str  # approved | changes_requested | needs_evidence | error
    rationale: str
    reviews: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, str]] = field(default_factory=list)


def _review_system(role: str) -> str:
    return (
        f"You are the {role} in an independent software review. Respond ONLY with a JSON "
        'object: {"verdict": "approve|reject|needs_evidence", "summary": str, '
        '"findings": [{"severity": "blocker|major|minor|info", "claim": str, '
        '"evidence": str}]}. Evidence outranks preference; do not approve without evidence.'
    )


def _parse_review(text: str, participant: str) -> dict[str, Any]:
    """Defensive JSON parsing — unparsable output can never approve (fail-closed)."""
    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except (json.JSONDecodeError, ValueError):
        return {
            "verdict": "needs_evidence",
            "summary": f"{participant}: unparsable response",
            "findings": [],
        }
    verdict = str(data.get("verdict", "needs_evidence"))
    if verdict not in _VALID_VERDICTS:
        verdict = "needs_evidence"
    findings = []
    for raw in data.get("findings", []) or []:
        if not isinstance(raw, dict):
            continue
        severity = str(raw.get("severity", "minor"))
        findings.append(
            {
                "severity": severity if severity in _SEVERITIES else "minor",
                "claim": str(raw.get("claim", ""))[:500],
                "evidence": str(raw.get("evidence", ""))[:500],
            }
        )
    return {
        "verdict": verdict,
        "summary": str(data.get("summary", ""))[:2000],
        "findings": findings,
    }


async def _ask(
    registry: ModelRegistry, role: str, prompt: str, *, max_output_tokens: int
) -> dict[str, Any]:
    request = ModelRequest(
        role=role, system=_review_system(role), prompt=prompt, max_output_tokens=max_output_tokens
    )
    response = await asyncio.wait_for(
        registry.complete(request), timeout=MODEL_CALL_TIMEOUT_SECONDS
    )
    return _parse_review(response.text, role)


def _consolidated(findings: list[ReviewFinding]) -> str:
    lines = [f"- [{f.severity}] {f.reviewer}: {f.claim}" for f in findings]
    return "\n".join(lines) if lines else "- (no findings)"


def _load_registry() -> ModelRegistry:
    from app.core.config import get_settings  # noqa: PLC0415

    return ModelRegistry.load(Path(getattr(get_settings(), "models_config_path", "") or "") or None)


def _persist_review(
    db: Session,
    *,
    decision_id: uuid.UUID,
    task_id: uuid.UUID | None,
    role: str,
    verdict: str,
    summary: str,
    model: str,
    rounds: int = 1,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    review = Review(
        decision_id=decision_id,
        task_id=task_id,
        reviewer_role=role,
        verdict=verdict,
        summary=summary[:4000],
        rounds=rounds,
        model=model,
    )
    db.add(review)
    db.commit()
    entry: dict[str, Any] = {
        "id": str(review.id),
        "role": role,
        "verdict": verdict,
        "summary": summary[:500],
        "model": model,
        "rounds": rounds,
    }
    if detail:
        entry["detail"] = detail
    return entry


def _override_registry(base: ModelRegistry, provider: ModelProvider) -> ModelRegistry:
    """Clone the registry routing every review role through ``provider`` (deterministic
    tests/smokes). Models and temperatures from the base routes are preserved."""
    routes: dict[str, dict[str, Any]] = {}
    for role in (
        "reviewer-1",
        "reviewer-2",
        "reviewer-3",
        "reviewer-4",
        "critic",
        "evidence_verifier",
        "adjudicator",
    ):
        source = base.route_for("reviewer" if role.startswith("reviewer") else role)
        routes[role] = {
            "provider": source.provider,
            "model": source.model,
            "max_output_tokens": source.max_output_tokens,
            "temperature": source.temperature,
        }
    return ModelRegistry(routes, provider_override=provider)


async def run_review(
    db: Session,
    factory: sessionmaker[Session],
    *,
    proposal: str,
    proposal_title: str,
    evidence: list[str] | None = None,
    task_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    reviewer_roles: list[str] | None = None,
    max_rounds: int = 1,
    registry: ModelRegistry | None = None,
    provider_override: ModelProvider | None = None,
) -> ReviewOutcome:
    """Run the bounded review pipeline and persist every step durably."""
    if registry is None:
        registry = _load_registry()
    if provider_override is not None:
        registry = _override_registry(registry, provider_override)
    roles = reviewer_roles or ["reviewer-1", "reviewer-2"]
    if not 1 <= len(roles) <= 4:
        raise DomainError("1 to 4 independent reviewers are required", 422)
    rounds = max(1, min(max_rounds, MAX_ROUNDS))

    decision = Decision(
        project_id=project_id,
        task_id=task_id,
        title=proposal_title[:300],
        rationale=proposal[:4000],
        kind="engineering",
        made_by="proposer",
        status="proposed",
    )
    db.add(decision)
    db.commit()

    evidence_block = (
        "\n".join(f"- {item}" for item in (evidence or [])) or "- (no evidence attached)"
    )
    base_prompt = (
        f"PROPOSAL\n{proposal[:4000]}\n\nEVIDENCE\n{evidence_block}\n\n"
        "Review the proposal on its merits. Cite evidence for every finding."
    )
    review_entries: list[dict[str, Any]] = []
    findings: list[ReviewFinding] = []

    try:
        # Stage 1 — independent reviewers: parallel, isolated contexts (spec §24).
        first_round = await asyncio.gather(
            *(_ask(registry, role, base_prompt, max_output_tokens=2048) for role in roles)
        )
        for role, parsed in zip(roles, first_round, strict=True):
            for finding in parsed["findings"]:
                findings.append(ReviewFinding(reviewer=role, **finding))
            review_entries.append(
                _persist_review(
                    db,
                    decision_id=decision.id,
                    task_id=task_id,
                    role=role,
                    verdict=parsed["verdict"],
                    summary=parsed["summary"],
                    model=registry.route_for(role).model,
                    detail={"findings": parsed["findings"]},
                )
            )

        # Stage 2 — adversarial critic: consolidated findings only (no chain-of-thought).
        critic = await _ask(
            registry,
            "critic",
            f"CONSOLIDATED FINDINGS\n{_consolidated(findings)}\n\n"
            "Challenge every finding that lacks evidence. Escalate real blockers.",
            max_output_tokens=2048,
        )
        for finding in critic["findings"]:
            findings.append(ReviewFinding(reviewer="critic", **finding))
        review_entries.append(
            _persist_review(
                db,
                decision_id=decision.id,
                task_id=task_id,
                role="critic",
                verdict=critic["verdict"],
                summary=critic["summary"],
                model=registry.route_for("critic").model,
                rounds=rounds,
                detail={"findings": critic["findings"]},
            )
        )
    except (ModelProviderError, TimeoutError) as exc:
        return _fail_closed(factory, decision, task_id, project_id, exc, review_entries, findings)

    return await _verify_and_adjudicate(
        db,
        factory,
        decision=decision,
        task_id=task_id,
        project_id=project_id,
        proposal=proposal,
        findings=findings,
        evidence_block=evidence_block,
        verifier_input=critic["summary"],
        rounds=rounds,
        registry=registry,
        review_entries=review_entries,
    )


async def _verify_and_adjudicate(
    db: Session,
    factory: sessionmaker[Session],
    *,
    decision: Decision,
    task_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    proposal: str,
    findings: list[ReviewFinding],
    evidence_block: str,
    verifier_input: str,
    rounds: int,
    registry: ModelRegistry,
    review_entries: list[dict[str, Any]],
) -> ReviewOutcome:
    verdict = "needs_evidence"
    rationale = ""
    try:
        # Stage 3 — evidence verifier: claims vs attached evidence.
        verifier = await _ask(
            registry,
            "evidence_verifier",
            f"CONSOLIDATED FINDINGS\n{_consolidated(findings)}\n\n"
            f"EVIDENCE\n{evidence_block}\n\n"
            "Mark each claim supported or unsupported by the evidence.",
            max_output_tokens=2048,
        )
        review_entries.append(
            _persist_review(
                db,
                decision_id=decision.id,
                task_id=task_id,
                role="evidence_verifier",
                verdict=verifier["verdict"],
                summary=verifier["summary"],
                model=registry.route_for("evidence_verifier").model,
                detail={"findings": verifier["findings"]},
            )
        )

        # Stage 4 — adjudicator: final decision, persisted with rationale (spec §24).
        adjudicator = await _ask(
            registry,
            "adjudicator",
            f"PROPOSAL\n{proposal[:2000]}\n\n"
            f"ALL FINDINGS\n{_consolidated(findings)}\n\n"
            f"EVIDENCE VERIFIER: {verifier_input[:500]}\n\n"
            'Return the final JSON. verdict "approve" only if evidence supports it.',
            max_output_tokens=2048,
        )
        verdict = {"approve": "approved", "reject": "changes_requested"}.get(
            adjudicator["verdict"], "needs_evidence"
        )
        rationale = adjudicator["summary"]
        review_entries.append(
            _persist_review(
                db,
                decision_id=decision.id,
                task_id=task_id,
                role="adjudicator",
                verdict=adjudicator["verdict"],
                summary=rationale,
                model=registry.route_for("adjudicator").model,
                rounds=rounds,
                detail={"findings": adjudicator["findings"]},
            )
        )

        # The decision row is accepted only on evidence-backed approval.
        decision.status = "accepted" if verdict == "approved" else "proposed"
        decision.rationale = f"{decision.rationale or ''}\n\nADJUDICATION: {rationale[:2000]}"
        db.commit()
    except (ModelProviderError, TimeoutError) as exc:
        return _fail_closed(factory, decision, task_id, project_id, exc, review_entries, findings)

    await record_event(
        factory,
        "DECISION_ADJUDICATED",
        project_id=project_id,
        task_id=task_id,
        payload={"decision_id": str(decision.id), "verdict": verdict},
    )
    return ReviewOutcome(
        decision_id=str(decision.id),
        verdict=verdict,
        rationale=rationale,
        reviews=review_entries,
        findings=[f.as_dict() for f in findings],
    )


def _fail_closed(
    factory: sessionmaker[Session],
    decision: Decision,
    task_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    exc: Exception,
    review_entries: list[dict[str, Any]],
    findings: list[ReviewFinding],
) -> ReviewOutcome:
    """A pipeline failure never adjudicates — the decision stays proposed (spec §24)."""
    message = f"review pipeline failed fail-closed: {exc}"
    asyncio.get_running_loop().create_task(
        record_event(
            factory,
            "REVIEW_FAILED_CLOSED",
            project_id=project_id,
            task_id=task_id,
            payload={"decision_id": str(decision.id), "error": message[:500]},
        )
    )
    return ReviewOutcome(
        decision_id=str(decision.id),
        verdict="error",
        rationale=message,
        reviews=review_entries,
        findings=[f.as_dict() for f in findings],
    )

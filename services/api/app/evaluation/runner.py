"""Bounded evidence-audit runner over the existing authenticated artifact API.

This runner audits supplied observations; it does not run agents or attest that
an artifact proves behavior. Reports never change authoritative completion state.
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import Field

from app.evaluation.scorecard import (
    EvaluationEvidence,
    EvaluationScorecard,
    EvidenceModel,
    evaluate_evidence,
)

MAX_REPORT_BYTES = 1_048_576


class ArtifactClient(Protocol):
    def get(self, url: str) -> Any: ...
    def post(self, url: str, *, files: Any) -> Any: ...


class CaseDefinition(EvidenceModel):
    case_id: str = Field(min_length=1, max_length=100)
    case_version: str = Field(min_length=1, max_length=100)
    dataset_version: str = Field(min_length=1, max_length=100)
    requirement: str = Field(min_length=1, max_length=4000)
    mandatory_check_keys: tuple[str, ...] = Field(min_length=1, max_length=100)


class ModelConfiguration(EvidenceModel):
    provider: str = Field(default="unrecorded", max_length=100)
    model: str = Field(default="unrecorded", max_length=200)
    temperature: float | None = None
    fallback_model: str | None = Field(default=None, max_length=200)


class AuditRequest(EvidenceModel):
    project_id: uuid.UUID
    definition: CaseDefinition
    code_revision: str = Field(min_length=1, max_length=100)
    dirty_worktree: bool
    configuration_version: str = Field(min_length=1, max_length=100)
    model_configuration: ModelConfiguration = Field(default_factory=ModelConfiguration)
    evidence: EvaluationEvidence


class AuditReport(EvidenceModel):
    schema_version: Literal[1] = 1
    mode: Literal["supplied_evidence_audit"] = "supplied_evidence_audit"
    run_id: uuid.UUID
    started_at: datetime
    completed_at: datetime
    audit_duration_ms: float
    request: AuditRequest
    scorecard: EvaluationScorecard
    artifact_hashes: dict[str, str]
    limitation: str = (
        "Supplied observations, not independently executed work. Artifact existence and project "
        "association are checked; semantic validity, history completeness and real model quality "
        "are not attested. Unrecorded telemetry is unknown. No completion state is modified."
    )


def run_audit(client: ArtifactClient, request: AuditRequest) -> dict[str, Any]:
    """Persist a versioned scorecard; HTTP errors propagate, never become a PASS."""
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    evidence = request.evidence
    if len(evidence.checks) > 100:
        raise ValueError("Audit supports at most 100 checks")
    checks = {check.key: check for check in evidence.checks}
    required = request.definition.mandatory_check_keys
    if len(set(required)) != len(required):
        raise ValueError("Duplicate mandatory check keys")
    # Missing declared checks are facts, not unmeasured optional dimensions.
    from app.evaluation.scorecard import Check  # noqa: PLC0415

    reconciled = list(evidence.checks)
    for key in required:
        if key not in checks:
            reconciled.append(Check(key=key, dimension="evidence", passed=False))
        elif not checks[key].mandatory:
            reconciled[reconciled.index(checks[key])] = checks[key].model_copy(
                update={"mandatory": True}
            )
    evidence = evidence.model_copy(update={"checks": tuple(reconciled)})
    scorecard = evaluate_evidence(evidence)
    refs = {ref for check in evidence.checks for ref in check.evidence_refs}
    if len(refs) > 100:
        raise ValueError("Audit supports at most 100 unique artifact references")
    hashes: dict[str, str] = {}
    for ref in sorted(refs):
        if not ref.startswith("artifact://"):
            raise ValueError("Audit evidence must use artifact://UUID references")
        artifact_id = uuid.UUID(ref.removeprefix("artifact://"))
        response = client.get(f"/api/artifacts/{artifact_id}")
        response.raise_for_status()
        metadata = response.json()
        if metadata.get("project_id") != str(request.project_id):
            raise ValueError("Evidence artifact belongs to another project")
        hashes[ref] = str(metadata["sha256"])
    report = AuditReport(
        run_id=uuid.uuid4(),
        started_at=started_at,
        completed_at=datetime.now(UTC),
        audit_duration_ms=(time.perf_counter() - started) * 1000,
        request=request.model_copy(update={"evidence": evidence}),
        scorecard=scorecard,
        artifact_hashes=hashes,
    )
    encoded = report.model_dump_json().encode("utf-8")
    if len(encoded) > MAX_REPORT_BYTES:
        raise ValueError("Evaluation report exceeds 1 MiB")
    response = client.post(
        f"/api/projects/{request.project_id}/artifacts",
        files={"file": (f"evaluation-{report.run_id}.json", encoded, "application/json")},
    )
    response.raise_for_status()
    return {
        "run_id": str(report.run_id),
        "status": scorecard.status,
        "artifact_id": str(response.json()["id"]),
        "mode": report.mode,
    }

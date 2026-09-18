"""Pure fail-closed quality gates. Callers must collect evidence from trusted records.

This module does not authenticate evidence or execute work. A positive model
assessment is deliberately not an input: it cannot override deterministic facts.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

DIMENSIONS = (
    "requirement_understanding",
    "planning",
    "task_decomposition",
    "dependencies",
    "agent_selection",
    "context",
    "tools",
    "execution",
    "code_quality",
    "validation",
    "recovery",
    "requirement_coverage",
    "security",
    "evidence",
    "cost",
    "latency",
    "reproducibility",
)
Verdict = Literal["PASS", "FAIL", "UNKNOWN"]


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Check(EvidenceModel):
    key: str = Field(min_length=1, max_length=200)
    dimension: str = Field(min_length=1, max_length=50)
    mandatory: bool = True
    passed: bool | None = None
    evidence_refs: tuple[Annotated[str, Field(min_length=1, max_length=1024)], ...] = Field(
        default=(), max_length=100
    )


class EvaluationEvidence(EvidenceModel):
    checks: tuple[Check, ...] = Field(default=(), max_length=1000)
    execution_completed: bool | None = None
    security_violation: bool | None = None
    duration_ms: float | None = Field(default=None, ge=0)
    timeout_ms: float = Field(default=60000, gt=0)
    model_calls: int | None = Field(default=None, ge=0)
    max_model_calls: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    max_cost_usd: float = Field(default=0, ge=0)


class EvaluationScorecard(EvidenceModel):
    status: Verdict
    dimensions: dict[str, Verdict]
    failures: tuple[str, ...]
    requirement_coverage: float | None


def evaluate_evidence(evidence: EvaluationEvidence) -> EvaluationScorecard:
    """Unknown mandatory evidence blocks PASS; known hard failures produce FAIL."""
    dimensions: dict[str, Verdict] = dict.fromkeys(DIMENSIONS, "UNKNOWN")
    failures: list[str] = []
    unknown = False
    seen: set[str] = set()
    grouped: dict[str, list[Verdict]] = {}
    for check in evidence.checks:
        if check.key in seen or check.dimension not in dimensions:
            raise ValueError("Duplicate check key or unsupported quality dimension")
        seen.add(check.key)
        verdict: Verdict = (
            "FAIL"
            if check.passed is False
            else "PASS"
            if check.passed is True and check.evidence_refs
            else "UNKNOWN"
        )
        grouped.setdefault(check.dimension, []).append(verdict)
        if check.mandatory and verdict != "PASS":
            failures.append(f"{check.key}: {verdict}")
            unknown |= verdict == "UNKNOWN"
    for dimension, verdicts in grouped.items():
        dimensions[dimension] = (
            "FAIL" if "FAIL" in verdicts else "UNKNOWN" if "UNKNOWN" in verdicts else "PASS"
        )
    hard_failure = any(
        (c.mandatory and (c.passed is not True or not c.evidence_refs))
        or (c.dimension == "security" and c.passed is False)
        for c in evidence.checks
    )
    for check in evidence.checks:
        if check.dimension == "security" and check.passed is False and not check.mandatory:
            failures.append(f"{check.key}: FAIL")
    gates: dict[str, bool | None] = {
        "execution": evidence.execution_completed,
        "security": None
        if evidence.security_violation is None
        else not evidence.security_violation,
        "latency": None
        if evidence.duration_ms is None
        else evidence.duration_ms <= evidence.timeout_ms,
        "cost": False
        if (evidence.cost_usd is not None and evidence.cost_usd > evidence.max_cost_usd)
        or (evidence.model_calls is not None and evidence.model_calls > evidence.max_model_calls)
        else None
        if evidence.cost_usd is None or evidence.model_calls is None
        else True,
    }
    for dimension, passed in gates.items():
        verdict = "UNKNOWN" if passed is None else "PASS" if passed else "FAIL"
        prior = dimensions[dimension]
        if "FAIL" in (prior, verdict):
            dimensions[dimension] = "FAIL"
        elif dimension in grouped and prior == "UNKNOWN":
            dimensions[dimension] = "UNKNOWN"
        else:
            dimensions[dimension] = verdict
        if passed is not True:
            failures.append(f"{dimension}: {verdict}")
            hard_failure |= passed is False
            unknown |= passed is None
    mandatory = [c for c in evidence.checks if c.mandatory]
    if not mandatory:
        failures.append("evidence: no mandatory checks")
        unknown = True
    coverage = [c for c in mandatory if c.dimension == "requirement_coverage"]
    ratio = (
        sum(c.passed is True and bool(c.evidence_refs) for c in coverage) / len(coverage)
        if coverage
        else None
    )
    return EvaluationScorecard(
        status="FAIL" if hard_failure else "UNKNOWN" if unknown else "PASS",
        dimensions=dimensions,
        failures=tuple(failures),
        requirement_coverage=ratio,
    )

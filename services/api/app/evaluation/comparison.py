"""Outcome consistency and same-case audit comparisons; no aggregate quality score."""

from __future__ import annotations

from collections.abc import Sequence

from app.evaluation.runner import AuditReport


def repeatability(reports: Sequence[AuditReport]) -> str:
    if not 2 <= len(reports) <= 20:
        raise ValueError("Repeatability requires 2..20 observations")
    for report in reports[1:]:
        _compatible(reports[0], report, same_code=True)
    states = {report.scorecard.status for report in reports}
    if "PASS" in states and "FAIL" in states:
        return "FLAKY"
    if "FAIL" in states:
        return "FAIL"
    if "UNKNOWN" in states:
        return "UNKNOWN"
    return "PASS"


def _compatible(before: AuditReport, after: AuditReport, *, same_code: bool = False) -> None:
    a, b = before.request, after.request
    if (
        a.definition != b.definition
        or a.configuration_version != b.configuration_version
        or a.model_configuration != b.model_configuration
    ):
        raise ValueError("Cannot compare different cases, datasets or model configurations")
    if same_code and (a.code_revision != b.code_revision or a.dirty_worktree or b.dirty_worktree):
        raise ValueError("Repeatability needs the same clean code revision")
    old_limits = (a.evidence.timeout_ms, a.evidence.max_cost_usd, a.evidence.max_model_calls)
    new_limits = (b.evidence.timeout_ms, b.evidence.max_cost_usd, b.evidence.max_model_calls)
    if old_limits != new_limits:
        raise ValueError("Cannot compare changed budgets")


def compare(before: AuditReport, after: AuditReport) -> dict:
    _compatible(before, after)
    regressions: list[str] = []
    improvements: list[str] = []
    if before.scorecard.status == "PASS" and after.scorecard.status != "PASS":
        regressions.append("previously passing case no longer passes")
    if before.scorecard.status != "PASS" and after.scorecard.status == "PASS":
        improvements.append("previously non-passing case now passes")
    for dimension, verdict in before.scorecard.dimensions.items():
        current = after.scorecard.dimensions[dimension]
        if verdict == "PASS" and current != "PASS":
            regressions.append(f"{dimension}: {verdict} -> {current}")
    old_coverage = before.scorecard.requirement_coverage
    coverage = after.scorecard.requirement_coverage
    if old_coverage is not None and (coverage is None or coverage < old_coverage):
        regressions.append("requirement coverage decreased or became unknown")
    changes = {}
    for field in ("cost_usd", "model_calls", "duration_ms"):
        old = getattr(before.request.evidence, field)
        new = getattr(after.request.evidence, field)
        changes[field] = {
            "before": old,
            "after": new,
            "delta": None if old is None or new is None else new - old,
        }
    return {
        "regressions": regressions,
        "improvements": improvements,
        "changes": changes,
        "status": "FAIL" if regressions else "PASS",
        "limitation": "Comparison of supplied observations, not independent reruns.",
    }

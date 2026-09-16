"""Review pipeline parsing units (FR-017): fail-closed verdict resolution."""

from __future__ import annotations

from app.services.quality.review import _parse_review


def test_valid_review_json_parses() -> None:
    parsed = _parse_review(
        '{"verdict": "approve", "summary": "ok", '
        '"findings": [{"severity": "blocker", "claim": "x", "evidence": "y"}]}',
        "reviewer-1",
    )
    assert parsed["verdict"] == "approve"
    assert parsed["findings"][0]["severity"] == "blocker"


def test_unparsable_output_resolves_to_needs_evidence() -> None:
    parsed = _parse_review("I think this looks great!", "reviewer-1")
    assert parsed["verdict"] == "needs_evidence"
    assert "unparsable" in parsed["summary"]


def test_unknown_verdict_and_severity_are_normalized() -> None:
    parsed = _parse_review(
        '{"verdict": "LGTM", "findings": [{"severity": "catastrophic", "claim": "x"}]}',
        "reviewer-1",
    )
    assert parsed["verdict"] == "needs_evidence"  # unknown verdicts can never approve
    assert parsed["findings"][0]["severity"] == "minor"


def test_rehearsal_style_output_never_approves() -> None:
    parsed = _parse_review('{"decision": "run_commands", "commands": ["ls"]}', "reviewer-1")
    assert parsed["verdict"] == "needs_evidence"

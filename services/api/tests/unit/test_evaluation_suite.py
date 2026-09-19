"""The execution evaluator itself must fail closed, including skips and absent evidence."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.evaluation.dataset import CASES, digest, select
from app.evaluation.suite import Limits, classify, consistency, read_json, save


@pytest.mark.parametrize(
    "exit_code,timed_out,outcome,expected",
    [
        (0, False, "passed", "PASS"),
        (1, False, "failed", "FAIL"),
        (None, True, "passed", "ERROR"),
        (0, False, "skipped", "UNKNOWN"),
        (4, False, "passed", "ERROR"),
        (0, False, "failed", "FAIL"),
    ],
)
def test_classify(exit_code: int | None, timed_out: bool, outcome: str, expected: str) -> None:
    assert (
        classify(
            {"records": [{"phase": "call", "outcome": outcome}]},
            exit_code=exit_code,
            timed_out=timed_out,
        )
        == expected
    )


def test_empty_or_collection_error_never_passes() -> None:
    assert classify({}, exit_code=0, timed_out=False) == "ERROR"
    assert classify({"collection_errors": 1}, exit_code=0, timed_out=False) == "ERROR"


@pytest.mark.parametrize(
    "states,expected",
    [
        (["PASS", "PASS"], "PASS"),
        (["PASS", "FAIL"], "FLAKY"),
        (["PASS", "ERROR"], "ERROR"),
        (["PASS", "UNKNOWN"], "UNKNOWN"),
        (["NOT_RUN"], "NOT_RUN"),
        ([], "UNKNOWN"),
    ],
)
def test_consistency(states: list[str], expected: str) -> None:
    assert consistency(states) == expected


def test_limits_and_fixed_catalog() -> None:
    assert len(CASES) == 10 and len(digest()) == 64
    assert select(["EVAL-001"])[0].fast
    for ids in (["../../arbitrary.py"], ["EVAL-001", "EVAL-001"]):
        with pytest.raises(ValueError):
            select(ids)
    for kwargs in ({"repeats": 0}, {"repeats": 6}, {"run_timeout_seconds": 9999}):
        with pytest.raises(ValidationError):
            Limits(**kwargs)


def test_bounded_atomic_report(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    save(path, {"status": "RUNNING"})
    assert read_json(path)["status"] == "RUNNING"
    with pytest.raises(ValueError):
        save(path, {"text": "x" * 1_048_576})
    assert read_json(path)["status"] == "RUNNING"
    assert not path.with_name("report.json.partial").exists()


def sample_report() -> dict:
    return {
        "schema_version": 1,
        "mode": "offline_infrastructure",
        "run_id": "f5890d7b-a0d5-4ab9-9ec3-8b71fa87ae41",
        "dataset_version": "v1",
        "dataset_digest": "abc",
        "definitions": [{"case_id": "EVAL-001"}],
        "limits": {"repeats": 1},
        "results": [
            {
                "case_id": "EVAL-001",
                "repeat": 1,
                "status": "PASS",
                "duration_ms": 100,
                "process_exit_code": 0,
                "tests": [{"phase": "call", "outcome": "passed"}],
            }
        ],
        "cases": {"EVAL-001": "PASS"},
        "status": "PASS",
        "duration_ms": 100,
        "completed_at": "2026-09-17T00:00:00Z",
        "model_configuration": {},
        "limitation": "fixture",
    }


def test_suite_regression_and_corruption() -> None:
    import copy

    from app.evaluation.reports import compare_suites, validate

    before = sample_report()
    after = copy.deepcopy(before)
    after["results"][0]["status"] = "FAIL"
    with pytest.raises(ValueError, match="contradicts"):
        validate(after)
    after["results"][0]["tests"][0]["outcome"] = "failed"
    after["results"][0]["process_exit_code"] = 1
    after.update(cases={"EVAL-001": "FAIL"}, status="FAIL")
    assert compare_suites(before, after)["regressions"]
    assert compare_suites(after, before)["improvements"]
    after = copy.deepcopy(before)
    after["results"][0]["duration_ms"] = 3000
    assert compare_suites(before, after)["status"] == "FAIL"
    after["dataset_digest"] = "changed"
    with pytest.raises(ValueError, match="Incompatible"):
        compare_suites(before, after)


def test_suite_missing_repeat_rejected() -> None:
    from app.evaluation.reports import validate

    report = sample_report()
    report["limits"]["repeats"] = 2
    with pytest.raises(ValueError, match="Missing"):
        validate(report)


def _row(**overrides: object) -> dict:
    row: dict = {
        "case_id": "EVAL-001",
        "status": "FAIL",
        "failure_class": None,
        "timed_out": False,
        "collection_errors": 0,
        "tests": [],
    }
    row.update(overrides)
    return row


def test_triage_pass_needs_no_label() -> None:
    from app.evaluation.suite import triage_result

    assert triage_result(_row(status="PASS")) is None


def test_triage_hard_signals_win() -> None:
    from app.evaluation.suite import triage_result

    assert triage_result(_row(failure_class="BUDGET_EXCEEDED")) == "COST_FAILURE"
    assert triage_result(_row(failure_class="INFRASTRUCTURE_FAILURE")) == "INFRASTRUCTURE_FAILURE"
    assert triage_result(_row(failure_class="TIMEOUT")) == "PERFORMANCE_FAILURE"
    assert triage_result(_row(status="NOT_RUN")) == "INFRASTRUCTURE_FAILURE"
    assert triage_result(_row(status="ERROR", collection_errors=2)) == "INFRASTRUCTURE_FAILURE"


def test_triage_labels_failed_nodes_transparently() -> None:
    from app.evaluation.suite import triage_result

    def failed(*nodeids: str) -> dict:
        return _row(
            tests=[{"nodeid": node, "outcome": "failed"} for node in nodeids],
        )

    assert triage_result(failed("tests/unit/test_wave1_security.py::test_x")) == "SECURITY_FAILURE"
    assert (
        triage_result(failed("tests/integration/test_recovery_executor.py::test_y"))
        == "RECOVERY_FAILURE"
    )
    assert (
        triage_result(failed("tests/evals/test_golden.py::test_provider_fallback"))
        == "RECOVERY_FAILURE"  # fallback machinery, not the provider error itself
    )
    assert (
        triage_result(failed("tests/unit/test_context_and_models.py::test_openai_500"))
        == "MODEL_FAILURE"
    )
    assert (
        triage_result(failed("tests/integration/test_quality_overseer.py::test_z"))
        == "REQUIREMENT_COVERAGE_FAILURE"
    )
    assert (
        triage_result(failed("tests/integration/test_codeintel_retrieval.py::test_q"))
        == "CONTEXT_FAILURE"
    )
    assert (
        triage_result(failed("tests/integration/test_scheduler.py::test_dag"))
        == "TASK_DECOMPOSITION_FAILURE"
    )
    assert triage_result(failed("tests/evals/test_golden.py::test_seeded_python")) == (
        "EXECUTION_FAILURE"
    )


def test_triage_never_overrides_status() -> None:
    from app.evaluation.suite import triage_result

    row = _row(tests=[{"nodeid": "tests/unit/test_wave1_security.py::t", "outcome": "failed"}])
    assert row["status"] == "FAIL"
    assert triage_result(row) == "SECURITY_FAILURE"

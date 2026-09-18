"""Real evaluator command and durable report path, not fabricated result input."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from app.evaluation.reports import compare_suites, persist, summarize
from app.evaluation.suite import Limits, run


def test_real_fast_suite_repeated_and_persisted(project: tuple, tmp_path: Path) -> None:
    _app, client, project_id, _root = project
    result = asyncio.run(run(tmp_path / "report.json", fast=True, limits=Limits(repeats=2)))
    assert summarize(result)["counts"]["PASS"] == 1
    assert len(result["results"]) == 2
    assert compare_suites(result, result)["status"] == "PASS"
    uploaded = persist(client, uuid.UUID(project_id), result)
    response = client.get(f"/api/artifacts/{uploaded['artifact_id']}/content")
    response.raise_for_status()
    assert response.json() == result
    assert uploaded["sha256"]


def test_provider_attempt_budget_stops_fallback(tmp_path: Path) -> None:
    from app.core.config import Settings
    from app.evaluation.dataset import select
    from app.evaluation.isolation import database
    from app.evaluation.suite import _one

    # This case node is a unit fixture: it needs no tables, but never receives the live DB.
    case = select(["EVAL-006"])[0].model_copy(
        update={"nodes": ("tests/evals/test_golden.py::test_provider_fallback",)}
    )
    with database(Settings().database_url) as url:
        result = asyncio.run(_one(case, Path(__file__).resolve().parents[2], tmp_path, 30, url, 1))
    assert result["status"] == "FAIL"
    assert result["metrics"]["model_call_count"] == 1
    assert result["metrics"]["budget_exhausted"] is True
    assert result["metrics"]["provider_failure_count"] == 1

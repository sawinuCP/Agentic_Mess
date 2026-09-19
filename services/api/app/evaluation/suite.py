"""Bounded offline evaluation; fixed repository-owned tests, no generated command execution."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from app.evaluation.dataset import VERSION, Case, digest, select
from app.evaluation.scorecard import EvidenceModel
from app.runtime.runner import run_process

MAX_BYTES = 1_048_576


class Limits(EvidenceModel):
    repeats: int = Field(default=1, ge=1, le=5)
    run_timeout_seconds: int = Field(default=1200, ge=1, le=3600)
    case_timeout_seconds: int = Field(default=120, ge=1, le=300)
    model_calls_per_case: int = Field(default=100, ge=0, le=1000)
    model_calls_per_run: int = Field(default=500, ge=0, le=5000)


def classify(data: dict[str, Any], *, exit_code: int | None, timed_out: bool) -> str:
    if timed_out or exit_code not in (0, 1) or data.get("collection_errors"):
        return "ERROR"
    rows = data.get("records", [])
    if not rows or any(
        r.get("phase") not in ("setup", "call", "teardown")
        or r.get("outcome") not in ("passed", "failed", "skipped")
        for r in rows
    ):
        return "ERROR"
    if not any(r.get("phase") == "call" for r in rows):
        return "UNKNOWN" if all(r.get("outcome") == "skipped" for r in rows) else "ERROR"
    if exit_code == 1 or any(r.get("outcome") == "failed" for r in rows):
        return "FAIL"
    if any(r.get("outcome") == "skipped" for r in rows):
        return "UNKNOWN"
    return "PASS"


def consistency(states: list[str]) -> str:
    values = set(states)
    if "PASS" in values and "FAIL" in values:
        return "FLAKY"
    for state in ("ERROR", "FAIL", "UNKNOWN", "NOT_RUN"):
        if state in values:
            return state
    return "PASS" if values else "UNKNOWN"


# Failure triage (§39): deterministic labels for failed rows. Hard signals
# (budget/timeout/infra) win over heuristics; otherwise the failed test node
# ids decide — transparent and unit-tested, never a model judgment, and never
# overriding the row status itself.
_TRIAGE_SECURITY_HINTS = (
    "secur",
    "auth",
    "secret",
    "ssrf",
    "unauth",
    "denies",
    "forbidden",
    "violation",
    "sanitiz",
    "private",
    "permission",
)
_TRIAGE_PLANNER_HINTS = ("plann",)
_TRIAGE_DECOMPOSITION_HINTS = ("schedul", "dag", "decompos", "task_graph")
_TRIAGE_AGENT_HINTS = ("spawn", "agent_selection", "wrong-role")
_TRIAGE_RECOVERY_HINTS = ("recover", "retry", "fallback", "dependenc", "hitl", "replan", "debugger")
_TRIAGE_MODEL_HINTS = ("provider", "model", "registry", "openai", "completion")
_TRIAGE_COVERAGE_HINTS = ("coverage", "traceability", "requirement", "overseer")
_TRIAGE_VALIDATION_HINTS = ("gates", "scorecard", "comparison", "audit", "validat")
_TRIAGE_COST_HINTS = ("cost", "budget", "ledger", "token")
_TRIAGE_CONTEXT_HINTS = ("context", "retrieval", "codeintel", "index", "search", "symbol")
_TRIAGE_TOOL_HINTS = ("tool", "runner", "toolchain", "browser", "mcp", "gateway")


def triage_result(row: dict[str, Any]) -> str | None:
    """Triage class for a suite result row (None when the row passed)."""
    status = row.get("status")
    if status == "PASS":
        return None
    if status == "NOT_RUN":
        return "INFRASTRUCTURE_FAILURE"
    failure_class = row.get("failure_class")
    if failure_class == "BUDGET_EXCEEDED":
        return "COST_FAILURE"
    if failure_class == "INFRASTRUCTURE_FAILURE":
        return "INFRASTRUCTURE_FAILURE"
    if failure_class == "TIMEOUT" or row.get("timed_out"):
        return "PERFORMANCE_FAILURE"
    if status == "ERROR" or row.get("collection_errors"):
        return "INFRASTRUCTURE_FAILURE"
    haystack = "\n".join(
        str(t.get("nodeid", "")) for t in row.get("tests", []) if t.get("outcome") == "failed"
    ).lower()

    def hits(hints: tuple[str, ...]) -> bool:
        return any(hint in haystack for hint in hints)

    if hits(_TRIAGE_SECURITY_HINTS):
        return "SECURITY_FAILURE"
    if hits(_TRIAGE_PLANNER_HINTS):
        return "PLANNER_FAILURE"
    if hits(_TRIAGE_DECOMPOSITION_HINTS):
        return "TASK_DECOMPOSITION_FAILURE"
    if hits(_TRIAGE_AGENT_HINTS):
        return "AGENT_SELECTION_FAILURE"
    if hits(_TRIAGE_RECOVERY_HINTS):
        return "RECOVERY_FAILURE"
    if hits(_TRIAGE_MODEL_HINTS):
        return "MODEL_FAILURE"
    if hits(_TRIAGE_COVERAGE_HINTS):
        return "REQUIREMENT_COVERAGE_FAILURE"
    if hits(_TRIAGE_VALIDATION_HINTS):
        return "VALIDATION_FAILURE"
    if hits(_TRIAGE_COST_HINTS):
        return "COST_FAILURE"
    if hits(_TRIAGE_CONTEXT_HINTS):
        return "CONTEXT_FAILURE"
    if hits(_TRIAGE_TOOL_HINTS):
        return "TOOL_SELECTION_FAILURE"
    return "EXECUTION_FAILURE"


def read_json(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Report exceeds 1 MiB")
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object")
    return result


def save(path: Path, report: dict[str, Any]) -> None:
    data = json.dumps(report, indent=2, allow_nan=False).encode()
    if len(data) > MAX_BYTES:
        raise ValueError("Report exceeds 1 MiB")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_bytes(data)
    temporary.replace(path)


def revision(root: Path) -> dict[str, Any]:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True, check=True, timeout=10
        ).stdout.strip()

    return {
        "code_revision": git("rev-parse", "HEAD"),
        "dirty_worktree": bool(git("status", "--porcelain")),
    }


async def _one(
    case: Case,
    root: Path,
    directory: Path,
    timeout: float,
    database_url: str,
    model_limit: int,
) -> dict[str, Any]:
    target = directory / "result.json"
    environment = {
        "HARNESS_EVAL_RESULT": str(target),
        "HARNESS_EVAL_MODEL_LIMIT": str(model_limit),
        "HARNESS_ENVIRONMENT": "test",
        "HARNESS_ARTIFACTS_DIR": str(directory / "artifacts"),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "GOTOOLCHAIN": "local",
        "GOPROXY": "off",
        "GOSUMDB": "off",
    }
    environment["HARNESS_DATABASE_URL"] = database_url
    started = time.perf_counter()
    result = await run_process(
        [
            sys.executable,
            "-m",
            "pytest",
            *case.nodes,
            "-q",
            "--tb=no",
            "-p",
            "app.evaluation.pytest_plugin",
            "-p",
            "anyio.pytest_plugin",
            "-p",
            "no:cacheprovider",
        ],
        root,
        timeout_seconds=timeout,
        output_limit=4096,
        env_extra=environment,
    )
    data = read_json(target) if target.is_file() else {}
    return {
        "case_id": case.case_id,
        "case_version": case.case_version,
        "status": classify(data, exit_code=result.exit_code, timed_out=result.timed_out),
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
        "timed_out": result.timed_out,
        "tests": data.get("records", []),
        "collection_errors": data.get("collection_errors", 0),
        "process_exit_code": result.exit_code,
        "metrics": data.get("metrics"),
        "model_routes": data.get("model_routes", []),
        "metrics_scope": "Provider attempts (including fallback) and tool policy checks; "
        "includes expected failures, not live execution-ledger totals. Tokens are estimates.",
        "failure_class": "TIMEOUT"
        if result.timed_out
        else ("BUDGET_EXCEEDED" if (data.get("metrics") or {}).get("budget_exhausted") else None),
    }


async def run(
    output: Path,
    *,
    case_ids: list[str] | None = None,
    fast: bool = False,
    limits: Limits | None = None,
) -> dict[str, Any]:
    limits = limits or Limits()
    cases = select(case_ids, fast=fast)
    root = Path(__file__).resolve().parents[2]
    if not (root / "tests").is_dir():
        raise ValueError("Evaluation requires a source checkout with tests")
    started = time.perf_counter()
    report: dict[str, Any] = {
        "schema_version": 1,
        "mode": "offline_infrastructure",
        "run_id": str(uuid.uuid4()),
        "dataset_version": VERSION,
        "dataset_digest": digest(),
        **revision(root),
        "configuration_version": "offline-1",
        "limits": limits.model_dump(),
        "model_configuration": {"external_calls_allowed": False, "provider": "rehearsal/fakes"},
        "started_at": datetime.now(UTC).isoformat(),
        "completed_at": None,
        "status": "RUNNING",
        "definitions": [c.model_dump(mode="json") for c in cases],
        "results": [],
        "limitation": "Infrastructure checks with scripted repairs, not autonomous AI quality. "
        "No model-assisted verdicts. Uncollected telemetry is unknown. "
        "Tests run serially; fixtures use normal tool policy and sanitized environments.",
    }
    save(output, report)
    from app.core.config import Settings  # noqa: PLC0415
    from app.evaluation.isolation import database  # noqa: PLC0415

    with database(Settings().database_url) as database_url:
        migration = await run_process(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            root,
            timeout_seconds=min(60, limits.run_timeout_seconds),
            output_limit=4096,
            env_extra={"HARNESS_DATABASE_URL": database_url},
        )
        if migration.exit_code != 0:
            report.update(status="ERROR", failure_class="INFRASTRUCTURE_FAILURE")
            save(output, report)
            return report
        for repeat in range(limits.repeats):
            for case in cases:
                remaining = limits.run_timeout_seconds - (time.perf_counter() - started)
                if remaining <= 0:
                    row = {
                        "case_id": case.case_id,
                        "status": "NOT_RUN",
                        "duration_ms": 0,
                        "failure_class": "TIMEOUT",
                    }
                else:
                    with tempfile.TemporaryDirectory(prefix="harness-eval-") as directory:
                        try:
                            row = await _one(
                                case,
                                root,
                                Path(directory),
                                min(remaining, limits.case_timeout_seconds, case.timeout_seconds),
                                database_url,
                                min(
                                    limits.model_calls_per_case,
                                    max(
                                        0,
                                        limits.model_calls_per_run
                                        - sum(
                                            (r.get("metrics") or {}).get("model_call_count", 0)
                                            for r in report["results"]
                                        ),
                                    ),
                                ),
                            )
                        except (OSError, ValueError):
                            row = {
                                "case_id": case.case_id,
                                "status": "ERROR",
                                "duration_ms": 0,
                                "failure_class": "INFRASTRUCTURE_FAILURE",
                            }
                report["results"].append({"repeat": repeat + 1, **row})
                save(output, report)
    for row in report["results"]:
        # Triage labels ride the persisted row (additive; never rewrites status).
        row["triage"] = triage_result(row)
    save(output, report)
    report["cases"] = {
        c.case_id: consistency(
            [r["status"] for r in report["results"] if r["case_id"] == c.case_id]
        )
        for c in cases
    }
    report["status"] = "PASS" if all(s == "PASS" for s in report["cases"].values()) else "FAIL"
    report["completed_at"] = datetime.now(UTC).isoformat()
    report["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
    save(output, report)
    return report

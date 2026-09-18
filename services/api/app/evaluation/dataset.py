"""Versioned, fixed test catalog. Selections never accept arbitrary test paths or commands."""

from __future__ import annotations

import hashlib
import json

from pydantic import Field

from app.evaluation.scorecard import EvidenceModel


class Case(EvidenceModel):
    case_id: str
    name: str
    requirement: str
    nodes: tuple[str, ...]
    dimensions: tuple[str, ...]
    case_version: str = "1"
    timeout_seconds: int = Field(default=120, ge=1, le=300)
    fast: bool = False


def _case(
    number: int,
    name: str,
    requirement: str,
    nodes: tuple[str, ...],
    dimensions: tuple[str, ...],
    *,
    fast: bool = False,
) -> Case:
    return Case(
        case_id=f"EVAL-{number:03}",
        name=name,
        requirement=requirement,
        nodes=nodes,
        dimensions=dimensions,
        fast=fast,
    )


VERSION = "offline-infrastructure-v1"
CASES = (
    _case(
        1,
        "Simple implementation",
        "A seeded Python defect fails an independent oracle; "
        "a scripted repair through the tool gateway passes the same oracle.",
        ("tests/evals/test_golden.py::test_seeded_python",),
        ("execution", "validation", "evidence"),
        fast=True,
    ),
    _case(
        2,
        "Multi-file implementation",
        "Seeded TypeScript and Go fixtures fail before repair "
        "and pass afterward without modifying protected inputs.",
        (
            "tests/evals/test_golden.py::test_seeded_typescript",
            "tests/evals/test_golden.py::test_seeded_go",
        ),
        ("execution", "validation"),
    ),
    _case(
        3,
        "Independent parallel tasks",
        "Scheduler admits independent same-role tasks; "
        "actual child execution intervals overlap and outputs stay isolated.",
        (
            "tests/integration/test_scheduler.py",
            "tests/evals/test_golden.py::test_parallel_execution",
        ),
        ("agent_selection", "execution"),
    ),
    _case(
        4,
        "Dependency chain",
        "A-B-C dependency readiness and cycles are checked by the "
        "existing DAG; persisted dependent lookup returns the correct successors.",
        (
            "tests/unit/test_tasks_graph.py",
            "tests/integration/test_recovery_executor.py::test_task_dependents_resolves_the_graph",
        ),
        ("planning", "dependencies", "task_decomposition"),
    ),
    _case(
        5,
        "Intentional test failure",
        "Classify a real failed command, execute idempotent "
        "debugger/replan activities and prove the recovery ladder is bounded.",
        (
            "tests/integration/test_durable_activities.py",
            "tests/integration/test_recovery_executor.py",
            "tests/unit/test_recovery.py",
        ),
        ("recovery", "validation"),
    ),
    _case(
        6,
        "Provider/model failure",
        "Inject provider outage and verify bounded registry "
        "fallback; exhausted task budgets block execution.",
        (
            "tests/evals/test_golden.py::test_provider_fallback",
            "tests/integration/test_codeintel_costs.py",
            "tests/unit/test_recovery.py::test_hard_policy_failures_never_retry",
        ),
        ("recovery", "cost"),
    ),
    _case(
        7,
        "Context retrieval challenge",
        "Rank a relevant symbol above unrelated UI "
        "symbols and enforce context tier ordering and token budgets.",
        ("tests/integration/test_codeintel_retrieval.py", "tests/unit/test_context_and_models.py"),
        ("context",),
    ),
    _case(
        8,
        "Large repository/search",
        "Index a deterministic 200-file repository; search "
        "finds the correct symbol; modifying one file only reindexes that file.",
        ("tests/evals/test_golden.py::test_large_repository",),
        ("context", "execution"),
    ),
    _case(
        9,
        "Security-sensitive task",
        "Existing auth, stream scoping, secret sanitization "
        "and private-destination guards remain enforced. No exploit execution is performed.",
        (
            "tests/unit/test_wave1_security.py",
            "tests/unit/test_agent_gateway.py",
            "tests/integration/test_wave1_auth.py",
            "tests/integration/test_realtime_stream.py",
        ),
        ("security", "tools"),
    ),
    _case(
        10,
        "Requirement coverage",
        "Four verified criteria out of five still block "
        "completion; missing evidence and security violations remain hard failures.",
        (
            "tests/evals/test_golden.py::test_incomplete_coverage",
            "tests/integration/test_quality_overseer.py",
            "tests/integration/test_quality_gates.py",
            "tests/unit/test_evaluation_scorecard.py",
        ),
        ("requirement_coverage", "security", "evidence"),
    ),
)


def digest() -> str:
    data = json.dumps([c.model_dump(mode="json") for c in CASES], sort_keys=True).encode()
    return hashlib.sha256(data).hexdigest()


def select(case_ids: list[str] | None = None, *, fast: bool = False) -> list[Case]:
    if case_ids and (
        len(set(case_ids)) != len(case_ids) or set(case_ids) - {c.case_id for c in CASES}
    ):
        raise ValueError("Unknown or duplicate case ID")
    selected = [
        c for c in CASES if (not case_ids or c.case_id in case_ids) and (not fast or c.fast)
    ]
    if not selected:
        raise ValueError("Empty evaluation selection")
    return selected

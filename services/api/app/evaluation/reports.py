"""Offline suite reports, durable artifact persistence and regression comparisons."""

from __future__ import annotations

import json
import statistics
import uuid
from typing import Any

from app.evaluation.runner import ArtifactClient
from app.evaluation.suite import MAX_BYTES, classify, consistency

STATES = {"PASS", "FAIL", "ERROR", "UNKNOWN", "NOT_RUN", "FLAKY"}


def validate(report: dict[str, Any]) -> None:
    if report.get("schema_version") != 1 or report.get("mode") != "offline_infrastructure":
        raise ValueError("Unsupported suite report")
    definitions = report.get("definitions", [])
    if not 1 <= len(definitions) <= 10 or len(report.get("results", [])) > 50:
        raise ValueError("Invalid suite bounds")
    ids = [c["case_id"] for c in definitions]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate definitions")
    seen: set[tuple[str, int]] = set()
    for row in report["results"]:
        key = (row["case_id"], row["repeat"])
        if key in seen or key[0] not in ids or row["status"] not in STATES:
            raise ValueError("Invalid or duplicate case result")
        seen.add(key)
        if row["status"] in ("PASS", "FAIL", "UNKNOWN"):
            derived = classify(
                {
                    "records": row.get("tests", []),
                    "collection_errors": row.get("collection_errors", 0),
                },
                exit_code=row.get("process_exit_code"),
                timed_out=row.get("timed_out", False),
            )
            if derived != row["status"]:
                raise ValueError("Case verdict contradicts saved test outcomes")
        duration = row.get("duration_ms")
        if not isinstance(duration, (int, float)) or not 0 <= duration < float("inf"):
            raise ValueError("Invalid case duration")
    if not report.get("completed_at"):
        raise ValueError("Run did not complete")
    repeats = report["limits"]["repeats"]
    if not 1 <= repeats <= 5 or seen != {(i, r) for i in ids for r in range(1, repeats + 1)}:
        raise ValueError("Missing evaluation repetitions")
    cases = {
        i: consistency([r["status"] for r in report["results"] if r["case_id"] == i]) for i in ids
    }
    if report.get("cases") != cases:
        raise ValueError("Case summary contradicts evidence")
    if report["status"] != ("PASS" if all(s == "PASS" for s in cases.values()) else "FAIL"):
        raise ValueError("Run summary contradicts evidence")


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    validate(report)
    return {
        "run_id": report["run_id"],
        "status": report["status"],
        "dataset_version": report["dataset_version"],
        "cases": report["cases"],
        "counts": {s: list(report["cases"].values()).count(s) for s in sorted(STATES)},
        "duration_ms": report["duration_ms"],
        "limitation": report["limitation"],
    }


def compare_suites(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    latency_ratio: float = 1.5,
    latency_floor_ms: float = 1000,
) -> dict[str, Any]:
    validate(before)
    validate(after)
    if latency_ratio <= 1 or latency_floor_ms < 0:
        raise ValueError("Invalid latency regression threshold")
    for key in ("dataset_version", "dataset_digest", "definitions", "limits"):
        if before[key] != after[key]:
            raise ValueError("Incompatible datasets, selections or budgets")
    regressions = []
    improvements = []
    changes = {}
    for case, old_status in before["cases"].items():
        new_status = after["cases"][case]
        if old_status == "PASS" and new_status != "PASS":
            regressions.append(f"{case}: {old_status} -> {new_status}")
        if old_status != "PASS" and new_status == "PASS":
            improvements.append(case)
        old = statistics.median(r["duration_ms"] for r in before["results"] if r["case_id"] == case)
        new = statistics.median(r["duration_ms"] for r in after["results"] if r["case_id"] == case)
        changes[case] = {"before_ms": old, "after_ms": new, "delta_ms": new - old}
        if new > old * latency_ratio and new - old > latency_floor_ms:
            regressions.append(f"{case}: latency threshold exceeded")
    return {
        "status": "FAIL" if regressions else "PASS",
        "regressions": regressions,
        "improvements": improvements,
        "changes": changes,
        "configuration_changed": before["model_configuration"] != after["model_configuration"],
        "limitation": "Infrastructure outcomes only; timings include pytest startup.",
    }


def persist(
    client: ArtifactClient, project_id: uuid.UUID, report: dict[str, Any]
) -> dict[str, Any]:
    validate(report)
    encoded = json.dumps(report, allow_nan=False).encode()
    if len(encoded) > MAX_BYTES:
        raise ValueError("Report exceeds 1 MiB")
    response = client.post(
        f"/api/projects/{project_id}/artifacts",
        files={
            "file": (
                f"evaluation-suite-{uuid.UUID(report['run_id'])}.json",
                encoded,
                "application/json",
            )
        },
    )
    response.raise_for_status()
    metadata = response.json()
    return {
        "status": report["status"],
        "run_id": report["run_id"],
        "artifact_id": metadata["id"],
        "sha256": metadata["sha256"],
    }

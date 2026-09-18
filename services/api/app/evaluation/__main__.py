"""Offline infrastructure evaluations and supplied-evidence audits (separate report modes)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from app.evaluation.comparison import compare
from app.evaluation.runner import MAX_REPORT_BYTES, AuditReport, AuditRequest, run_audit


def read_bounded(path: Path) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(MAX_REPORT_BYTES + 1)
    if len(data) > MAX_REPORT_BYTES:
        raise ValueError("Input exceeds 1 MiB")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list fixed offline evaluation cases")
    execution = commands.add_parser("run", help="execute the offline infrastructure dataset")
    execution.add_argument("--output", type=Path, required=True)
    execution.add_argument("--case", action="append", dest="case_ids")
    execution.add_argument("--fast", action="store_true")
    execution.add_argument("--full", action="store_true", help="all offline cases, no paid models")
    execution.add_argument("--repeats", type=int, default=1)
    execution.add_argument("--timeout", type=int, default=1200)
    execution.add_argument("--case-timeout", type=int, default=120)
    execution.add_argument("--model-calls-per-case", type=int, default=100)
    execution.add_argument("--model-calls-per-run", type=int, default=500)
    publication = commands.add_parser("persist", help="upload a completed suite via artifact API")
    publication.add_argument("input", type=Path)
    publication.add_argument("--project", required=True)
    publication.add_argument("--api", default="http://localhost:8000")
    run = commands.add_parser("audit", help="persist one supplied-evidence audit through the API")
    run.add_argument("input", type=Path)
    run.add_argument("--api", default="http://localhost:8000")
    report = commands.add_parser("report", help="read a saved audit JSON report")
    report.add_argument("input", type=Path)
    comparison = commands.add_parser("compare")
    comparison.add_argument("before", type=Path)
    comparison.add_argument("after", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "list":
            from app.evaluation.dataset import CASES, VERSION  # noqa: PLC0415

            print(
                json.dumps({"dataset": VERSION, "cases": [c.model_dump() for c in CASES]}, indent=2)
            )
            return 0
        if args.command == "run":
            from app.evaluation.suite import Limits  # noqa: PLC0415
            from app.evaluation.suite import run as execute_suite

            if args.fast and args.full:
                raise ValueError("Choose fast or full, not both")
            result = asyncio.run(
                execute_suite(
                    args.output,
                    case_ids=args.case_ids,
                    fast=args.fast,
                    limits=Limits(
                        repeats=args.repeats,
                        run_timeout_seconds=args.timeout,
                        case_timeout_seconds=args.case_timeout,
                        model_calls_per_case=args.model_calls_per_case,
                        model_calls_per_run=args.model_calls_per_run,
                    ),
                )
            )
            print(
                json.dumps(
                    {k: result.get(k) for k in ("run_id", "status", "cases", "duration_ms")},
                    indent=2,
                )
            )
            return 0 if result["status"] == "PASS" else 1
        if args.command == "compare":
            from app.evaluation.reports import compare_suites  # noqa: PLC0415

            before = json.loads(read_bounded(args.before))
            after = json.loads(read_bounded(args.after))
            result = (
                compare_suites(before, after)
                if before.get("mode") == "offline_infrastructure"
                else compare(AuditReport.model_validate(before), AuditReport.model_validate(after))
            )
        elif args.command == "report":
            from app.evaluation.reports import summarize  # noqa: PLC0415

            data = json.loads(read_bounded(args.input))
            if data.get("mode") == "offline_infrastructure":
                result = summarize(data)
            else:
                audit = AuditReport.model_validate(data)
                result = {
                    "run_id": str(audit.run_id),
                    "status": audit.scorecard.status,
                    "scorecard": audit.scorecard.model_dump(),
                    "limitation": audit.limitation,
                }
        else:
            parsed = urlsplit(args.api)
            if (
                parsed.scheme not in ("http", "https")
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("API URL must not contain credentials, query or fragment")
            if parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
                raise ValueError("Non-loopback API requires HTTPS")
            token = os.environ.get("HARNESS_API_TOKEN", "")
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            with httpx.Client(
                base_url=args.api, headers=headers, timeout=10, follow_redirects=False
            ) as client:
                if args.command == "persist":
                    import uuid  # noqa: PLC0415

                    from app.evaluation.reports import persist  # noqa: PLC0415

                    result = persist(
                        client, uuid.UUID(args.project), json.loads(read_bounded(args.input))
                    )
                else:
                    result = run_audit(
                        client, AuditRequest.model_validate_json(read_bounded(args.input))
                    )
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "PASS" else 1
    except (ValueError, ValidationError, OSError, httpx.HTTPError) as exc:
        # Never print the HTTP request, input document or credentials.
        print(json.dumps({"status": "ERROR", "error_type": type(exc).__name__}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

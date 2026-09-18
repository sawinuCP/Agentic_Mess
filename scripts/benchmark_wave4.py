"""Local Wave 4 benchmarks. No model calls; generated DB rows are rolled back.

Run using the repository virtualenv. Reports go to stdout unless --output is set.
Only the selected task-list and process-capture paths are measured, not full scale.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import tempfile
import time
import tracemalloc
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from sqlalchemy import event  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.db.base import build_engine  # noqa: E402
from app.db.models import Project, Task, TaskAttempt, TaskDependency  # noqa: E402
from app.runtime.runner import run_process  # noqa: E402
from app.services.planning.tasks import list_tasks  # noqa: E402


def positive(value: str) -> int:
    number = int(value)
    if not 1 <= number <= 1000:
        raise argparse.ArgumentTypeError("expected a value between 1 and 1000")
    return number


def percentiles(samples: list[float]) -> dict[str, float]:
    ordered = sorted(samples)
    return {
        f"p{p}_ms": round(ordered[math.ceil(p / 100 * len(ordered)) - 1], 3) for p in (50, 95, 99)
    }


def tasks_benchmark(sizes: list[int], samples: int) -> list[dict[str, Any]]:
    engine = build_engine(Settings().database_url)
    reports = []
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                with Session(bind=connection) as db:
                    namespace = uuid.uuid4()
                    project = Project(
                        id=namespace,
                        name="wave4-rollback-benchmark",
                        root_path=str(Path(tempfile.gettempdir()) / str(namespace)),
                    )
                    db.add(project)
                    db.flush()
                    total = 0
                    task_ids: list[uuid.UUID] = []
                    for size in sorted(set(sizes)):
                        tasks = [
                            Task(
                                id=uuid.uuid5(namespace, str(i)),
                                project_id=namespace,
                                title=f"Task {i}",
                                request="reproducible benchmark",
                                priority=i % 5,
                            )
                            for i in range(total, size)
                        ]
                        db.add_all(tasks)
                        db.flush()
                        for task in tasks:
                            if task_ids:
                                db.add(
                                    TaskDependency(task_id=task.id, depends_on_task_id=task_ids[-1])
                                )
                            task_ids.append(task.id)
                            db.add(
                                TaskAttempt(task_id=task.id, attempt_number=1, outcome="success")
                            )
                        db.flush()
                        total = size
                        query_count = [0]

                        def count(*_args: Any, counter: list[int] = query_count) -> None:
                            counter[0] += 1

                        timings = []
                        counts = []
                        list_tasks(db, namespace, None)  # warm-up excluded
                        event.listen(connection, "before_cursor_execute", count)
                        try:
                            for _ in range(samples):
                                query_count[0] = 0
                                started = time.perf_counter()
                                rows = list_tasks(db, namespace, None)
                                timings.append((time.perf_counter() - started) * 1000)
                                counts.append(query_count[0])
                                assert len(rows) == size
                                assert all(len(row.attempts) == 1 for row in rows)
                        finally:
                            event.remove(connection, "before_cursor_execute", count)
                        reports.append(
                            {
                                "tasks": size,
                                "samples": samples,
                                "max_queries": max(counts),
                                **percentiles(timings),
                            }
                        )
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
    return reports


async def output_benchmark(sizes: list[int]) -> list[dict[str, Any]]:
    reports = []
    for mib in sizes:
        tracemalloc.start()
        try:
            started = time.perf_counter()
            result = await run_process(
                [
                    sys.executable,
                    "-c",
                    "import sys; chunk=b'x'*65536; "
                    f"[sys.stdout.buffer.write(chunk) for _ in range({mib}*16)]",
                ],
                cwd=tempfile.gettempdir(),
                output_limit=1000,
            )
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert result.exit_code == 0 and result.stdout == "x" * 1000 and result.truncated
        reports.append(
            {
                "output_mib": mib,
                "peak_python_mib": round(peak / 1048576, 3),
                "seconds": round(time.perf_counter() - started, 3),
            }
        )
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", nargs="+", type=positive, default=[10, 100, 500])
    parser.add_argument("--output-mib", nargs="+", type=positive, default=[1, 16, 64])
    parser.add_argument("--samples", type=positive, default=20)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {
        "task_queries": tasks_benchmark(args.tasks, args.samples),
        "process_capture": asyncio.run(output_benchmark(args.output_mib)),
    }
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()

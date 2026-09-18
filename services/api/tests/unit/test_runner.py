"""Process runner behaviour: exit codes, timeout kill, truncation, missing exe."""

from __future__ import annotations

import asyncio
import sys
import tracemalloc
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar
from unittest.mock import AsyncMock, patch

import pytest

from app.runtime.runner import run_process

PY = sys.executable
_T = TypeVar("_T")


def run(coro: Coroutine[Any, Any, _T]) -> _T:  # keeps tests plugin-free
    return asyncio.run(coro)


def test_run_captures_output(tmp_path: Path) -> None:
    result = run(run_process([PY, "-c", "print('hi')"], cwd=tmp_path))
    assert result.exit_code == 0
    assert "hi" in result.stdout
    assert result.timed_out is False


def test_nonzero_exit_code(tmp_path: Path) -> None:
    result = run(run_process([PY, "-c", "import sys; sys.exit(3)"], cwd=tmp_path))
    assert result.exit_code == 3


def test_stderr_capture(tmp_path: Path) -> None:
    result = run(run_process([PY, "-c", "import sys; sys.stderr.write('oops')"], cwd=tmp_path))
    assert "oops" in result.stderr


def test_timeout_kills_process(tmp_path: Path) -> None:
    result = run(
        run_process([PY, "-c", "import time; time.sleep(30)"], cwd=tmp_path, timeout_seconds=1)
    )
    assert result.timed_out is True
    assert result.exit_code is None


def test_output_truncation(tmp_path: Path) -> None:
    result = run(run_process([PY, "-c", "print('x' * 10000)"], cwd=tmp_path, output_limit=100))
    assert result.truncated is True
    assert len(result.stdout) == 100


def test_missing_executable_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        run(run_process(["definitely-missing-exe-123"], cwd=tmp_path))


@pytest.mark.parametrize("output_limit", [0, 1000])
def test_large_dual_stream_output_has_bounded_capture(tmp_path: Path, output_limit: int) -> None:
    # 16 MiB on each pipe previously allocated >32 MiB before truncation.
    script = (
        "import sys; chunk=b'x'*65536; "
        "[(sys.stdout.buffer.write(chunk), sys.stderr.buffer.write(chunk)) "
        "for _ in range(256)]"
    )
    tracemalloc.start()
    try:
        result = run(run_process([PY, "-c", script], cwd=tmp_path, output_limit=output_limit))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result.exit_code == 0
    assert result.stdout == result.stderr == "x" * output_limit
    assert result.truncated
    assert peak < 8 * 1024 * 1024, "capture must not scale with total emitted output"


def test_capture_decodes_split_utf8_and_marks_exact_limit() -> None:
    from app.runtime.runner import _OutputCapture

    async def exercise() -> None:
        stream = AsyncMock(spec=asyncio.StreamReader)
        stream.read.side_effect = [b"\xe2", b"\x82\xac", b"\xff", b""]
        capture = _OutputCapture(2)
        await capture.drain(stream)
        assert "".join(capture.parts) == "\u20ac\ufffd"
        assert not capture.truncated

    run(exercise())


def test_negative_output_limit_rejected_before_spawn(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="output_limit"):
        run(run_process([PY, "-c", "pass"], cwd=tmp_path, output_limit=-1))


def test_timeout_preserves_output_prefix(tmp_path: Path) -> None:
    result = run(
        run_process(
            [PY, "-c", "import time; print('before timeout', flush=True); time.sleep(30)"],
            cwd=tmp_path,
            timeout_seconds=1,
        )
    )
    assert result.timed_out
    assert "before timeout" in result.stdout


def test_cancellation_reaps_child(tmp_path: Path) -> None:
    async def exercise() -> None:
        created: list[asyncio.subprocess.Process] = []
        ready = asyncio.Event()
        original = asyncio.create_subprocess_exec

        async def spawn(*args: Any, **kwargs: Any) -> asyncio.subprocess.Process:
            proc = await original(*args, **kwargs)
            created.append(proc)
            ready.set()
            return proc

        with patch("app.runtime.runner.asyncio.create_subprocess_exec", side_effect=spawn):
            task = asyncio.create_task(
                run_process(
                    [PY, "-c", "import time; time.sleep(30)"],
                    cwd=tmp_path,
                )
            )
            await asyncio.wait_for(ready.wait(), timeout=5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert created[0].returncode is not None

    run(exercise())

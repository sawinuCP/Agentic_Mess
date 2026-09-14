"""Process runner behaviour: exit codes, timeout kill, truncation, missing exe."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar

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

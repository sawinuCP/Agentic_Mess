"""Async process runner with timeouts, output caps and process-tree cleanup.

Phase 1 scope: user-initiated host execution from the editor (terminal-equivalent).
Phase 6 replaces this with sandboxed runtimes for AI-generated code; the interface
(``run_process`` + ``ExecResult``) is designed to survive that change.
"""

from __future__ import annotations

import asyncio
import codecs
import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass

logger = logging.getLogger("harness.runtime")

DEFAULT_TIMEOUT_SECONDS = 180.0
DEFAULT_OUTPUT_LIMIT = 200_000


@dataclass(slots=True)
class ExecResult:
    command: list[str]
    cwd: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    truncated: bool


async def run_process(
    argv: list[str],
    cwd: str | os.PathLike[str],
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
    env_extra: dict[str, str] | None = None,
) -> ExecResult:
    """Run ``argv`` and capture output. Never raises for non-zero exit codes.

    The child environment is SANITIZED (default-deny inheritance, see
    ``app.runtime.env_sandbox``): agent/tool subprocesses never see host
    credentials such as the model API key. ``env_extra`` values are explicit
    scoped injections applied verbatim on top of the sanitized baseline.

    Raises ``FileNotFoundError`` when the executable itself is missing (callers turn
    that into actionable diagnostics, LANG-003).
    """
    if output_limit < 0:
        raise ValueError("output_limit must be non-negative")
    started = time.perf_counter()
    from app.runtime.env_sandbox import (
        build_agent_environment,  # noqa: PLC0415 — no import cycle at load
    )

    env = build_agent_environment(overrides=env_extra)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=os.fspath(cwd),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=(os.name != "nt"),
    )
    assert proc.stdout is not None and proc.stderr is not None
    stdout_capture = _OutputCapture(output_limit)
    stderr_capture = _OutputCapture(output_limit)
    readers = [
        asyncio.create_task(stdout_capture.drain(proc.stdout)),
        asyncio.create_task(stderr_capture.drain(proc.stderr)),
    ]
    completion = asyncio.gather(*readers, proc.wait())
    timed_out = False
    try:
        # Shield the drains: killing a noisy process must not leave full pipes
        # preventing its exit. Capture memory stays bounded even after the cap.
        await asyncio.wait_for(asyncio.shield(completion), timeout=timeout_seconds)
    except TimeoutError:
        timed_out = True
        await _kill_process_tree(proc)
    except BaseException:
        await _kill_process_tree(proc)
        raise
    finally:
        if not completion.done():
            try:
                await asyncio.wait_for(asyncio.shield(completion), timeout=5)
            except TimeoutError:
                completion.cancel()
        await asyncio.gather(completion, return_exceptions=True)
    duration_ms = int((time.perf_counter() - started) * 1000)
    stdout = "".join(stdout_capture.parts)
    stderr = "".join(stderr_capture.parts)
    truncated = stdout_capture.truncated or stderr_capture.truncated
    return ExecResult(
        command=list(argv),
        cwd=os.fspath(cwd),
        # A timed-out process was killed; its exit code is meaningless.
        exit_code=None if timed_out else proc.returncode,
        stdout=stdout[:output_limit],
        stderr=stderr[:output_limit],
        duration_ms=duration_ms,
        timed_out=timed_out,
        truncated=truncated,
    )


class _OutputCapture:
    """Retain a character-limited prefix; drain excess without accumulating it."""

    def __init__(self, limit: int) -> None:
        self.remaining = limit
        self.parts: list[str] = []
        self.truncated = False

    async def drain(self, stream: asyncio.StreamReader) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        while True:
            chunk = await stream.read(65536)
            text = decoder.decode(chunk, final=not chunk)
            kept = text[: self.remaining]
            if kept:
                self.parts.append(kept)
                self.remaining -= len(kept)
            if len(text) > len(kept):
                self.truncated = True
            if not chunk:
                return


async def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    """Terminate the whole process tree so children cannot outlive a timeout."""
    if proc.returncode is not None:
        return
    try:
        if os.name == "nt":
            await asyncio.to_thread(
                subprocess.run,
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            # POSIX-only APIs, resolved dynamically so this module type-checks on Windows.
            killpg = getattr(os, "killpg", None)
            getpgid = getattr(os, "getpgid", None)
            sigkill = getattr(signal, "SIGKILL", None)
            if killpg is not None and getpgid is not None and sigkill is not None:
                killpg(getpgid(proc.pid), sigkill)
    except ProcessLookupError:
        pass
    except Exception:  # noqa: BLE001 — best-effort cleanup
        logger.warning("process_tree_kill_failed pid=%s", proc.pid)
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except TimeoutError:
        logger.error("process_refused_to_die pid=%s", proc.pid)

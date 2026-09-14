"""PTY backends: pywinpty (Windows/ConPTY) and stdlib pty (POSIX)."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(slots=True)
class PtyOutput:
    data: str
    alive: bool


class PtySession:
    """Common interface: read() / write() / resize() / isalive / close()."""

    def __init__(self, proc: object, master_fd: int | None) -> None:
        self._proc = proc
        self._master_fd = master_fd
        self.closed = False

    def write(self, data: str) -> None:
        if self._master_fd is not None:
            os.write(self._master_fd, data.encode("utf-8"))
        else:
            self._proc.write(data)  # type: ignore[attr-defined]

    def read(self, size: int = 4096) -> PtyOutput:
        """Blocking read. Returns data when available; POSIX backend stays responsive
        with a short select so idle sessions keep the loop alive."""
        if self._master_fd is not None:
            import select  # noqa: PLC0415 — posix only

            ready, _, _ = select.select([self._master_fd], [], [], 0.05)
            if not ready:
                return PtyOutput(data="", alive=self.isalive)
            try:
                raw = os.read(self._master_fd, size)
            except OSError:
                return PtyOutput(data="", alive=False)
            return PtyOutput(data=raw.decode("utf-8", errors="replace"), alive=self.isalive)
        # pywinpty: read(size) blocks until data is available (or the pipe closes).
        try:
            data = self._proc.read(size)  # type: ignore[attr-defined]
        except OSError:
            return PtyOutput(data="", alive=False)
        return PtyOutput(data=data or "", alive=self.isalive)

    def resize(self, cols: int, rows: int) -> None:
        cols, rows = max(2, min(cols, 500)), max(2, min(rows, 200))
        if self._master_fd is not None:
            import struct  # noqa: PLC0415 — posix only
            from typing import Any  # noqa: PLC0415

            fcntl: Any = __import__("fcntl")  # POSIX-only, resolved dynamically
            termios: Any = __import__("termios")
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        else:
            self._proc.set_size(rows, cols)  # type: ignore[attr-defined]

    @property
    def isalive(self) -> bool:
        if self.closed:
            return False
        if self._master_fd is not None:
            return self._proc.poll() is None  # type: ignore[attr-defined]
        return self._proc.isalive()  # type: ignore[attr-defined]

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            if self._master_fd is not None:
                posix_proc: subprocess.Popen[bytes] = self._proc  # type: ignore[assignment]
                posix_proc.terminate()
                os.close(self._master_fd)
            else:
                self._proc.terminate(force=True)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 — cleanup is best-effort
            pass


def spawn_pty(cwd: str, cols: int = 100, rows: int = 30) -> PtySession:
    """Spawn the platform shell in a PTY at ``cwd``."""
    if os.name == "nt":
        try:
            from winpty import PtyProcess  # noqa: PLC0415 — windows only
        except ImportError as exc:
            raise RuntimeError(
                "Terminal requires 'pywinpty' on Windows. Install services/api with its deps."
            ) from exc
        shell = _windows_shell()
        proc = PtyProcess.spawn(shell, cwd=cwd, dimensions=(rows, cols))
        return PtySession(proc=proc, master_fd=None)
    shell = os.environ.get("SHELL") or shutil.which("bash") or "/bin/sh"
    openpty = getattr(os, "openpty", None)
    if openpty is None:  # pragma: no cover — non-Windows without a POSIX pty
        raise RuntimeError("POSIX pty is unavailable on this platform")
    master_fd, slave_fd = openpty()
    proc = subprocess.Popen(
        [shell],
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        cwd=cwd,
        start_new_session=True,
    )
    os.close(slave_fd)  # parent keeps only the master side
    return PtySession(proc=proc, master_fd=master_fd)


def _windows_shell() -> str:
    if shutil.which("pwsh"):
        return "pwsh.exe -NoLogo"
    return "powershell.exe -NoLogo"


async def pump_output(session: PtySession, queue: asyncio.Queue[str]) -> None:
    """Drain PTY output into a queue until the process dies or the pipe closes."""
    while session.isalive:
        try:
            out = await asyncio.to_thread(session.read, 4096)
        except Exception:  # noqa: BLE001 — pipe closed during shutdown
            break
        if out.data:
            await queue.put(out.data)
        await asyncio.sleep(0)

"""Git CLI wrapper. argv-list subprocess only — never a shell (SEC-001 posture)."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path

from app.core.errors import DomainError
from app.runtime.runner import run_process


class GitError(DomainError):
    """kind: missing | not_a_repo | not_found | failed | conflict"""

    def __init__(self, kind: str, message: str) -> None:
        status = {
            "missing": 503,
            "not_a_repo": 409,
            "not_found": 404,
            "failed": 400,
            "conflict": 409,
        }[kind]
        super().__init__(message, status)
        self.kind = kind


@dataclass(slots=True)
class GitStatusEntry:
    index_status: str
    worktree_status: str
    path: str


@dataclass(slots=True)
class GitStatus:
    branch: str | None
    upstream: str | None
    ahead: int
    behind: int
    entries: list[GitStatusEntry] = field(default_factory=list)


@dataclass(slots=True)
class GitCommit:
    hash: str
    author: str
    date_iso: str
    message: str


@dataclass(slots=True)
class GitWorktree:
    path: str
    head: str | None
    branch: str | None


def _worktree_from(block: dict[str, str]) -> GitWorktree:
    branch = block.get("branch")
    return GitWorktree(
        path=block.get("worktree", ""),
        head=block.get("head"),
        branch=branch.removeprefix("refs/heads/") if branch else None,
    )


class GitClient:
    def __init__(self, root: Path) -> None:
        self.root = root

    async def _run(self, *args: str, timeout: float = 30.0) -> str:
        try:
            result = await run_process(
                ["git", *args], cwd=self.root, timeout_seconds=timeout, output_limit=1_000_000
            )
        except FileNotFoundError:
            raise GitError("missing", "git executable was not found on PATH") from None
        if result.timed_out:
            raise GitError("failed", f"git timed out: git {' '.join(args)}")
        if result.exit_code != 0:
            err = result.stderr.strip() or result.stdout.strip() or "unknown git error"
            lowered = err.lower()
            if "not a git repository" in lowered:
                raise GitError("not_a_repo", "This project is not a git repository")
            if "does not exist" in lowered or "pathspec" in lowered:
                raise GitError("not_found", err.splitlines()[-1])
            raise GitError("failed", err.splitlines()[-1] if err else "git failed")
        return result.stdout

    async def status(self) -> GitStatus:
        out = await self._run("status", "--porcelain=v1", "-b")
        lines = out.splitlines()
        status = GitStatus(branch=None, upstream=None, ahead=0, behind=0)
        for line in lines:
            if line.startswith("## "):
                self._parse_branch_line(line[3:], status)
                continue
            if len(line) < 4:
                continue
            xy, path = line[:2], line[3:]
            if " -> " in path:  # renames: take the destination side
                path = path.split(" -> ", 1)[1]
            status.entries.append(
                GitStatusEntry(index_status=xy[0], worktree_status=xy[1], path=path.strip('"'))
            )
        return status

    @staticmethod
    def _parse_branch_line(info: str, status: GitStatus) -> None:
        if info.startswith("No commits yet on "):
            status.branch = info.removeprefix("No commits yet on ")
            return
        if "..." in info:
            branch_part, _, rest = info.partition("...")
            tracking, _, _markers = rest.partition(" ")
            status.branch = branch_part.strip() or None
            status.upstream = tracking or None
        else:
            status.branch = info.split(" ", 1)[0].strip() or None
        idx_ahead = info.find("[ahead ")
        idx_behind = info.find("[behind ")
        if idx_ahead >= 0:
            digits = "".join(ch for ch in info[idx_ahead + 7 :] if ch.isdigit())
            status.ahead = int(digits or 0)
        if idx_behind >= 0:
            digits = "".join(ch for ch in info[idx_behind + 8 :] if ch.isdigit())
            status.behind = int(digits or 0)

    async def diff(self, path: str | None = None, *, staged: bool = False) -> str:
        args = ["diff", "--no-color", "--unified=3"]
        if staged:
            args.append("--cached")
        if path:
            args += ["--", path]
        return await self._run(*args)

    async def file_at(self, ref: str, path: str) -> str:
        return await self._run("show", f"{ref}:{path}", timeout=20.0)

    async def log(self, limit: int = 50) -> list[GitCommit]:
        out = await self._run(
            "log",
            f"--max-count={max(1, min(limit, 200))}",
            "--pretty=format:%H%x1f%an%x1f%aI%x1f%s%x1e",
        )
        commits: list[GitCommit] = []
        for record in out.split("\x1e"):
            record = record.strip("\n")
            if not record:
                continue
            parts = record.split("\x1f")
            if len(parts) == 4:
                commits.append(
                    GitCommit(hash=parts[0], author=parts[1], date_iso=parts[2], message=parts[3])
                )
        return commits

    async def branches(self) -> list[str]:
        out = await self._run("for-each-ref", "refs/heads", "--format=%(refname:short)")
        return [line for line in out.splitlines() if line.strip()]

    async def current_branch(self) -> str | None:
        try:
            out = await self._run("rev-parse", "--abbrev-ref", "HEAD")
        except GitError as exc:
            if exc.kind in ("not_found", "not_a_repo"):
                return None
            raise
        return out.strip() or None

    async def stage(self, paths: list[str]) -> None:
        await self._run("add", "--", *paths)

    async def unstage(self, paths: list[str]) -> None:
        await self._run("restore", "--staged", "--", *paths)

    async def commit(self, message: str, paths: list[str] | None = None) -> str:
        message = message.strip()
        if not message:
            raise GitError("failed", "Commit message must not be empty")
        if paths:
            await self.stage(paths)
        out = await self._run("commit", "-m", message)
        return out.strip()

    async def checkout(self, branch: str, *, create: bool = False) -> None:
        branch = branch.strip()
        if not branch or any(c.isspace() or c == ":" for c in branch):
            raise GitError("failed", f"Invalid branch name: {branch!r}")
        args = ["checkout", *(["-b"] if create else []), branch]
        await self._run(*args)

    async def init(self) -> None:
        await self._run("init")

    async def ensure_local_exclude(self, pattern: str) -> None:
        """Add ``pattern`` to ``.git/info/exclude`` (local, never committed).

        Tool-managed paths (worktrees under ``.harness/``) must not pollute the
        user's ``git status`` — and this belongs in the local exclude rather than
        the tracked ``.gitignore`` because it is harness plumbing, not project code.
        """
        info_dir = self.root / ".git" / "info"
        info_dir.mkdir(parents=True, exist_ok=True)
        exclude_path = info_dir / "exclude"
        try:
            existing = exclude_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            existing = ""
        lines = {line.strip() for line in existing.splitlines()}
        if pattern not in lines:
            separator = "" if not existing or existing.endswith("\n") else "\n"
            exclude_path.write_text(
                f"{existing}{separator}# managed by AI Harness\n{pattern}\n",
                encoding="utf-8",
            )

    async def commit_all(self, message: str) -> str:
        """Stage everything and commit — test/setup convenience for empty repos."""
        await self._run("add", "-A")
        return (await self._run("commit", "-m", message)).strip()

    # --- Worktrees (spec §17: parallel agents work in isolated worktrees) ---

    async def worktree_add(self, path: str, branch: str, *, create_branch: bool = True) -> None:
        """Create a worktree at ``path`` on ``branch`` (new branch from HEAD by default)."""
        args = ["worktree", "add"]
        if create_branch:
            args += ["-b", branch]
        args.append(str(path))
        if not create_branch:
            args.append(branch)
        await self._run(*args)

    async def worktree_remove(self, path: str, *, force: bool = False) -> None:
        """Remove a worktree. Non-force refuses dirty trees — failed attempts must
        remain inspectable (spec §17)."""
        await self._run("worktree", "remove", *(["--force"] if force else []), str(path))

    async def worktree_list(self) -> list[GitWorktree]:
        out = await self._run("worktree", "list", "--porcelain")
        entries: list[GitWorktree] = []
        current: dict[str, str] = {}
        for line in out.splitlines():
            if not line.strip():
                if current:
                    entries.append(_worktree_from(current))
                    current = {}
                continue
            key, _, value = line.partition(" ")
            current[key] = value.strip()
        if current:
            entries.append(_worktree_from(current))
        return entries

    async def merge_no_ff(self, branch: str, message: str) -> str:
        """Merge ``branch`` into the current branch with a merge commit (integration
        queue, spec §17). Conflicts abort cleanly and surface as GitError("conflict")
        so the caller can record an explicit conflict task — never a dirty canonical
        workspace."""
        branch = branch.strip()
        if not branch or any(c.isspace() or c == ":" for c in branch):
            raise GitError("failed", f"Invalid branch name: {branch!r}")
        try:
            await self._run("merge", "--no-ff", "--no-commit", branch, timeout=60.0)
        except GitError as exc:
            with contextlib.suppress(GitError):
                await self._run("merge", "--abort")  # nothing to abort is fine; surface the cause
            raise GitError("conflict", f"merge of {branch!r} conflicts: {exc}") from None
        await self._run("commit", "-m", message)
        return (await self._run("rev-parse", "HEAD")).strip()

"""Git endpoints: status/diff/log/branches/stage/commit/checkout (FR-028 Git basics)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.api.deps import get_files_service, get_project
from app.db.models import Project
from app.events.recorder import record_event
from app.files.service import ProjectFiles
from app.gitops.client import GitClient, GitStatus

router = APIRouter(prefix="/api/projects/{project_id}/git", tags=["git"])


class GitStatusEntryOut(BaseModel):
    index_status: str
    worktree_status: str
    path: str


class GitStatusOut(BaseModel):
    branch: str | None
    upstream: str | None
    ahead: int
    behind: int
    entries: list[GitStatusEntryOut]


class CommitRequest(BaseModel):
    message: str
    paths: list[str] | None = None


class PathsRequest(BaseModel):
    paths: list[str]


class CheckoutRequest(BaseModel):
    branch: str
    create: bool = False


def _client(files: ProjectFiles = Depends(get_files_service)) -> GitClient:
    return GitClient(files.root)


def _sanitize(files: ProjectFiles, paths: list[str]) -> list[str]:
    """Containment check only — staged paths may already be deleted on disk."""
    return [files.to_rel(files.resolve(p)) for p in paths]


def _status_dto(status: GitStatus) -> GitStatusOut:
    return GitStatusOut(
        branch=status.branch,
        upstream=status.upstream,
        ahead=status.ahead,
        behind=status.behind,
        entries=[
            GitStatusEntryOut(
                index_status=e.index_status, worktree_status=e.worktree_status, path=e.path
            )
            for e in status.entries
        ],
    )


@router.get("/status", response_model=GitStatusOut)
async def status(client: GitClient = Depends(_client)) -> GitStatusOut:
    return _status_dto(await client.status())


@router.get("/diff")
async def diff(
    path: str | None = None,
    staged: bool = False,
    files: ProjectFiles = Depends(get_files_service),
    client: GitClient = Depends(_client),
) -> dict[str, str]:
    rel = files.to_rel(files.resolve(path)) if path else None
    text = await client.diff(rel, staged=staged)
    return {"diff": text}


@router.get("/file")
async def file_at(
    path: str = Query(...),
    ref: str = "HEAD",
    files: ProjectFiles = Depends(get_files_service),
    client: GitClient = Depends(_client),
) -> dict[str, str]:
    rel = files.to_rel(files.resolve(path))
    content = await client.file_at(ref, rel)
    return {"path": rel, "ref": ref, "content": content}


@router.get("/log")
async def log(
    limit: int = Query(50, ge=1, le=200), client: GitClient = Depends(_client)
) -> list[dict[str, str]]:
    commits = await client.log(limit)
    return [
        {"hash": c.hash, "author": c.author, "date_iso": c.date_iso, "message": c.message}
        for c in commits
    ]


@router.get("/branches")
async def branches(client: GitClient = Depends(_client)) -> dict[str, object]:
    names = await client.branches()
    current = await client.current_branch()
    return {"branches": names, "current": current}


@router.post("/stage", status_code=204)
async def stage(
    body: PathsRequest,
    files: ProjectFiles = Depends(get_files_service),
    client: GitClient = Depends(_client),
) -> None:
    await client.stage(_sanitize(files, body.paths))


@router.post("/unstage", status_code=204)
async def unstage(
    body: PathsRequest,
    files: ProjectFiles = Depends(get_files_service),
    client: GitClient = Depends(_client),
) -> None:
    await client.unstage(_sanitize(files, body.paths))


@router.post("/commit", response_model=dict[str, str])
async def commit(
    body: CommitRequest,
    request: Request,
    project: Project = Depends(get_project),
    files: ProjectFiles = Depends(get_files_service),
    client: GitClient = Depends(_client),
) -> dict[str, str]:
    paths = _sanitize(files, body.paths) if body.paths else None
    out = await client.commit(body.message, paths)
    await record_event(
        request.app.state.session_factory,
        "GIT_COMMIT",
        project_id=project.id,
        payload={"message": body.message.strip()[:200], "paths": paths or "staged"},
    )
    return {"output": out}


@router.post("/checkout", status_code=204)
async def checkout(body: CheckoutRequest, client: GitClient = Depends(_client)) -> None:
    await client.checkout(body.branch, create=body.create)


@router.post("/init", status_code=204)
async def init_repo(client: GitClient = Depends(_client)) -> None:
    await client.init()

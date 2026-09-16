"""Worktree isolation + controlled integration queue endpoints (FR-012, spec §17)."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_files_service, get_project
from app.core.errors import DomainError
from app.db.models import Project
from app.files.service import ProjectFiles
from app.gitops.client import GitClient, GitError
from app.schemas.orchestration.worktrees import IntegrationOut, WorktreeCreateIn, WorktreeOut
from app.services.orchestration import worktrees as worktree_service

router = APIRouter(tags=["worktrees"])


def _worktree_root(files: ProjectFiles) -> Path:
    return Path(files.root) / ".harness" / "worktrees"


@router.post("/api/projects/{project_id}/worktrees", response_model=WorktreeOut, status_code=201)
async def create_worktree(
    body: WorktreeCreateIn,
    project: Project = Depends(get_project),
    files: ProjectFiles = Depends(get_files_service),
    db: Session = Depends(get_db),
) -> WorktreeOut:
    """Give an agent an isolated worktree on a fresh branch (spec §17)."""
    branch = worktree_service.sanitize_branch(body.branch or f"agent/task-{uuid.uuid4().hex[:8]}")
    # Isolation pre-check BEFORE touching git: never take an active branch.
    await asyncio.to_thread(worktree_service.ensure_branch_free, db, project.id, branch)
    git = GitClient(files.root)
    await git.ensure_local_exclude(".harness/")  # worktrees never pollute `git status`
    worktree_path = _worktree_root(files) / branch.replace("/", "-")
    await git.worktree_add(str(worktree_path), branch, create_branch=True)
    return await asyncio.to_thread(
        worktree_service.register, db, project.id, body.task_id, branch, str(worktree_path)
    )


@router.get("/api/projects/{project_id}/worktrees", response_model=list[WorktreeOut])
async def list_worktrees(
    project: Project = Depends(get_project),
    db: Session = Depends(get_db),
    status: str | None = Query(None, pattern="^(active|merged|abandoned)$"),
    limit: int = Query(100, ge=1, le=500),
) -> list[WorktreeOut]:
    return await asyncio.to_thread(worktree_service.list_worktrees, db, project.id, status, limit)


@router.post("/api/worktrees/{worktree_id}/integration/enqueue", response_model=WorktreeOut)
async def enqueue_integration(worktree_id: uuid.UUID, db: Session = Depends(get_db)) -> WorktreeOut:
    return await asyncio.to_thread(worktree_service.enqueue, db, worktree_id)


@router.post("/api/projects/{project_id}/integration/process", response_model=IntegrationOut)
async def process_integration(
    project: Project = Depends(get_project),
    files: ProjectFiles = Depends(get_files_service),
    db: Session = Depends(get_db),
) -> IntegrationOut:
    """One controlled integration step: FIFO queue head → canonical branch (spec §17).

    Conflicts abort cleanly and become explicit conflict tasks — the canonical
    workspace is never left dirty.
    """
    worktree = await asyncio.to_thread(worktree_service.next_queued, db, project.id)
    if worktree is None:
        return IntegrationOut(worktree=None, merged=False, message="integration queue is empty")
    await asyncio.to_thread(worktree_service.mark_integration, db, worktree.id, "integrating")
    git = GitClient(files.root)
    try:
        commit = await git.merge_no_ff(
            worktree.branch, f"Integrate {worktree.branch} (worktree {worktree.id})"
        )
    except GitError as exc:
        if exc.kind != "conflict":
            raise
        task = await asyncio.to_thread(
            worktree_service.create_conflict_task, db, worktree, str(exc)
        )
        marked = await asyncio.to_thread(
            worktree_service.mark_integration, db, worktree.id, "conflict"
        )
        return IntegrationOut(
            worktree=marked,
            merged=False,
            conflict_task_id=task.id,
            message=str(exc),
        )
    marked = await asyncio.to_thread(worktree_service.mark_integration, db, worktree.id, "merged")
    return IntegrationOut(
        worktree=marked, merged=True, commit=commit, message="integrated into canonical branch"
    )


@router.post("/api/worktrees/{worktree_id}/release", response_model=WorktreeOut)
async def release_worktree(
    worktree_id: uuid.UUID,
    db: Session = Depends(get_db),
    force: bool = Query(False, description="Force-remove even a dirty worktree (explicit)"),
) -> WorktreeOut:
    """Remove the worktree on disk and mark it abandoned. Without ``force`` a dirty
    worktree is refused — failed attempts must remain inspectable (spec §17)."""
    worktree = await asyncio.to_thread(worktree_service.get_worktree, db, worktree_id)
    project = await asyncio.to_thread(db.get, Project, worktree.project_id)
    if project is None:
        raise DomainError("Project not found", 404)
    git = GitClient(Path(project.root_path))
    try:
        await git.worktree_remove(worktree.path, force=force)
    except GitError:
        if not force:
            raise  # dirty worktree — an explicit force decision is required
    return await asyncio.to_thread(worktree_service.release, db, worktree_id, merged=False)

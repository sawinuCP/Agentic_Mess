"""Filesystem endpoints: tree, read/write, create/rename/delete, search (FR-001, FR-028)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.api.deps import get_files_service, get_project
from app.db.models import Project
from app.events.recorder import record_event
from app.files.search import ProjectSearch
from app.files.service import FileContent, ProjectFiles, TreeEntry

router = APIRouter(prefix="/api/projects/{project_id}", tags=["files"])


class FileWriteRequest(BaseModel):
    path: str
    content: str


class EntryCreateRequest(BaseModel):
    path: str
    kind: str  # "file" | "directory"


class EntryRenameRequest(BaseModel):
    path: str
    new_path: str


class FileContentOut(BaseModel):
    path: str
    content: str
    is_binary: bool
    size: int
    mtime_ms: int


class TreeEntryOut(BaseModel):
    name: str
    path: str
    kind: str
    size: int
    has_children: bool


class SearchMatchOut(BaseModel):
    path: str
    line: int
    column: int
    text: str


def _content_dto(content: FileContent) -> FileContentOut:
    return FileContentOut(
        path=content.path,
        content=content.content,
        is_binary=content.is_binary,
        size=content.size,
        mtime_ms=content.mtime_ms,
    )


def _entry_dto(entry: TreeEntry) -> TreeEntryOut:
    return TreeEntryOut(
        name=entry.name,
        path=entry.path,
        kind=entry.kind,
        size=entry.size,
        has_children=entry.has_children,
    )


@router.get("/tree", response_model=list[TreeEntryOut])
async def tree(
    path: str = "",
    files: ProjectFiles = Depends(get_files_service),
) -> list[TreeEntryOut]:
    entries = await asyncio.to_thread(files.tree, path)
    return [_entry_dto(e) for e in entries]


@router.get("/file", response_model=FileContentOut)
async def read_file(
    path: str = Query(...), files: ProjectFiles = Depends(get_files_service)
) -> FileContentOut:
    content = await asyncio.to_thread(files.read, path)
    return _content_dto(content)


@router.put("/file", response_model=FileContentOut)
async def write_file(
    body: FileWriteRequest,
    request: Request,
    project: Project = Depends(get_project),
    files: ProjectFiles = Depends(get_files_service),
) -> FileContentOut:
    content = await asyncio.to_thread(files.write, body.path, body.content)
    await record_event(
        request.app.state.session_factory,
        "FILE_WRITTEN",
        project_id=project.id,
        payload={"path": body.path, "bytes": len(body.content.encode("utf-8"))},
    )
    return _content_dto(content)


@router.post("/entries", response_model=TreeEntryOut)
async def create_entry(
    body: EntryCreateRequest, files: ProjectFiles = Depends(get_files_service)
) -> TreeEntryOut:
    entry = await asyncio.to_thread(files.create, body.path, body.kind)
    return _entry_dto(entry)


@router.post("/rename", response_model=TreeEntryOut)
async def rename_entry(
    body: EntryRenameRequest, files: ProjectFiles = Depends(get_files_service)
) -> TreeEntryOut:
    entry = await asyncio.to_thread(files.rename, body.path, body.new_path)
    return _entry_dto(entry)


@router.delete("/entries", status_code=204)
async def delete_entry(
    path: str = Query(...), files: ProjectFiles = Depends(get_files_service)
) -> None:
    await asyncio.to_thread(files.delete, path)


@router.get("/search", response_model=list[SearchMatchOut])
async def search(
    q: str = Query(..., min_length=1),
    path: str = "",
    regex: bool = False,
    case_sensitive: bool = False,
    glob: str | None = None,
    files: ProjectFiles = Depends(get_files_service),
) -> list[SearchMatchOut]:
    searcher = ProjectSearch(files)
    matches = await asyncio.to_thread(
        searcher.search,
        q,
        sub_path=path,
        is_regex=regex,
        case_sensitive=case_sensitive,
        glob=glob,
    )
    return [SearchMatchOut(path=m.path, line=m.line, column=m.column, text=m.text) for m in matches]


@router.get("/files", response_model=list[str])
async def list_files(q: str = "", files: ProjectFiles = Depends(get_files_service)) -> list[str]:
    """Flat path list for quick-open."""
    searcher = ProjectSearch(files)
    return await asyncio.to_thread(searcher.list_files, q)

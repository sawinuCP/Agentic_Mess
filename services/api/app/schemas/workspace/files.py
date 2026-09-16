"""Filesystem DTOs (tree, content, entries, search)."""

from pydantic import BaseModel


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

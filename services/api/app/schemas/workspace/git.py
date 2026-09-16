"""Git DTOs."""

from pydantic import BaseModel


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

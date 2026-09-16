"""Project DTOs."""

from uuid import UUID

from pydantic import BaseModel


class ProjectOpenRequest(BaseModel):
    root_path: str
    name: str | None = None


class ProjectOut(BaseModel):
    id: UUID
    name: str
    root_path: str
    default_branch: str

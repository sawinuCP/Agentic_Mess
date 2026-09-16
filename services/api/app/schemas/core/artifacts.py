"""Artifact DTOs."""

from uuid import UUID

from pydantic import BaseModel


class ArtifactOut(BaseModel):
    id: UUID
    project_id: UUID | None
    name: str
    kind: str
    mime: str
    size: int
    sha256: str

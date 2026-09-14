"""Artifact service: store/open content and manage metadata (FR-024, spec §19)."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.artifacts.store import ArtifactStore, mime_for_name
from app.core.errors import DomainError
from app.db.models import Artifact
from app.schemas.artifacts import ArtifactOut


def artifact_out(artifact: Artifact) -> ArtifactOut:
    return ArtifactOut(
        id=artifact.id,
        project_id=artifact.project_id,
        name=artifact.name,
        kind=artifact.kind,
        mime=artifact.mime,
        size=artifact.size,
        sha256=artifact.sha256,
    )


def _artifact_or_404(artifact_id: uuid.UUID, db: Session) -> Artifact:
    artifact = db.get(Artifact, artifact_id)
    if artifact is None:
        raise DomainError("Artifact not found", 404)
    return artifact


def store_artifact(
    db: Session,
    store: ArtifactStore,
    project_id: uuid.UUID,
    name: str,
    kind: str,
    mime: str,
    data: bytes,
) -> ArtifactOut:
    if not data:
        raise DomainError("Empty artifact upload", 422)
    blob = store.put(data)
    artifact = Artifact(
        project_id=project_id,
        name=name or f"artifact-{blob.sha256[:8]}",
        kind=kind,
        mime=mime or mime_for_name(name),
        size=blob.size,
        sha256=blob.sha256,
        storage_path=blob.storage_path,
    )
    db.add(artifact)
    db.commit()
    return artifact_out(artifact)


def get_artifact(db: Session, artifact_id: uuid.UUID) -> ArtifactOut:
    return artifact_out(_artifact_or_404(artifact_id, db))


def read_content(
    db: Session, store: ArtifactStore, artifact_id: uuid.UUID
) -> tuple[Artifact, bytes]:
    artifact = _artifact_or_404(artifact_id, db)
    return artifact, store.open(artifact.storage_path)


def record_blob(
    db: Session,
    store: ArtifactStore,
    project_id: uuid.UUID | None,
    name: str,
    kind: str,
    data: bytes,
) -> Artifact:
    """Persist a generated blob (e.g. workflow evidence) and return the ORM row."""
    blob = store.put(data)
    artifact = Artifact(
        project_id=project_id,
        name=name,
        kind=kind,
        mime=mime_for_name(name),
        size=blob.size,
        sha256=blob.sha256,
        storage_path=blob.storage_path,
    )
    db.add(artifact)
    db.commit()
    return artifact

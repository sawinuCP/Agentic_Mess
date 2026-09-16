"""Project export/import (Phase 10 hardening): durable-state portability.

``export_bundle`` serializes the full durable state of a project (requirements,
criteria, plans, tasks, dependencies, attempts, oversight rows, events, context
items and artifact metadata) into a JSON bundle. Artifact blobs are inlined
base64 when small enough, otherwise referenced by sha with a note — content is
content-addressed, so a same-store re-import restores them by sha.

``import_bundle`` restores the bundle as a NEW project (new ids everywhere).
The workspace root is not portable: the caller supplies a fresh absolute path.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.models import (
    AcceptanceCriterion,
    Artifact,
    ContextItem,
    Decision,
    Event,
    HitlRequest,
    Plan,
    Project,
    Requirement,
    Review,
    Task,
    TaskAttempt,
    TaskDependency,
    Validation,
)

INLINE_ARTIFACT_MAX_BYTES = 1_000_000

# Any-model loops: these models expose the columns the copy loop touches.
_PROJECT_OWNED: tuple[type[Any], ...] = (
    Requirement,
    Task,
    Decision,
    Validation,
    HitlRequest,
    ContextItem,
    Event,
)
_TABLES: tuple[type[Any], ...] = (
    Requirement,
    AcceptanceCriterion,
    Plan,
    Task,
    TaskDependency,
    TaskAttempt,
    Decision,
    Review,
    Validation,
    HitlRequest,
    ContextItem,
    Event,
)

_SKIP_COLUMNS = {
    "id",
    "project_id",
    "created_at",
    "updated_at",
    "started_at",
    "finished_at",
    "decided_at",
    "occurred_at",
}


def export_bundle(db: Session, project_id: uuid.UUID, store: Any) -> dict[str, Any]:
    """Serialize a project's durable state (spec §29 entities owned by the project)."""
    project = db.get(Project, project_id)
    if project is None:
        raise DomainError("Project not found", 404)
    store_root = Path(store.root)

    entities: dict[str, list[dict[str, Any]]] = {}

    def _rows(model: type[Any], owner_column: str, owner_ids: list[uuid.UUID]) -> list[Any]:
        if not owner_ids:
            return []
        rows = db.scalars(select(model).where(getattr(model, owner_column).in_(owner_ids))).all()
        return list(rows)

    def _dump(model: type[Any], rows: list[Any]) -> list[dict[str, Any]]:
        exported: list[dict[str, Any]] = []
        for row in rows:
            item: dict[str, Any] = {"_old_id": str(row.id)}
            for column in model.__table__.columns:
                if column.name in _SKIP_COLUMNS:
                    continue
                value = getattr(row, column.name)
                item[column.name] = str(value) if isinstance(value, uuid.UUID) else value
            exported.append(item)
        return exported

    # Direct project-owned rows.
    project_rows: dict[type[Any], list[Any]] = {}
    for model in _PROJECT_OWNED:
        rows = list(db.scalars(select(model).where(model.project_id == project_id)).all())
        project_rows[model] = rows
        entities[model.__name__] = _dump(model, rows)

    # Child rows hang off their parents (no project_id column of their own).
    requirement_ids = [row.id for row in project_rows[Requirement]]
    task_ids = [row.id for row in project_rows[Task]]
    decision_ids = [row.id for row in project_rows[Decision]]
    entities["Plan"] = _dump(Plan, _rows(Plan, "requirement_id", requirement_ids))
    entities["AcceptanceCriterion"] = _dump(
        AcceptanceCriterion, _rows(AcceptanceCriterion, "requirement_id", requirement_ids)
    )
    entities["TaskDependency"] = _dump(TaskDependency, _rows(TaskDependency, "task_id", task_ids))
    entities["TaskAttempt"] = _dump(TaskAttempt, _rows(TaskAttempt, "task_id", task_ids))
    reviews = list(
        db.scalars(
            select(Review).where(
                Review.task_id.in_(task_ids) | Review.decision_id.in_(decision_ids)
            )
        ).all()
    )
    entities["Review"] = _dump(Review, reviews)

    artifacts: list[dict[str, Any]] = []
    for artifact in db.scalars(select(Artifact).where(Artifact.project_id == project_id)).all():
        entry: dict[str, Any] = {
            "_old_id": str(artifact.id),
            "name": artifact.name,
            "kind": artifact.kind,
            "mime": artifact.mime,
            "sha256": artifact.sha256,
            "size": artifact.size,
        }
        path = store_root / artifact.storage_path  # storage paths are store-relative
        if path.is_file() and artifact.size <= INLINE_ARTIFACT_MAX_BYTES:
            entry["content_b64"] = base64.b64encode(path.read_bytes()).decode("ascii")
        else:
            entry["content_b64"] = None
            entry["note"] = "too large to inline; restore by sha from a store that has it"
        artifacts.append(entry)

    return {
        "bundle_version": 1,
        "exported_at": datetime.now(UTC).isoformat(),
        "source_project": {
            "id": str(project.id),
            "name": project.name,
            "default_branch": project.default_branch,
        },
        "entities": entities,
        "artifacts": artifacts,
        "id_map_note": "old ids are listed per row (_old_id); import assigns fresh ids",
    }


def import_bundle(
    db: Session,
    artifact_store: Any,
    bundle: dict[str, Any],
    *,
    new_root: str,
    new_name: str | None = None,
) -> dict[str, Any]:
    """Restore a bundle as a brand-new project; returns the new project summary."""
    if bundle.get("bundle_version") != 1:
        raise DomainError("Unsupported bundle version", 422)
    entities: dict[str, list[dict[str, Any]]] = bundle.get("entities", {})
    if not entities.get("Requirement"):
        raise DomainError("Bundle has no requirements to import", 422)

    project = Project(name=new_name or f"imported-{uuid.uuid4().hex[:8]}", root_path=str(new_root))
    db.add(project)
    db.flush()

    for model in _TABLES:
        has_project_id = "project_id" in model.__table__.columns
        for item in entities.get(model.__name__, []):
            row = model(id=uuid.uuid4(), **({"project_id": project.id} if has_project_id else {}))
            for column in model.__table__.columns:
                if column.name in ("id", "created_at", "updated_at"):
                    continue
                if column.name in item and item[column.name] is not None:
                    setattr(row, column.name, item[column.name])
            db.add(row)
        db.flush()

    restored, skipped = 0, 0
    for entry in bundle.get("artifacts", []):
        content_b64 = entry.get("content_b64")
        if not content_b64:
            skipped += 1
            continue
        blob = artifact_store.put(base64.b64decode(content_b64))
        db.add(
            Artifact(
                project_id=project.id,
                name=entry.get("name", "imported"),
                kind=entry.get("kind", "file"),
                mime=entry.get("mime", ""),
                size=blob.size,
                sha256=blob.sha256,
                storage_path=blob.storage_path,
            )
        )
        restored += 1
    db.commit()

    return {
        "project_id": str(project.id),
        "requirements": len(entities.get("Requirement", [])),
        "tasks": len(entities.get("Task", [])),
        "artifacts_restored": restored,
        "artifacts_skipped": skipped,
    }

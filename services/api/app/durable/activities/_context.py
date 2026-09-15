"""Shared activity context: injected refs (session factory, artifact store, settings).

Dependencies are injected via :func:`init_refs` by the worker entrypoint and by
tests; activities never construct their own engine/store (single source of truth).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.artifacts.store import ArtifactStore
from app.db.models import Task

#: Raw outputs smaller than this are kept in the attempt record only, not as artifacts.
EVIDENCE_MIN_BYTES = 512


class _Refs:
    session_factory: sessionmaker[Session] | None = None
    artifact_store: ArtifactStore | None = None
    settings: Any = None


def init_refs(
    session_factory: sessionmaker[Session],
    artifact_store: ArtifactStore,
    settings: Any = None,
) -> None:
    """Inject process-wide dependencies (worker startup or test setup)."""
    _Refs.session_factory = session_factory
    _Refs.artifact_store = artifact_store
    _Refs.settings = settings


def refs() -> tuple[sessionmaker[Session], ArtifactStore]:
    if _Refs.session_factory is None or _Refs.artifact_store is None:
        raise RuntimeError("Activity refs not initialised (worker startup or test setup)")
    return _Refs.session_factory, _Refs.artifact_store


def current_settings() -> Any:
    """The injected settings object (may be ``None`` in uninitialised tests)."""
    return _Refs.settings


def load_task_row(session: Session, task_id: uuid.UUID) -> Task:
    """Fetch a task or raise — activities treat a missing task as a bug, not a 404."""
    task = session.get(Task, task_id)
    if task is None:
        raise RuntimeError(f"Task not found: {task_id}")
    return task

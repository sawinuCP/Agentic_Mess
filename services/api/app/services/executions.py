"""Execution quotas (Phase 6, spec §19): bounded concurrency per project.

Slots are implemented as ``runtime``-kind resource leases (spec §18) keyed
``<project>#exec-slot-<n>`` — reusing the durable TTL/renewal/expiry machinery
instead of inventing a second locking mechanism. A task that cannot get a slot
is reported as ``QUOTA_EXCEEDED``; it never queues invisibly.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.schemas.leases import LeaseIn, LeaseOut
from app.services import leases as lease_service

RUNTIME_LEASE_KIND = "runtime"


def acquire_slot(
    db: Session,
    project_id: uuid.UUID,
    *,
    max_concurrent: int,
    ttl_seconds: int = 3600,
    holder_session: str | None = None,
) -> LeaseOut | None:
    """Acquire one of ``max_concurrent`` execution slots; ``None`` when exhausted."""
    if max_concurrent <= 0:
        return None
    for slot in range(max_concurrent):
        try:
            return lease_service.acquire(
                db,
                project_id,
                LeaseIn(
                    kind=RUNTIME_LEASE_KIND,
                    key=f"{project_id}#exec-slot-{slot}",
                    holder_session=holder_session,
                    ttl_seconds=ttl_seconds,
                ),
            )
        except DomainError as exc:
            if exc.status_code != 409:
                raise
            continue  # slot busy — try the next one
    return None


def release_slot(
    db: Session, lease_id: uuid.UUID, holder_agent_id: uuid.UUID | None = None
) -> None:
    lease_service.release(db, lease_id, holder_agent_id)

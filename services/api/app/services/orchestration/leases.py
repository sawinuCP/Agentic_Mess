"""Resource-lease service (spec §18): leases with TTL and heartbeat renewal.

Leases — never permanent locks. Expiry is computed, never stored, so a lease can
always be judged against the durable record. On worker failure leases expire (or
are explicitly released); acquisition order over multiple leases is deterministic
to avoid deadlock (kind, key sort). Every transition emits a durable event.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.models import Event, Resource
from app.schemas.orchestration.leases import LeaseIn, LeaseOut, LeaseRenewIn

STATUS_ACTIVE = "active"
STATUS_EXPIRED = "expired"
STATUS_RELEASED = "released"


def lease_status(resource: Resource, now: datetime | None = None) -> str:
    """Compute lease status. Expiry is a judgment over durable facts (spec §18)."""
    if resource.released_at is not None:
        return STATUS_RELEASED
    now = now or datetime.now(UTC)
    if resource.expires_at <= now:
        return STATUS_EXPIRED
    return STATUS_ACTIVE


def _lease_out(resource: Resource) -> LeaseOut:
    return LeaseOut(
        id=resource.id,
        kind=resource.kind,
        key=resource.key,
        project_id=resource.project_id,
        holder_agent_id=resource.holder_agent_id,
        holder_session=resource.holder_session,
        ttl_seconds=resource.ttl_seconds,
        acquired_at=resource.acquired_at,
        expires_at=resource.expires_at,
        released_at=resource.released_at,
        status=lease_status(resource),
    )


def _emit(db: Session, event_type: str, resource: Resource, extra: dict[str, Any]) -> None:
    """Write the audit event in the same transaction as the lease mutation."""
    db.add(
        Event(
            event_type=event_type,
            source="leases",
            project_id=resource.project_id,
            payload={
                "lease_id": str(resource.id),
                "kind": resource.kind,
                "key": resource.key,
                "holder_agent_id": (
                    str(resource.holder_agent_id) if resource.holder_agent_id else None
                ),
                **extra,
            },
        )
    )


def _active_conflict_error(resource: Resource) -> DomainError:
    return DomainError(
        f"resource is actively leased: kind={resource.kind} key={resource.key} "
        f"holder_agent_id={resource.holder_agent_id} expires_at={resource.expires_at.isoformat()}",
        409,
    )


def _apply_holding(
    db: Session,
    resource: Resource,
    *,
    project_id: uuid.UUID | None,
    body: LeaseIn,
    now: datetime,
) -> Resource:
    """Bind a (new or expired) lease row to the incoming holder."""
    resource.project_id = project_id
    resource.holder_agent_id = body.holder_agent_id
    resource.holder_session = body.holder_session
    resource.ttl_seconds = body.ttl_seconds
    resource.acquired_at = now
    resource.expires_at = now + timedelta(seconds=body.ttl_seconds)
    resource.released_at = None
    db.add(resource)
    _emit(db, "LEASE_ACQUIRED", resource, {"ttl_seconds": body.ttl_seconds})
    return resource


def acquire(db: Session, project_id: uuid.UUID | None, body: LeaseIn) -> LeaseOut:
    """Acquire one lease. An actively-held resource conflicts (409); an expired
    lease is taken over (spec §18: on failure leases expire and may be re-acquired)."""
    now = datetime.now(UTC)
    resource = db.scalar(
        select(Resource).where(Resource.kind == body.kind, Resource.key == body.key)
    )
    if resource is not None and lease_status(resource, now) == STATUS_ACTIVE:
        raise _active_conflict_error(resource)
    resource = resource or Resource(kind=body.kind, key=body.key)
    _apply_holding(db, resource, project_id=project_id, body=body, now=now)
    db.commit()
    return _lease_out(resource)


def acquire_many(
    db: Session, project_id: uuid.UUID | None, bodies: Sequence[LeaseIn]
) -> list[LeaseOut]:
    """Acquire several leases all-or-nothing, in deterministic (kind, key) order
    (spec §18: deterministic lock acquisition ordering prevents deadlock)."""
    if not bodies:
        raise DomainError("at least one lease is required", 422)
    seen: set[tuple[str, str]] = set()
    for body in bodies:
        pair = (body.kind, body.key)
        if pair in seen:
            raise DomainError(f"duplicate lease request in batch: {body.kind}/{body.key}", 422)
        seen.add(pair)

    now = datetime.now(UTC)
    taken: list[Resource] = []
    for body in sorted(bodies, key=lambda b: (b.kind, b.key)):
        resource = db.scalar(
            select(Resource).where(Resource.kind == body.kind, Resource.key == body.key)
        )
        if resource is not None and lease_status(resource, now) == STATUS_ACTIVE:
            db.rollback()  # all-or-nothing: an active conflict abandons the whole batch
            raise _active_conflict_error(resource)
        resource = resource or Resource(kind=body.kind, key=body.key)
        taken.append(_apply_holding(db, resource, project_id=project_id, body=body, now=now))
    db.commit()
    return [_lease_out(r) for r in taken]


def _lease_or_404(db: Session, lease_id: uuid.UUID) -> Resource:
    resource = db.get(Resource, lease_id)
    if resource is None:
        raise DomainError("Lease not found", 404)
    return resource


def renew(db: Session, lease_id: uuid.UUID, body: LeaseRenewIn) -> LeaseOut:
    """Heartbeat renewal: extend the TTL from now. Only the current holder may renew."""
    now = datetime.now(UTC)
    resource = _lease_or_404(db, lease_id)
    status = lease_status(resource, now)
    if status == STATUS_RELEASED:
        raise DomainError("lease was released; acquire it again", 409)
    if status == STATUS_EXPIRED:
        raise DomainError("lease expired; acquire it again", 409)
    if body.holder_agent_id is not None and body.holder_agent_id != resource.holder_agent_id:
        raise DomainError("renewal denied: caller is not the lease holder", 409)
    ttl = body.ttl_seconds or resource.ttl_seconds
    resource.ttl_seconds = ttl
    resource.expires_at = now + timedelta(seconds=ttl)
    db.add(resource)
    _emit(db, "LEASE_RENEWED", resource, {"ttl_seconds": ttl})
    db.commit()
    return _lease_out(resource)


def release(db: Session, lease_id: uuid.UUID, holder_agent_id: uuid.UUID | None) -> LeaseOut:
    """Explicit release (idempotent). Only the holder may release an active lease."""
    now = datetime.now(UTC)
    resource = _lease_or_404(db, lease_id)
    if (
        resource.released_at is None
        and resource.holder_agent_id is not None
        and holder_agent_id is not None
        and holder_agent_id != resource.holder_agent_id
    ):
        raise DomainError("release denied: caller is not the lease holder", 409)
    if resource.released_at is None and lease_status(resource, now) == STATUS_ACTIVE:
        resource.released_at = now
        db.add(resource)
        _emit(db, "LEASE_RELEASED", resource, {})
        db.commit()
    return _lease_out(resource)


def expire_stale(db: Session, project_id: uuid.UUID | None = None) -> dict[str, int]:
    """Mark every unreleased, past-TTL lease as released-by-expiry (spec §18:
    on worker failure leases expire). Supervision calls this; it is idempotent."""
    now = datetime.now(UTC)
    query = select(Resource).where(Resource.released_at.is_(None), Resource.expires_at <= now)
    if project_id is not None:
        query = query.where(Resource.project_id == project_id)
    stale = db.scalars(query).all()
    for resource in stale:
        resource.released_at = now
        db.add(resource)
        _emit(db, "LEASE_EXPIRED", resource, {"expired_at": now.isoformat()})
    db.commit()
    return {"expired": len(stale)}


def list_leases(
    db: Session, project_id: uuid.UUID, status: str | None, limit: int
) -> list[LeaseOut]:
    """List leases for a project, newest first, optionally filtered by computed status.

    The status filter is expressed in SQL (released/expired/active derive fully
    from ``released_at``/``expires_at``) so the limit applies in the database —
    never fetch-then-slice.
    """
    query = (
        select(Resource)
        .where(Resource.project_id == project_id)
        .order_by(Resource.acquired_at.desc(), Resource.id.desc())
        .limit(max(1, limit))
    )
    if status == STATUS_RELEASED:
        query = query.where(Resource.released_at.is_not(None))
    elif status == STATUS_EXPIRED:
        query = query.where(
            Resource.released_at.is_(None),
            Resource.expires_at <= datetime.now(UTC),
        )
    elif status == STATUS_ACTIVE:
        query = query.where(
            Resource.released_at.is_(None),
            Resource.expires_at > datetime.now(UTC),
        )
    return [_lease_out(r) for r in db.scalars(query).all()]


def active_leases_for(db: Session, kind: str, keys: Iterable[str]) -> list[Resource]:
    """Active leases held on any of ``keys`` of one kind — used by the scheduler and
    the integration queue to honor exclusive resources (spec §18)."""
    key_list = list(keys)
    if not key_list:
        return []
    now = datetime.now(UTC)
    rows = db.scalars(
        select(Resource).where(
            Resource.kind == kind,
            Resource.key.in_(key_list),
            Resource.released_at.is_(None),
        )
    ).all()
    return [r for r in rows if lease_status(r, now) == STATUS_ACTIVE]

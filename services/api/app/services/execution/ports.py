"""Port allocator (spec §19.1): agents request ports instead of guessing.

An allocation is only granted when the port is (a) inside the configured range,
(b) not actively allocated in the durable ledger, and (c) actually bindable on
the loopback interface right now — the Phase-0 lesson (loopback binds beat
Docker's wildcard mappings) makes the live bind probe mandatory. TTLs expire;
expired ports are re-allocatable. Every transition emits a durable event.
"""

from __future__ import annotations

import socket
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.models import Event, PortAllocation

STATUS_ACTIVE = "active"
STATUS_EXPIRED = "expired"
STATUS_RELEASED = "released"

VALID_PURPOSES = ("preview", "service", "debug", "test")


def allocation_status(allocation: PortAllocation, now: datetime | None = None) -> str:
    if allocation.released_at is not None:
        return STATUS_RELEASED
    now = now or datetime.now(UTC)
    if allocation.expires_at <= now:
        return STATUS_EXPIRED
    return STATUS_ACTIVE


def _out(allocation: PortAllocation) -> dict[str, Any]:
    return {
        "id": str(allocation.id),
        "project_id": str(allocation.project_id) if allocation.project_id else None,
        "port": allocation.port,
        "purpose": allocation.purpose,
        "holder": allocation.holder,
        "ttl_seconds": allocation.ttl_seconds,
        "allocated_at": allocation.allocated_at,
        "expires_at": allocation.expires_at,
        "released_at": allocation.released_at,
        "status": allocation_status(allocation),
    }


def _emit(db: Session, event_type: str, allocation: PortAllocation, extra: dict[str, Any]) -> None:
    db.add(
        Event(
            event_type=event_type,
            source="ports",
            project_id=allocation.project_id,
            payload={
                "port": allocation.port,
                "purpose": allocation.purpose,
                "allocation_id": str(allocation.id),
                **extra,
            },
        )
    )


def _bindable(port: int) -> bool:
    """True when the OS lets us bind 127.0.0.1:<port> right now (Phase-0 lesson)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def _candidate_ports(low: int, high: int, preferred: int | None) -> Iterator[int]:
    if preferred is not None:
        yield preferred
    for port in range(low, high + 1):
        if preferred is None or port != preferred:
            yield port


def _live_by_key(
    db: Session, project_id: uuid.UUID | None, key: str, now: datetime
) -> PortAllocation | None:
    """The live allocation for an idempotency key, if the retry is a replay."""
    row = db.scalar(
        select(PortAllocation).where(
            PortAllocation.project_id == project_id,
            PortAllocation.idempotency_key == key,
            PortAllocation.released_at.is_(None),
        )
    )
    if row is not None and allocation_status(row, now) == STATUS_ACTIVE:
        return row
    return None


def allocate(
    db: Session,
    project_id: uuid.UUID | None,
    *,
    purpose: str,
    holder: str | None,
    ttl_seconds: int,
    port_low: int,
    port_high: int,
    preferred_port: int | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Reserve the first free, bindable port in the configured range.

    ``idempotency_key`` (client-generated per logical operation): a retried
    call with the same key returns the live allocation instead of reserving a
    second port. A lost race replays the winner's row (fail-safe, never 500).
    """
    if purpose not in VALID_PURPOSES:
        raise DomainError(f"purpose must be one of {VALID_PURPOSES}", 422)
    if port_low > port_high:
        raise DomainError("port range is inverted", 500)
    if preferred_port is not None and not (port_low <= preferred_port <= port_high):
        raise DomainError(f"preferred port {preferred_port} is outside the configured range", 422)
    now = datetime.now(UTC)
    key = (idempotency_key or "").strip() or None
    if key is not None:
        replay = _live_by_key(db, project_id, key, now)
        if replay is not None:
            return _out(replay)

    active = {
        row.port
        for row in db.scalars(select(PortAllocation).where(PortAllocation.released_at.is_(None)))
        if allocation_status(row, now) == STATUS_ACTIVE
    }

    for port in _candidate_ports(port_low, port_high, preferred_port):
        if port in active:
            continue
        if not _bindable(port):
            continue  # OS-level conflict: skip (loopback binds beat wildcard binds)
        allocation = PortAllocation(
            project_id=project_id,
            port=port,
            purpose=purpose,
            holder=holder,
            ttl_seconds=ttl_seconds,
            expires_at=now + timedelta(seconds=ttl_seconds),
            idempotency_key=key,
        )
        db.add(allocation)
        _emit(db, "PORT_ALLOCATED", allocation, {"ttl_seconds": ttl_seconds})
        try:
            db.commit()
        except IntegrityError:
            # Lost a race: an idempotency-key collision replays the winner's
            # row; a port collision (concurrent allocator) tries the next port.
            db.rollback()
            if key is not None:
                replay = _live_by_key(db, project_id, key, datetime.now(UTC))
                if replay is not None:
                    return _out(replay)
            active.add(port)
            continue
        return _out(allocation)

    raise DomainError(
        f"no free bindable port in range {port_low}-{port_high} ({len(active)} actively allocated)",
        409,
    )


def release(db: Session, allocation_id: uuid.UUID, holder: str | None) -> dict[str, Any]:
    """Release a port (idempotent). Holder-checked like leases (SEC posture)."""
    allocation = db.get(PortAllocation, allocation_id)
    if allocation is None:
        raise DomainError("Port allocation not found", 404)
    if (
        allocation.released_at is None
        and allocation.holder is not None
        and holder is not None
        and holder != allocation.holder
    ):
        raise DomainError("release denied: caller is not the allocation holder", 409)
    if allocation.released_at is None:
        allocation.released_at = datetime.now(UTC)
        db.add(allocation)
        _emit(db, "PORT_RELEASED", allocation, {})
        db.commit()
    return _out(allocation)


def renew(db: Session, allocation_id: uuid.UUID, ttl_seconds: int) -> dict[str, Any]:
    """Extend the TTL of an active allocation (heartbeat renewal, spec §18 pattern)."""
    now = datetime.now(UTC)
    allocation = db.get(PortAllocation, allocation_id)
    if allocation is None:
        raise DomainError("Port allocation not found", 404)
    status = allocation_status(allocation, now)
    if status == STATUS_RELEASED:
        raise DomainError("allocation was released; request a new port", 409)
    if status == STATUS_EXPIRED:
        raise DomainError("allocation expired; request a new port", 409)
    allocation.ttl_seconds = ttl_seconds
    allocation.expires_at = now + timedelta(seconds=ttl_seconds)
    db.add(allocation)
    _emit(db, "PORT_RENEWED", allocation, {"ttl_seconds": ttl_seconds})
    db.commit()
    return _out(allocation)


def expire_stale(db: Session) -> dict[str, int]:
    """Release every past-TTL allocation (spec §19.1: ports are released on expiry)."""
    now = datetime.now(UTC)
    stale = db.scalars(
        select(PortAllocation).where(
            PortAllocation.released_at.is_(None), PortAllocation.expires_at <= now
        )
    ).all()
    for allocation in stale:
        allocation.released_at = now
        db.add(allocation)
        _emit(db, "PORT_EXPIRED", allocation, {})
    db.commit()
    return {"expired": len(stale)}


def list_allocations(
    db: Session, project_id: uuid.UUID, status: str | None, limit: int
) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(PortAllocation)
        .where(PortAllocation.project_id == project_id)
        .order_by(PortAllocation.allocated_at.desc())
    ).all()
    out = [_out(r) for r in rows]
    if status is not None:
        out = [a for a in out if a["status"] == status]
    return out[:limit]

"""Resource-lease DTOs (spec §18): TTL leases with heartbeat renewal, never permanent locks."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

# Lockable resource kinds (spec §18). ``kind`` + ``key`` uniquely identify a lease.
LEASE_KINDS = ("file", "symbol", "branch", "worktree", "port", "runtime", "tool")

LEASE_TTL_MIN_SECONDS = 5
LEASE_TTL_MAX_SECONDS = 86_400


class LeaseIn(BaseModel):
    kind: str
    key: str = Field(min_length=1, max_length=500)
    holder_agent_id: UUID | None = None
    holder_session: str | None = Field(None, max_length=64)
    ttl_seconds: int = Field(300, ge=LEASE_TTL_MIN_SECONDS, le=LEASE_TTL_MAX_SECONDS)


class LeaseBatchIn(BaseModel):
    """All-or-nothing acquisition of several leases in deterministic key order (spec §18)."""

    leases: list[LeaseIn] = Field(min_length=1, max_length=25)


class LeaseRenewIn(BaseModel):
    holder_agent_id: UUID | None = None
    ttl_seconds: int | None = Field(None, ge=LEASE_TTL_MIN_SECONDS, le=LEASE_TTL_MAX_SECONDS)


class LeaseOut(BaseModel):
    id: UUID
    kind: str
    key: str
    project_id: UUID | None
    holder_agent_id: UUID | None
    holder_session: str | None
    ttl_seconds: int
    acquired_at: datetime
    expires_at: datetime
    released_at: datetime | None
    status: str  # active|expired|released (computed, never stored)

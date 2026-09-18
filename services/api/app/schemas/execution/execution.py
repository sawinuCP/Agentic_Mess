"""Execution-plane DTOs (Phase 6): ports (spec §19.1) + runtime status."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PortAllocateIn(BaseModel):
    purpose: str  # preview | service | debug | test
    holder: str | None = Field(None, max_length=200)
    ttl_seconds: int = Field(3600, ge=10, le=86_400)
    preferred_port: int | None = Field(None, ge=1, le=65_535)
    # Client-generated per logical operation: retried calls with the same key
    # return the live allocation instead of reserving a second port.
    idempotency_key: str | None = Field(None, max_length=64)


class PortRenewIn(BaseModel):
    ttl_seconds: int = Field(3600, ge=10, le=86_400)


class PortOut(BaseModel):
    id: UUID
    port: int
    purpose: str
    holder: str | None
    project_id: UUID | None
    ttl_seconds: int
    allocated_at: datetime
    expires_at: datetime
    released_at: datetime | None
    status: str  # active | expired | released


class RuntimeStatusOut(BaseModel):
    backends: list[str]
    active_backend: str
    docker_image: str
    docker_network: str
    docker_memory: str
    docker_cpus: str
    exec_timeout_cap_seconds: float
    exec_max_concurrent_per_project: int
    port_range: dict[str, int]
    extra: dict[str, Any] = {}

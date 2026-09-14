"""Health/liveness/readiness DTOs."""

from pydantic import BaseModel


class ComponentHealth(BaseModel):
    status: str
    detail: str | None = None


class LivenessReport(BaseModel):
    status: str
    version: str
    environment: str


class ReadinessReport(BaseModel):
    ready: bool
    version: str
    environment: str
    checks: dict[str, ComponentHealth]

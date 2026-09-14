"""Actionable toolchain errors (LANG-003)."""

from __future__ import annotations

from app.core.errors import DomainError


class ToolchainError(DomainError):
    """Raised for missing tools or invalid toolchain configuration."""

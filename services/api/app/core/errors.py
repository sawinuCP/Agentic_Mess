"""Shared domain error type carried by service exceptions."""

from __future__ import annotations


class DomainError(Exception):
    """Base for errors that map directly onto HTTP responses."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code

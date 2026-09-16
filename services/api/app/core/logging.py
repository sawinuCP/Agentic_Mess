"""Structured JSON logging with request-ID propagation."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str] = ContextVar("request_id", default="")

# Keys that belong to LogRecord itself (plus the injected request id) and must not
# leak into the "extra" payload.
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "request_id",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Compact one-line JSON formatter for machine-readable logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", "")
        if request_id:
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        extra = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED and not key.startswith("_")
        }
        if extra:
            payload["extra"] = extra
        return json.dumps(payload, default=str)


class SecretRedactionFilter(logging.Filter):
    """Redacts credential-shaped spans from log messages (SEC-003).

    Uses the Phase-8 scanner patterns; every high-confidence match is replaced
    in-place with a mask so secrets never persist in normal logs. Non-string
    extras are left untouched (the formatter stringifies them separately).
    """

    MASK = "«redacted»"

    def filter(self, record: logging.LogRecord) -> bool:
        from app.services.quality.secrets import (
            redact_span,  # noqa: PLC0415 — no import cycle at load
        )

        if isinstance(record.msg, str):
            record.msg = redact_span(record.msg)
        if record.args:
            record.args = tuple(
                redact_span(arg) if isinstance(arg, str) else arg for arg in record.args
            )
        return True


class RequestIdFilter(logging.Filter):
    """Injects the current request id (if any) into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("")
        return True


def configure_logging(level: str) -> None:
    """Idempotently install the JSON handler on the root logger."""
    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestIdFilter())
    handler.addFilter(SecretRedactionFilter())
    root.addHandler(handler)

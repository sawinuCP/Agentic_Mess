"""Structured JSON logging behaviour."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.logging import JsonFormatter, RequestIdFilter, configure_logging, request_id_var


def test_json_formatter_emits_parseable_json() -> None:
    record: Any = logging.LogRecord(
        "harness.test", logging.INFO, __file__, 1, "hello %s", ("world",), None
    )
    record.custom_field = {"a": 1}
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "harness.test"
    assert payload["extra"]["custom_field"] == {"a": 1}
    assert "ts" in payload
    assert "request_id" not in payload  # no request context in this record


def test_request_id_filter_injects_context() -> None:
    token = request_id_var.set("req-42")
    try:
        record: Any = logging.LogRecord(
            "harness.test", logging.INFO, __file__, 1, "msg", None, None
        )
        assert RequestIdFilter().filter(record) is True
        assert record.request_id == "req-42"
    finally:
        request_id_var.reset(token)


def test_configure_logging_is_idempotent() -> None:
    configure_logging("INFO")
    configure_logging("INFO")
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert isinstance(root.handlers[0].formatter, JsonFormatter)

"""Worker activity tracing: one span per activity execution (OTel, opt-in)."""

from __future__ import annotations

import asyncio

import pytest
from opentelemetry import trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from app.core.observability import trace_activity


@pytest.fixture()
def exporter(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(otel_trace, "get_tracer", provider.get_tracer)
    return exporter


async def _ok(input: dict) -> dict:
    return {"outcome": "success"}


async def _boom(input: dict) -> dict:
    raise RuntimeError("activity failed")


async def _positional(task_id: str) -> dict:
    return {"outcome": "success", "task_id": task_id}


def test_successful_activity_records_span_with_ids_and_outcome(
    exporter: InMemorySpanExporter,
) -> None:
    wrapped = trace_activity(_ok)
    result = asyncio.run(wrapped({"task_id": "t-1", "agent_id": "a-1", "prompt": "secret"}))
    assert result == {"outcome": "success"}
    (span,) = exporter.get_finished_spans()
    assert span.name == "temporal-activity._ok"
    assert span.attributes == {"task_id": "t-1", "agent_id": "a-1", "outcome": "success"}


def test_failing_activity_records_error_status(exporter: InMemorySpanExporter) -> None:
    wrapped = trace_activity(_boom)
    with pytest.raises(RuntimeError, match="activity failed"):
        asyncio.run(wrapped({"task_id": "t-9"}))
    (span,) = exporter.get_finished_spans()
    assert span.status.status_code == StatusCode.ERROR
    assert span.events, "the exception must be recorded on the span"


def test_non_dict_input_is_traced_without_attributes(exporter: InMemorySpanExporter) -> None:
    wrapped = trace_activity(_positional)
    assert asyncio.run(wrapped("t-2"))["outcome"] == "success"
    (span,) = exporter.get_finished_spans()
    assert span.name == "temporal-activity._positional"
    # No input attributes lifted (input is not a mapping); outcome still recorded.
    assert dict(span.attributes or {}) == {"outcome": "success"}


def test_wrapper_preserves_function_name_for_temporal_registration() -> None:
    assert trace_activity(_ok).__name__ == "_ok"


def test_activity_runs_without_configured_provider() -> None:
    # Default global (NoOp) tracer: spans cost nothing, results pass through.
    assert asyncio.run(trace_activity(_ok)({"task_id": "t-3"})) == {"outcome": "success"}

"""OpenTelemetry tracing setup. Opt-in; degrades to a no-op when disabled or unavailable."""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from app.core.config import Settings

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger("harness.observability")

# Correlation attributes lifted off activity inputs (when present) — IDs only,
# never prompts, commands, or payloads.
_ACTIVITY_ATTR_KEYS = ("task_id", "attempt_id", "agent_id", "session_id", "project_id")


def setup_tracing(app: FastAPI, settings: Settings) -> None:
    """Wire OTel tracing onto the app when enabled. Never raises for missing optional deps."""
    if not settings.otel_enabled:
        logger.info("otel disabled")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:  # pragma: no cover — environment specific
        logger.warning("otel dependencies unavailable: %s", exc)
        return

    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.otel_service_name})
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint))
    )
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    logger.info("otel tracing enabled endpoint=%s", settings.otel_exporter_endpoint)


def trace_activity(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Wrap a Temporal activity function in one span per execution.

    Span name ``temporal-activity.<fn>`` with ID-only attributes lifted from
    the input mapping. Without a configured SDK provider the global tracer is
    a no-op, so worker spans cost nothing until ``HARNESS_OTEL_ENABLED=true``;
    if the OTel API itself is unavailable the function runs unwrapped. Stack
    directly under ``@activity.defn`` — direct calls (tests, local runs) get
    spans the same way worker dispatches do.
    """

    @functools.wraps(fn)
    async def _wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            from opentelemetry import trace  # noqa: PLC0415 — optional at runtime
            from opentelemetry.trace import Status, StatusCode  # noqa: PLC0415
        except Exception:  # noqa: BLE001 — tracing is never load-bearing
            return await fn(*args, **kwargs)
        attributes: dict[str, str] = {}
        if args and isinstance(args[0], dict):
            for key in _ACTIVITY_ATTR_KEYS:
                value = args[0].get(key)
                if value:
                    attributes[key] = str(value)
        tracer = trace.get_tracer("ai-harness.worker")
        with tracer.start_as_current_span(
            f"temporal-activity.{fn.__name__}", attributes=attributes
        ) as span:
            try:
                result = await fn(*args, **kwargs)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR))
                raise
            if isinstance(result, dict) and result.get("outcome"):
                span.set_attribute("outcome", str(result["outcome"]))
            return result

    return _wrapper

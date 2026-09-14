"""OpenTelemetry tracing setup. Opt-in; degrades to a no-op when disabled or unavailable."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.config import Settings

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger("harness.observability")


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

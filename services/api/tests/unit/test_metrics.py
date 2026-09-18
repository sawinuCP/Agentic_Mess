"""Unit tests: metrics registry + Prometheus exposition (W3-METRICS-1)."""

from __future__ import annotations

from app.core.metrics import MetricsRegistry


def test_counter_accumulates_by_label_set() -> None:
    registry = MetricsRegistry()
    counter = registry.counter("test_events_total", "test counter")
    counter.inc(event_type="AGENT_CREATED")
    counter.inc(event_type="AGENT_CREATED")
    counter.inc(event_type="TASK_FAILED", amount=3)
    rendered = registry.render_prometheus()
    assert 'test_events_total{event_type="AGENT_CREATED"} 2' in rendered
    assert 'test_events_total{event_type="TASK_FAILED"} 3' in rendered
    assert "# HELP test_events_total test counter" in rendered
    assert "# TYPE test_events_total counter" in rendered


def test_gauge_reflects_last_value() -> None:
    registry = MetricsRegistry()
    gauge = registry.gauge("test_active", "active things")
    gauge.set(3)
    gauge.set(7)
    assert "test_active 7" in registry.render_prometheus()


def test_histogram_buckets_and_sum_count() -> None:
    registry = MetricsRegistry()
    histogram = registry.histogram("test_latency_seconds", "latency", buckets=(0.1, 1.0))
    histogram.observe(0.05)
    histogram.observe(0.5)
    histogram.observe(5.0)
    rendered = registry.render_prometheus()
    assert 'test_latency_seconds_bucket{le="0.1"} 1' in rendered
    assert 'test_latency_seconds_bucket{le="1.0"} 2' in rendered
    assert 'test_latency_seconds_bucket{le="+Inf"} 3' in rendered
    assert "test_latency_seconds_count 3" in rendered
    assert f"test_latency_seconds_sum {0.05 + 0.5 + 5.0}" in rendered

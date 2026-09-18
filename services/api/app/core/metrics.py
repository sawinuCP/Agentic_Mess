"""Minimal in-process metrics registry with Prometheus text exposition (W3-METRICS-1).

Realtime/HTTP observability counters, gauges and histograms are measured
in-process and scraped via ``GET /metrics``. Deliberately dependency-free:
OpenTelemetry tracing (``app.core.observability``) stays untouched and no second
monitoring system is introduced — this is the Prometheus surface the remediation
plan asks for. Thread-safe: event writes happen on worker threads (Temporal
activities, ``asyncio.to_thread``) while the gateway drains on the event loop.
"""

from __future__ import annotations

import threading

LabelSet = tuple[tuple[str, str], ...]

DEFAULT_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)


def _label_key(labels: dict[str, str]) -> LabelSet:
    return tuple(sorted(labels.items()))


def _render_labels(labels: LabelSet, extra: dict[str, str] | None = None) -> str:
    merged = dict(labels)
    if extra:
        merged.update(extra)
    if not merged:
        return ""
    inner = ",".join(f'{k}="{v}"' for k, v in sorted(merged.items()))
    return "{" + inner + "}"


class Counter:
    """Monotonic counter, optionally labeled."""

    def __init__(self, registry: MetricsRegistry, name: str, doc: str) -> None:
        self._registry = registry
        self.name = name
        self.doc = doc

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        with self._registry._lock:
            series = self._registry._counters.setdefault(self.name, {})
            key = _label_key(labels)
            series[key] = series.get(key, 0.0) + amount


class Gauge:
    """Last-value gauge, optionally labeled."""

    def __init__(self, registry: MetricsRegistry, name: str, doc: str) -> None:
        self._registry = registry
        self.name = name
        self.doc = doc

    def set(self, value: float, **labels: str) -> None:
        with self._registry._lock:
            series = self._registry._gauges.setdefault(self.name, {})
            series[_label_key(labels)] = value


class _HistogramState:
    __slots__ = ("counts", "sum", "count")

    def __init__(self, bucket_count: int) -> None:
        self.counts = [0] * bucket_count
        self.sum = 0.0
        self.count = 0


class Histogram:
    """Cumulative-bucket histogram (Prometheus exposition), optionally labeled."""

    def __init__(
        self,
        registry: MetricsRegistry,
        name: str,
        doc: str,
        buckets: tuple[float, ...] = DEFAULT_BUCKETS,
    ) -> None:
        self._registry = registry
        self.name = name
        self.doc = doc
        self.buckets = buckets

    def observe(self, value: float, **labels: str) -> None:
        with self._registry._lock:
            states: dict[LabelSet, _HistogramState] = self._registry._histograms.setdefault(
                self.name, {}
            )
            state = states.setdefault(_label_key(labels), _HistogramState(len(self.buckets)))
            for i, bound in enumerate(self.buckets):
                if value <= bound:
                    state.counts[i] += 1
            state.sum += value
            state.count += 1


class MetricsRegistry:
    """Process-wide registry. One instance lives on ``app.state.metrics``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._docs: dict[str, str] = {}
        self._kinds: dict[str, str] = {}
        self._counters: dict[str, dict[LabelSet, float]] = {}
        self._gauges: dict[str, dict[LabelSet, float]] = {}
        self._histograms: dict[str, dict[LabelSet, _HistogramState]] = {}
        self._histogram_bounds: dict[str, tuple[float, ...]] = {}

    def counter(self, name: str, doc: str) -> Counter:
        with self._lock:
            self._docs.setdefault(name, doc)
            self._kinds.setdefault(name, "counter")
        return Counter(self, name, doc)

    def gauge(self, name: str, doc: str) -> Gauge:
        with self._lock:
            self._docs.setdefault(name, doc)
            self._kinds.setdefault(name, "gauge")
        return Gauge(self, name, doc)

    def histogram(
        self, name: str, doc: str, buckets: tuple[float, ...] = DEFAULT_BUCKETS
    ) -> Histogram:
        with self._lock:
            self._docs.setdefault(name, doc)
            self._kinds.setdefault(name, "histogram")
            self._histogram_bounds.setdefault(name, buckets)
        return Histogram(self, name, doc, buckets)

    def render_prometheus(self) -> str:
        """Prometheus text exposition (version 0.0.4)."""
        lines: list[str] = []
        with self._lock:
            for name, doc in sorted(self._docs.items()):
                kind = self._kinds.get(name, "counter")
                lines.append(f"# HELP {name} {doc}")
                lines.append(f"# TYPE {name} {kind}")
                if kind == "counter":
                    for labels, value in sorted(self._counters.get(name, {}).items()):
                        lines.append(f"{name}{_render_labels(labels)} {value}")
                elif kind == "gauge":
                    for labels, value in sorted(self._gauges.get(name, {}).items()):
                        lines.append(f"{name}{_render_labels(labels)} {value}")
                elif kind == "histogram":
                    bounds = self._histogram_bounds.get(name, DEFAULT_BUCKETS)
                    for labels, state in sorted(self._histograms.get(name, {}).items()):
                        for i, bound in enumerate(bounds):
                            le = _render_labels(labels, {"le": repr(bound)})
                            lines.append(f"{name}_bucket{le} {state.counts[i]}")
                        inf = _render_labels(labels, {"le": "+Inf"})
                        lines.append(f"{name}_bucket{inf} {state.count}")
                        lines.append(f"{name}{_render_labels(labels)}_sum {state.sum}")
                        lines.append(f"{name}{_render_labels(labels)}_count {state.count}")
        return "\n".join(lines) + "\n"


_FALLBACK: MetricsRegistry | None = None


def snapshot_registry() -> MetricsRegistry:
    """Fallback registry for code paths without an app context (worker scripts)."""
    global _FALLBACK  # noqa: PLW0603
    if _FALLBACK is None:
        _FALLBACK = MetricsRegistry()
    return _FALLBACK

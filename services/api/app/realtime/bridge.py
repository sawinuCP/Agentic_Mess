"""Event bridge: durable ``events`` inserts → event bus (committed rows only).

One integration point instead of a call-site sweep: every subsystem that writes
durable events (API routes, orchestration services, Temporal activities and
workflows) automatically streams to realtime subscribers. Mechanics:

* ``after_insert`` (mapper event, inside the flush transaction): stash the
  envelope projection on ``session.info``.
* ``after_commit`` (session event): hand the stashed envelopes to the bus —
  only committed rows are ever published.
* ``after_rollback``: discard the stash.

The bus enqueue is non-blocking (bounded queue, overflow drops the live copy);
execution paths are never slowed by realtime delivery. The bridge is
process-global (installed once at import) and feeds whichever bus the process
activates — the API process and the Temporal worker each run their own.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

from app.core.metrics import MetricsRegistry, snapshot_registry
from app.db.models import Event
from app.realtime.bus import EventBus
from app.realtime.envelope import EventEnvelope, envelope_from_event

logger = logging.getLogger("harness.realtime.bridge")

_STASH_KEY = "_harness_realtime_stash"

_active_bus: EventBus | None = None
_bridge_metrics: dict[str, Any] | None = None


def activate_bus(bus: EventBus) -> None:
    """Point the process-wide bridge at ``bus`` (lifespan startup)."""
    global _active_bus  # noqa: PLW0603
    _active_bus = bus


def deactivate_bus() -> None:
    """Detach the bus (lifespan shutdown) — durable writes continue unaffected."""
    global _active_bus  # noqa: PLW0603
    _active_bus = None


def active_bus() -> EventBus | None:
    return _active_bus


def _metrics(registry: MetricsRegistry | None) -> dict[str, Any]:
    global _bridge_metrics  # noqa: PLW0603
    if _bridge_metrics is None:
        reg = registry or snapshot_registry()
        _bridge_metrics = {
            "processing": reg.histogram(
                "harness_event_processing_latency_seconds",
                "Durable event commit → bus enqueue latency",
            ),
            "errors": reg.counter(
                "harness_realtime_stream_errors_total",
                "Realtime pipeline errors by kind",
            ),
        }
    return _bridge_metrics


def _on_after_insert(mapper: Any, connection: Any, target: Event) -> None:
    bus = _active_bus
    if bus is None or bus._queue is None:  # noqa: SLF001 — fast no-op path
        return
    session = Session.object_session(target)
    if session is None:
        return
    stash: list[EventEnvelope] = session.info.setdefault(_STASH_KEY, [])
    stash.append(envelope_from_event(target))


def _drain_stash(session: Session) -> list[EventEnvelope]:
    stash: list[EventEnvelope] = session.info.pop(_STASH_KEY, [])
    return stash


def _on_after_commit(session: Session) -> None:
    bus = _active_bus
    if bus is None:
        return
    stash = _drain_stash(session)
    if not stash:
        return
    started = time.perf_counter()
    for envelope in stash:
        bus.publish_nowait(envelope)
    _metrics(None)["processing"].observe(time.perf_counter() - started)


def _on_after_rollback(session: Session) -> None:
    _drain_stash(session)


def install_listeners() -> None:
    """Register the bridge listeners once per process (idempotent)."""
    global _installed  # noqa: PLW0603
    if _installed:
        return
    sa_event.listen(Event, "after_insert", _on_after_insert)
    sa_event.listen(Session, "after_commit", _on_after_commit)
    sa_event.listen(Session, "after_rollback", _on_after_rollback)
    _installed = True
    logger.info("realtime_event_bridge_installed")


_installed = False

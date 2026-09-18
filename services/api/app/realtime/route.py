"""SSE endpoint: ``GET /api/events/stream`` (Wave 3, W3-STREAM-1).

Transport decision — SSE, not a second WebSocket:
* execution updates are strictly server → client (the terminal keeps the one
  WebSocket the product actually needs, bidirectionally);
* SSE frames carry the per-project sequence in the ``id`` field so reconnects
  replay exactly what was missed;
* the browser client consumes the stream via ``fetch`` + ReadableStream so the
  Wave 1 ``Authorization: Bearer`` header works — ``EventSource`` cannot set
  headers, and tokens never travel in URLs or query strings.

Connection protocol:
  1. authorize (Wave 1 middleware) + validate ``project_id`` (404 otherwise);
  2. ``GATEWAY_STATUS`` control frame (live | degraded);
  3. durable replay: events with ``project_seq > since`` in ascending order;
     a leading gap (pruned history) emits ``RESYNC_REQUIRED``;
  4. live frames from the gateway; heartbeat comments keep proxies alive.

The stream is a projection — the authoritative state is always re-fetchable via
the existing REST endpoints.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Event, Project
from app.realtime.envelope import EventEnvelope
from app.realtime.gateway import Connection, ConnectionLimitError, ControlFrame, RealtimeGateway

logger = logging.getLogger("harness.realtime.route")

router = APIRouter(tags=["realtime"])

_SSE_MEDIA_TYPE = "text/event-stream"


def _sse_frame(event_type: str, sequence: int | None, data: str) -> str:
    # One `id` field per frame = the per-project sequence cursor (what a
    # reconnecting client needs for Last-Event-ID); event_id rides in the data.
    seq_prefix = f"id: {sequence}\n" if sequence is not None else ""
    return f"event: {event_type}\n{seq_prefix}data: {data}\n\n"


def _envelope_frame(envelope: EventEnvelope) -> str:
    return _sse_frame(envelope.event_type, envelope.sequence, envelope.to_json())


def _control_frame(frame: ControlFrame) -> str:
    return _sse_frame("harness.control", None, frame.to_json())


def _heartbeat() -> str:
    return f": hb {uuid.uuid4().hex[:8]}\n\n"


def _replay_rows(
    factory: sessionmaker[Session], project_id: uuid.UUID, since: int, limit: int
) -> tuple[list[Event], int | None]:
    """Authoritative replay from PostgreSQL (ascending by per-project sequence).

    Returns the rows plus the minimum available sequence for the project, so the
    caller can detect a pruned leading range (``min_seq > since + 1``).
    """
    scope = Event.project_id == project_id
    sequenced = Event.project_seq.is_not(None)

    def _query(session: Session) -> tuple[list[Event], int | None]:
        min_seq = session.scalar(select(func.min(Event.project_seq)).where(scope, sequenced))
        rows = session.scalars(
            select(Event)
            .where(scope, sequenced, Event.project_seq > since)
            .order_by(Event.project_seq.asc())
            .limit(limit)
        ).all()
        return list(rows), int(min_seq) if min_seq is not None else None

    with factory() as session:
        return _query(session)


@router.get("/api/events/stream")
async def event_stream(
    request: Request,
    project_id: uuid.UUID | None = None,
    since: int | None = Query(None, ge=0),
    replay_limit: int = Query(200, ge=1, le=500),
) -> StreamingResponse:
    """Authorized server → client execution event stream (SSE)."""
    settings = request.app.state.settings
    if not getattr(settings, "realtime_enabled", True):
        raise HTTPException(status_code=404, detail="Realtime streaming is disabled")
    gateway: RealtimeGateway | None = getattr(request.app.state, "realtime", None)
    if gateway is None:
        raise HTTPException(status_code=503, detail="Realtime gateway unavailable")

    # Authorization model (Wave 1): a valid bearer token IS the workspace grant
    # (single-operator local posture). The project must exist — client-supplied
    # ids are validated, never trusted blindly.
    if project_id is not None:
        factory = request.app.state.session_factory
        with factory() as session:
            if session.get(Project, project_id) is None:
                raise HTTPException(status_code=404, detail="Project not found")
    if since is not None and project_id is None:
        raise HTTPException(
            status_code=400,
            detail="since is a per-project sequence cursor; pass project_id",
        )

    try:
        conn = gateway.register(project_id)
    except ConnectionLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from None

    headers = {
        "Cache-Control": "no-store",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        _generator(
            request,
            gateway,
            conn,
            project_id,
            since,
            min(replay_limit, settings.realtime_replay_page_cap),
        ),
        media_type=_SSE_MEDIA_TYPE,
        headers=headers,
    )


async def _generator(
    request: Request,
    gateway: RealtimeGateway,
    conn: Connection,
    project_id: uuid.UUID | None,
    since: int | None,
    replay_limit: int,
) -> AsyncIterator[str]:
    try:
        yield _control_frame(
            ControlFrame(
                "GATEWAY_STATUS",
                state="degraded" if gateway.degraded else "live",
                detail="replay-only" if gateway.degraded else "",
            )
        )
        if since is not None and project_id is not None:
            rows, min_seq = await asyncio.to_thread(
                _replay_rows, request.app.state.session_factory, project_id, since, replay_limit
            )
            if min_seq is not None and min_seq > since + 1:
                # History for the requested range is gone (retention): the client
                # must refetch authoritative state — never guess from partials.
                gateway.resyncs.inc()
                yield _control_frame(ControlFrame("RESYNC_REQUIRED", "replay range unavailable"))
            for row in rows:
                yield _envelope_frame(_envelope_of(row))
        while True:
            if conn.dead:
                break
            try:
                item = await asyncio.wait_for(
                    conn.queue.get(), timeout=request.app.state.settings.realtime_heartbeat_seconds
                )
            except TimeoutError:
                yield _heartbeat()
                continue
            if isinstance(item, ControlFrame):
                if item.kind == "DISCONNECT":
                    break
                yield _control_frame(item)
            else:
                yield _envelope_frame(item)
    except asyncio.CancelledError:  # client disconnected
        raise
    finally:
        gateway.unregister(conn)
        logger.info("realtime_connection_closed connection_id=%s", conn.connection_id)


def _envelope_of(row: Event) -> EventEnvelope:
    from app.realtime.envelope import envelope_from_event  # noqa: PLC0415

    return envelope_from_event(row)

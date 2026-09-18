"""HTTP middleware: request-ID correlation, rate limiting, and request logging."""

from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.api.security import PUBLIC_PATHS
from app.core.logging import request_id_var

logger = logging.getLogger("harness.request")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a request id to every request: honored from the client or generated."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("request_failed method=%s path=%s", request.method, request.url.path)
            request_id_var.reset(token)
            raise
        duration_ms = (time.perf_counter() - started) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "request_completed method=%s path=%s status=%d duration_ms=%.1f",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        request_id_var.reset(token)
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP fixed-window rate limiter (W1-RATE-1).

    Single-process in-memory buckets: ``ip -> (window_start, count)``. The
    deployment is a single local control plane (no shared-Redis requirement),
    so local buckets are honest — not a placeholder. Public paths (health/docs
    probes) and CORS preflight (OPTIONS) are exempt. Over-limit responses are
    429 JSON with a ``Retry-After`` header (seconds until the window resets).
    """

    def __init__(
        self,
        app: Any,
        *,
        enabled: bool = True,
        requests_per_window: int = 600,
        window_seconds: float = 60.0,
    ) -> None:
        super().__init__(app)
        self.enabled = enabled and requests_per_window > 0 and window_seconds > 0
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self._buckets: dict[str, tuple[float, int]] = {}
        self._lock = asyncio.Lock()

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if (
            not self.enabled
            or request.method == "OPTIONS"
            or request.url.path in PUBLIC_PATHS
            or any(request.url.path.startswith(f"{p}/") for p in PUBLIC_PATHS)
        ):
            return await call_next(request)
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        async with self._lock:
            start, count = self._buckets.get(client, (now, 0))
            if now - start >= self.window_seconds:
                start, count = now, 0
            if len(self._buckets) > 10_000:
                # Bound memory: drop expired windows, keep the caller.
                expired = [
                    ip
                    for ip, (s, _) in self._buckets.items()
                    if now - s >= self.window_seconds and ip != client
                ]
                for ip in expired:
                    del self._buckets[ip]
            count += 1
            self._buckets[client] = (start, count)
            over_limit = count > self.requests_per_window
            retry_after = max(1, math.ceil(start + self.window_seconds - now))
        if over_limit:
            return JSONResponse(
                status_code=429,
                content={"detail": "rate limit exceeded"},
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)


class MetricsMiddleware(BaseHTTPMiddleware):
    """HTTP request count + duration into the Prometheus registry (W3-METRICS-1).

    Labels are bounded (method × status) — no per-path cardinality explosion.
    """

    def __init__(self, app: Any, registry: Any) -> None:
        super().__init__(app)
        self.requests_total = registry.counter(
            "harness_http_requests_total", "HTTP requests processed"
        )
        self.duration = registry.histogram(
            "harness_http_request_duration_seconds", "HTTP request duration"
        )

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            self.requests_total.inc(method=request.method, status="500")
            self.duration.observe(time.perf_counter() - started, method=request.method)
            raise
        status = str(response.status_code)
        self.requests_total.inc(method=request.method, status=status)
        self.duration.observe(time.perf_counter() - started, method=request.method)
        return response

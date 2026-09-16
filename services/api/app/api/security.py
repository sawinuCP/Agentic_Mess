"""Security middleware (Wave 1, SEC-001/SR-01): optional bearer-token auth.

Policy:
- ``api_token`` empty  → auth disabled (local desktop posture; the app then
  refuses non-loopback binding at startup so this is genuinely local-only).
- ``api_token`` set    → every ``/api/*`` HTTP request and every WebSocket
  handshake must present the token; ``PUBLIC_PATHS`` (health/docs) stay open.

Token transports:
- HTTP: ``Authorization: Bearer <token>``.
- WebSocket: browsers cannot set custom headers, so the client offers the token
  as a WebSocket subprotocol ``bearer.<token>``; the server validates it and
  accepts WITHOUT echoing the subprotocol (the token is never reflected back).
  Non-browser clients may also use the Authorization header.

The presented credential is never logged. Comparison is constant-time.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Awaitable, Callable

from starlette.datastructures import Headers

logger = logging.getLogger("harness.security")

PUBLIC_PATHS = ("/healthz", "/readyz", "/docs", "/redoc", "/openapi.json")
WS_CLOSE_UNAUTHENTICATED = 4401


def extract_bearer(headers: Headers) -> str | None:
    """Bearer token from the Authorization header, if present."""
    authorization = headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def extract_ws_token(headers: Headers) -> str | None:
    """Token from a WebSocket handshake: Authorization header (preferred) or a
    ``bearer.<token>`` WebSocket subprotocol (browser-compatible)."""
    bearer = extract_bearer(headers)
    if bearer:
        return bearer
    for protocol in headers.get("sec-websocket-protocol", "").split(","):
        candidate = protocol.strip()
        if candidate.startswith("bearer."):
            return candidate[len("bearer.") :] or None
    return None


def _is_public(path: str, public_paths: tuple[str, ...]) -> bool:
    return path in public_paths or any(path.startswith(f"{p}/") for p in public_paths)


class AuthMiddleware:
    """Pure-ASGI bearer-token gate covering both HTTP and WebSocket scopes."""

    def __init__(
        self,
        app: Callable[[dict, Callable, Callable], Awaitable[None]],
        *,
        token: str,
        public_paths: tuple[str, ...] = PUBLIC_PATHS,
    ) -> None:
        self.app = app
        self.token = token
        self.public_paths = public_paths

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        scope_type = scope.get("type")
        if not self.token or scope_type not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if scope_type == "http" and scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)  # CORS preflight is unauthenticated
            return
        if _is_public(path, self.public_paths):
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        presented = (
            extract_ws_token(headers) if scope_type == "websocket" else extract_bearer(headers)
        )
        if presented is not None and secrets.compare_digest(presented, self.token):
            await self.app(scope, receive, send)
            return

        logger.warning(
            "AUTHENTICATION_FAILED path=%s reason=%s",
            path,
            "missing" if presented is None else "invalid",
        )
        if scope_type == "websocket":
            await send(
                {
                    "type": "websocket.close",
                    "code": WS_CLOSE_UNAUTHENTICATED,
                    "reason": "unauthenticated",
                }
            )
        else:
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate", b"Bearer"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b'{"detail":"unauthenticated"}'})

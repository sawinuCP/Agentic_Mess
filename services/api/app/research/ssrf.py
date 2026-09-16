"""SSRF guard (Wave 1, SEC-003/SR-03): DNS-aware destination validation.

Validates that a URL's destination is not a private/internal network address.
Both layers are checked (spec: hostname AND resolved addresses):

1. scheme + hostname string rules (localhost names, non-http schemes);
2. DNS resolution — the hostname's resolved IP set must be entirely public
   (defends against hostnames that resolve into private ranges).

Redirects are re-validated by the caller for every hop (no blind following).
``resolver`` is injectable so tests stay deterministic. Note: this validates at
request time; a full rebinding defense would additionally pin connections to the
validated address (deferred, tracked in the security register).
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from collections.abc import Callable
from urllib.parse import urlparse

from app.core.errors import DomainError

logger = logging.getLogger(__name__)

MAX_REDIRECTS = 5
Resolver = Callable[[str], list[str]]


def _default_resolver(hostname: str) -> list[str]:
    """Resolve a hostname to all of its IP strings (best effort)."""
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError:
        return []
    return [str(info[4][0]) for info in infos]


def is_forbidden_ip(ip: str) -> bool:
    """True for loopback/private/link-local/multicast/unspecified/reserved IPs."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return True  # unparseable address → treat as unsafe
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped  # ::ffff:10.0.0.1 is still a private v4
    return (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    )


def assert_url_allowed(
    url: str,
    *,
    allow_private: bool = False,
    resolver: Resolver | None = None,
) -> None:
    """Raise DomainError(403/422) unless ``url`` is a safe http(s) destination."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise DomainError("only http/https URLs can be fetched", 422)
    host = parsed.hostname or ""
    if not host:
        raise DomainError("URL has no hostname", 422)

    if allow_private:
        return

    try:  # IP-literal host: no DNS involved
        address = ipaddress.ip_address(host.strip("[]"))
        if is_forbidden_ip(str(address)):
            logger.warning("SSRF_BLOCKED ip_literal=%s", host)  # host only — never secrets
            raise DomainError(f"destination address is blocked by SSRF policy: {host}", 403)
        return
    except ValueError:
        pass

    if host in ("localhost", "host.docker.internal") or host.endswith(".localhost"):
        logger.warning("SSRF_BLOCKED hostname=%s", host)
        raise DomainError(f"destination host is blocked by SSRF policy: {host}", 403)

    resolve = resolver or _default_resolver
    resolved = resolve(host)
    if not resolved:
        logger.warning("SSRF_BLOCKED unresolvable=%s", host)
        raise DomainError(f"destination host could not be resolved: {host}", 403)
    if any(is_forbidden_ip(ip) for ip in resolved):
        logger.warning("SSRF_BLOCKED resolved_private=%s", host)
        raise DomainError(
            f"destination host resolves to a blocked address (SSRF policy): {host}", 403
        )

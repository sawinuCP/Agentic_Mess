"""Web research service (FR-022, spec §22): provenance-backed evidence packets.

Every fetched page becomes a durable evidence packet: raw content stored as an
artifact, provenance (url/title/timestamp/sha256) recorded, and a T5 context
item created for retrieval. Facts only — interpretation is the agent's job and
is deliberately kept out of the packet (spec §22).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy.orm import Session

from app.core.errors import DomainError
from app.db.models import Artifact, ContextItem
from app.research.ssrf import MAX_REDIRECTS, Resolver, assert_url_allowed

MAX_TEXT_CHARS = 20_000
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True, slots=True)
class EvidencePacket:
    url: str
    final_url: str
    title: str
    fetched_at: str
    sha256: str
    excerpt: str
    artifact_id: str
    context_item_id: str
    confidence: float = 0.9  # fetched pages: high confidence (spec §22)


class _TextExtractor(HTMLParser):
    """Minimal, dependency-free HTML → text (no script/style content)."""

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style"):
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._chunks.append(data.strip())

    def text(self) -> str:
        return " ".join(self._chunks)


def extract_page(html: str) -> dict[str, str]:
    """Title + readable text from an HTML document (bounded)."""
    title_match = _TITLE_RE.search(html)
    title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
    stripped = _TAG_RE.sub(" ", _SCRIPT_STYLE_RE.sub(" ", html))
    parser = _TextExtractor()
    parser.feed(stripped)
    text = re.sub(r"\s+", " ", parser.text()).strip()[:MAX_TEXT_CHARS]
    return {"title": title, "text": text}


async def fetch_page(
    url: str,
    *,
    timeout: float,
    max_bytes: int,
    allow_private: bool = False,
    resolver: Resolver | None = None,
) -> dict[str, Any]:
    """Fetch a page (bounded) with per-hop SSRF validation.

    Redirects are followed MANUALLY so every destination — including each
    redirect target — is subject to the same SSRF policy (hostname + resolved
    addresses). Blind ``follow_redirects=True`` would validate only the initial
    URL and is exactly the rebinding/redirect bypass the guard exists to stop.
    ``resolver`` is injectable for deterministic tests.
    """
    try:
        async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
            current_url = url
            for _hop in range(MAX_REDIRECTS + 1):
                assert_url_allowed(current_url, allow_private=allow_private, resolver=resolver)
                response = await client.get(current_url)
                if not response.is_redirect:
                    break
                location = response.headers.get("location")
                if not location:
                    break  # 3xx without Location: treat as terminal response
                current_url = urljoin(current_url, location)
            else:
                raise DomainError(f"too many redirects fetching {url}", 502)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise DomainError(f"fetch failed for {url}: {exc}", 502) from None
    content_type = response.headers.get("content-type", "")
    if not content_type.startswith(("text/html", "text/plain", "application/json")):
        raise DomainError(f"unsupported content type for research: {content_type}", 422)
    body = response.content[:max_bytes]
    return {
        "url": url,
        "final_url": str(response.url),
        "status": response.status_code,
        "html": body.decode("utf-8", errors="replace"),
        "sha256": hashlib.sha256(body).hexdigest(),
        "truncated": len(response.content) > max_bytes,
    }


async def fetch_and_record(
    db: Session,
    artifact_store: Any,
    project_id: uuid.UUID | None,
    url: str,
    *,
    timeout: float,
    max_bytes: int,
    private_hosts_allowed: bool,
) -> EvidencePacket:
    """Fetch a URL and record the durable evidence packet (artifact + T5 context item)."""
    fetched = await fetch_page(
        url, timeout=timeout, max_bytes=max_bytes, allow_private=private_hosts_allowed
    )
    page = extract_page(fetched["html"])
    excerpt = page["text"][:500]

    blob = artifact_store.put(fetched["html"].encode("utf-8"))
    artifact = Artifact(
        project_id=project_id,
        name=f"web-{fetched['sha256'][:12]}",
        kind="web_content",
        mime="text/html",
        size=blob.size,
        sha256=blob.sha256,
        storage_path=blob.storage_path,
    )
    db.add(artifact)
    context_item = ContextItem(
        project_id=project_id,
        task_id=None,
        tier=5,
        kind="evidence",
        ref=url,
        summary=f"{page['title'] or url} :: {excerpt}",
        tokens_est=max(1, len(excerpt) // 4),
        confidence=0.9,  # fetched pages are high-confidence evidence (spec §22)
    )
    db.add(context_item)
    db.commit()

    return EvidencePacket(
        url=url,
        final_url=fetched["final_url"],
        title=page["title"],
        fetched_at=datetime.now(UTC).isoformat(),
        sha256=fetched["sha256"],
        excerpt=excerpt,
        artifact_id=str(artifact.id),
        context_item_id=str(context_item.id),
    )


async def search_web(query: str, *, max_results: int, timeout: float) -> list[dict[str, str]]:
    """DuckDuckGo Lite search (HTML, no key). Results carry provenance — fetching
    the underlying pages is a separate, explicit ``fetch_and_record`` call so
    agents control what enters context (spec §22: never flood context)."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            response = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise DomainError(f"web search failed: {exc}", 502) from None

    results: list[dict[str, str]] = []
    pattern = re.compile(
        r'<a[^>]*class="result__a"[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    from urllib.parse import parse_qs  # noqa: PLC0415

    for match in pattern.finditer(response.text):
        url = match.group("url")
        if "uddg=" in url:  # DDG wraps targets in a redirect parameter — unwrap it
            parsed = urlparse(url)
            url = parse_qs(parsed.query).get("uddg", [url])[0]
        title = re.sub(r"<[^>]+>", "", match.group("title")).strip()
        results.append({"title": title, "url": url, "source": "duckduckgo"})
        if len(results) >= max_results:
            break
    if not results:
        raise DomainError("web search returned no results (provider may be blocking)", 502)
    return results

"""Wave 1 security units: env sanitizer (SR-02) + SSRF guard (SR-03).

DNS is always stubbed — the SSRF tests are deterministic and never touch real
network resolution.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

from app.core.errors import DomainError
from app.research import service as research_service
from app.research.ssrf import assert_url_allowed, is_forbidden_ip
from app.runtime.env_sandbox import (
    build_agent_environment,
    is_sensitive_name,
    parse_name_list,
)
from app.runtime.runner import run_process

pytestmark = pytest.mark.unit


# --- environment sanitizer (SR-02) -------------------------------------------


HOST_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/home/dev",
    "HARNESS_OPENAI_API_KEY": "sk-host-secret-1",
    "AWS_SECRET_ACCESS_KEY": "aws-secret-2",
    "GITHUB_TOKEN": "ghp-host-secret-3",
    "DATABASE_PASSWORD": "db-secret-4",
    "MY_SERVICE_TOKEN": "svc-token-5",
    "AZURE_CLIENT_SECRET": "azure-6",
    "PIP_INDEX_URL": "https://pypi.org/simple",
    "CARGO_HOME": "/usr/local/cargo",
}


def test_sensitive_names_excluded_by_default() -> None:
    env = build_agent_environment(environ=HOST_ENV)
    assert "HARNESS_OPENAI_API_KEY" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "GITHUB_TOKEN" not in env
    assert "DATABASE_PASSWORD" not in env
    assert "MY_SERVICE_TOKEN" not in env
    assert "AZURE_CLIENT_SECRET" not in env


def test_baseline_names_preserved() -> None:
    env = build_agent_environment(environ=HOST_ENV)
    assert env["PATH"] == "/usr/bin:/bin"
    assert env["HOME"] == "/home/dev"


def test_explicit_allow_inherits_non_sensitive_names() -> None:
    env = build_agent_environment(environ=HOST_ENV, extra_allow=["PIP_INDEX_URL"])
    assert env["PIP_INDEX_URL"] == "https://pypi.org/simple"


def test_allow_never_overrides_the_deny_rule() -> None:
    env = build_agent_environment(environ=HOST_ENV, extra_allow=["MY_SERVICE_TOKEN"])
    assert "MY_SERVICE_TOKEN" not in env


def test_overrides_are_explicit_scoped_injection() -> None:
    env = build_agent_environment(
        environ=HOST_ENV, overrides={"SESSION_DB_PASSWORD": "scoped-value"}
    )
    assert env["SESSION_DB_PASSWORD"] == "scoped-value"


def test_is_sensitive_name_matrix() -> None:
    for name in (
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "SLACK_BOT_USER_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "aws_session_token",
        "MY_PASSWORD",
        "SERVICE_CREDENTIALS",
        "PRIVATE_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
    ):
        assert is_sensitive_name(name), name
    for name in ("PATH", "HOME", "PIP_INDEX_URL", "CARGO_HOME", "NODE_ENV"):
        assert not is_sensitive_name(name), name


def test_parse_name_list() -> None:
    assert parse_name_list("A, B ,,C") == ["A", "B", "C"]
    assert parse_name_list("") == []


@pytest.mark.anyio
async def test_run_process_child_env_is_sanitized(tmp_path: Path) -> None:
    """End-to-end: a child process must not see host secrets via the environment."""
    probe = (
        "import os; "
        "print('KEY=' + os.environ.get('HARNESS_OPENAI_API_KEY', 'MISSING')); "
        "print('HASPATH=' + str('PATH' in os.environ))"
    )
    result = await run_process([sys.executable, "-c", probe], cwd=tmp_path)
    assert result.exit_code == 0
    assert "KEY=MISSING" in result.stdout
    assert "HASPATH=True" in result.stdout


@pytest.mark.anyio
async def test_run_process_env_extra_is_scoped_injection(tmp_path: Path) -> None:
    probe = "import os; print('SCOPED=' + os.environ.get('SCOPED_PROBE', 'MISSING'))"
    result = await run_process(
        [sys.executable, "-c", probe], cwd=tmp_path, env_extra={"SCOPED_PROBE": "injected"}
    )
    assert result.exit_code == 0
    assert "SCOPED=injected" in result.stdout


# --- SSRF guard (SR-03) -------------------------------------------------------


def _resolve(mapping: dict[str, list[str]]):
    return lambda host: mapping.get(host, [])


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/api",
        "http://[::1]/x",
        "http://[::ffff:10.0.0.1]/x",  # IPv4-mapped IPv6
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://10.1.2.3/x",
        "http://192.168.1.50/x",
        "http://172.20.0.1/x",
        "http://localhost/x",
        "http://api.localhost/x",
        "http://host.docker.internal/x",
        "ftp://example.com/file",
    ],
)
def test_blocked_destinations(url: str) -> None:
    with pytest.raises(DomainError):
        assert_url_allowed(url)


def test_public_url_allowed_with_stub_resolver() -> None:
    assert_url_allowed(
        "https://example.com/page",
        resolver=_resolve({"example.com": ["93.184.216.34"]}),
    )


def test_hostname_resolving_to_private_ip_is_blocked() -> None:
    with pytest.raises(DomainError, match="resolves to a blocked address"):
        assert_url_allowed(
            "https://internal.example.com/x",
            resolver=_resolve({"internal.example.com": ["10.0.0.5"]}),
        )


def test_unresolvable_hostname_is_blocked() -> None:
    with pytest.raises(DomainError, match="could not be resolved"):
        assert_url_allowed("https://nonexistent.example.com/x", resolver=_resolve({}))


def test_allow_private_opts_back_in_explicitly() -> None:
    assert_url_allowed("http://127.0.0.1:8000/api", allow_private=True)
    assert_url_allowed("http://localhost/x", allow_private=True)


def test_malformed_url_rejected() -> None:
    with pytest.raises(DomainError):
        assert_url_allowed("not-a-url")
    with pytest.raises(DomainError):
        assert_url_allowed("http:///no-host")


@pytest.mark.parametrize(
    "ip,forbidden",
    [
        ("8.8.8.8", False),
        ("127.0.0.1", True),
        ("169.254.169.254", True),
        ("224.0.0.1", True),  # multicast
        ("0.0.0.0", True),  # unspecified
        ("::ffff:192.168.0.9", True),  # v4-mapped private
        ("2606:4700:4700::1111", False),
    ],
)
def test_is_forbidden_ip(ip: str, forbidden: bool) -> None:
    assert is_forbidden_ip(ip) is forbidden


# --- per-hop redirect validation in the fetch pipeline ------------------------


def _client_factory(transport: httpx.BaseTransport):
    original = httpx.AsyncClient  # capture BEFORE the module attribute is patched

    def factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return original(*args, **kwargs)  # type: ignore[arg-type]

    return factory


def test_fetch_page_redirect_into_private_ip_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A public URL redirecting into metadata/loopback must be stopped before the hop."""
    resolver = _resolve({"public.example.com": ["93.184.216.34"]})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "public.example.com":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})
        return httpx.Response(200, text="metadata-page", headers={"content-type": "text/plain"})

    monkeypatch.setattr(
        research_service.httpx, "AsyncClient", _client_factory(httpx.MockTransport(handler))
    )
    with pytest.raises(DomainError, match="blocked by SSRF policy"):
        asyncio.run(
            research_service.fetch_page(
                "https://public.example.com/", timeout=5.0, max_bytes=10_000, resolver=resolver
            )
        )


def test_fetch_page_follows_safe_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    resolver = _resolve({"a.example.com": ["93.184.216.34"], "b.example.com": ["93.184.216.35"]})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "a.example.com":
            return httpx.Response(302, headers={"location": "https://b.example.com/final"})
        return httpx.Response(200, text="final-page", headers={"content-type": "text/html"})

    monkeypatch.setattr(
        research_service.httpx, "AsyncClient", _client_factory(httpx.MockTransport(handler))
    )
    fetched = asyncio.run(
        research_service.fetch_page(
            "https://a.example.com/start", timeout=5.0, max_bytes=10_000, resolver=resolver
        )
    )
    assert fetched["final_url"] == "https://b.example.com/final"
    assert "final-page" in fetched["html"]

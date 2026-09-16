"""Agent environment sanitizer (Wave 1, SEC-002/SR-02): default-deny env inheritance.

Agent/tool subprocesses must never automatically inherit the API process
environment — the host environment contains credentials (model API keys,
database URLs, cloud credentials) that generated code must not see (spec §31,
SEC-002/§12).

Policy: DEFAULT DENY + EXPLICIT ALLOW.

- A small built-in baseline (PATH, HOME, system dirs, locale) keeps toolchains,
  git and shells functional.
- ``HARNESS_AGENT_ENV_ALLOW`` adds explicitly trusted variable names.
- Sensitive-named variables are never inherited, even if allow-listed by name
  (deny wins); a tool that genuinely needs a secret receives it through an
  explicit per-call ``overrides`` mapping (scoped injection), which is auditable
  at the call site.
- ``overrides`` always win and are applied verbatim — that is the only path for
  secret-shaped values into a subprocess.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping

# Built-in safe baseline (matched case-insensitively; Windows shells and
# toolchains need the system paths, git needs HOME/USERPROFILE for config).
BASELINE_NAMES: frozenset[str] = frozenset(
    {
        "path",
        "home",
        "userprofile",
        "homedrive",
        "homepath",
        "appdata",
        "localappdata",
        "temp",
        "tmp",
        "systemroot",
        "windir",
        "comspec",
        "pathext",
        "programfiles",
        "programfiles(x86)",
        "commonprogramfiles",
        "lang",
        "lc_all",
        "tz",
        "term",
    }
)

# Substrings that mark a variable name as sensitive regardless of allow-lists.
_SENSITIVE_SUBSTRINGS = ("token", "secret", "password", "passwd", "credential", "signature")
_SENSITIVE_PREFIXES = ("aws_", "openai_", "anthropic_", "google_", "azure_", "gcp_", "hcloud_")


def is_sensitive_name(name: str) -> bool:
    """True when a variable name is credential-shaped (deny wins over allow)."""
    fold = name.casefold().replace("-", "_")
    if any(marker in fold for marker in _SENSITIVE_SUBSTRINGS):
        return True
    if any(fold.startswith(prefix) for prefix in _SENSITIVE_PREFIXES):
        return True
    return fold.endswith("_key") or fold == "key"


def build_agent_environment(
    *,
    extra_allow: Iterable[str] | None = None,
    overrides: Mapping[str, str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build a sanitized child-process environment.

    ``extra_allow``      — additional variable names to inherit (case-insensitive;
                           sensitive-named entries are still refused). When omitted,
                           the configured application allowlist applies (see
                           ``configure_agent_env`` / ``HARNESS_AGENT_ENV_ALLOW``).
    ``overrides``        — explicit scoped values applied verbatim after filtering
                           (the only sanctioned path for secret-shaped values).
    ``environ``          — source mapping; defaults to the real process environment
                           (injectable for deterministic tests).
    """
    source = os.environ if environ is None else environ
    # The allowlist always EXTENDS the baseline (never replaces it); the deny
    # rule is applied last and wins over everything.
    names = BASELINE_NAMES | _configured_allow
    if extra_allow is not None:
        names |= {name.strip().casefold() for name in extra_allow if name.strip()}
    allow = {name for name in names if not is_sensitive_name(name)}

    env = {key: value for key, value in source.items() if key.casefold() in allow}
    env.update(overrides or {})
    return env


_configured_allow: frozenset[str] = frozenset()


def configure_agent_env(extra_allow: Iterable[str]) -> None:
    """Set the application-wide agent env allowlist (called once at startup)."""
    global _configured_allow
    _configured_allow = frozenset(name.strip().casefold() for name in extra_allow if name.strip())


def parse_name_list(raw: str) -> list[str]:
    """Parse a comma-separated name list from configuration."""
    return [item.strip() for item in raw.split(",") if item.strip()]

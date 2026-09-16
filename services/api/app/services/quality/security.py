"""Tool-output trust scanning (SEC-006/007): prompt-injection detection.

Tool outputs are untrusted input (SEC-006). Before a compressed observation
enters model context, it is scanned for instruction-override and exfiltration
attempts. Findings are attached to the observation as ``security_flags`` — the
system prompt and gateway policy stay authoritative regardless of what the tool
output claims (SEC-007: policy is independent of model instructions).
"""

from __future__ import annotations

import re

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instruction_override",
        re.compile(
            r"(?i)ignore (all |any |the )?(previous|prior|above) (instructions|prompts|rules)"
        ),
    ),
    (
        "instruction_override",
        re.compile(
            r"(?i)disregard (all |the )?(previous|prior|system|above) (instructions|prompts|rules)"
        ),
    ),
    (
        "system_prompt_probe",
        re.compile(
            r"(?i)(reveal|show|print|repeat) (me )?(your|the) (system )?(prompt|instructions)"
        ),
    ),
    (
        "role_override",
        re.compile(
            r"(?i)you are now (a|an|the) |act as (a|an)?( unaligned| unrestricted| jailbroken)"
        ),
    ),
    (
        "exfiltration",
        re.compile(
            r"(?i)(send|post|upload|curl|wget).{0,40}(api[_-]?key|token|secret|credential|password|\.env)"
        ),
    ),
    (
        "policy_bypass",
        re.compile(
            r"(?i)(bypass|disable|turn off) (the )?(policy|policies|security|sandbox|allowlist)"
        ),
    ),
)


def prompt_injection_scan(text: str) -> list[str]:
    """Return the kinds of injection attempts found in untrusted text."""
    kinds: list[str] = []
    for kind, pattern in _INJECTION_PATTERNS:
        if pattern.search(text or "") and kind not in kinds:
            kinds.append(kind)
    return kinds

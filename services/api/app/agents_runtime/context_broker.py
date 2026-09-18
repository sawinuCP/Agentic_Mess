"""Context broker: tiered context assembly with token budgets (spec §15).

Pure assembly core (unit-testable) + DB loading helpers. Priority order follows
the spec: T0 safety/policy → T1 task+criteria → T2 project/plan state → T3
relevant code/tests → T4 recent history → T5 evidence → T6 raw details.

Two-stage budgeting: whole tiers that do not fit are *truncated* (not dropped)
down to the remaining budget — head for most tiers, tail for history (recent
events matter most) — with an explicit omission marker. A tier is only dropped
when not even a useful stub (``min_section_tokens``) fits. T0 safety is never
dropped; when oversized it is truncated to the budget so the total stays bounded.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TIER_LABELS = {
    0: "Safety & policy",
    1: "Task & acceptance criteria",
    2: "Project & plan state",
    3: "Relevant code & tests",
    4: "Recent task history & messages",
    5: "Research evidence & artifacts",
    6: "Raw details (explicit request only)",
}

# Truncation strategy per tier: history keeps the TAIL (recency wins),
# everything else keeps the HEAD (definitions before details).
_TRUNCATE_KEEP_TAIL_TIERS = frozenset({4})

#: Minimum remaining budget worth spending on a truncated stub (below this the
#: tier is dropped — a 2-token stub carries no signal, only noise).
MIN_SECTION_TOKENS = 16


@dataclass(slots=True)
class ContextSection:
    tier: int
    title: str
    text: str
    tokens_est: int
    truncated_tokens: int = 0  # estimated tokens omitted by truncation (0 = intact)

    @classmethod
    def make(cls, tier: int, title: str, text: str) -> ContextSection:
        from app.agents_runtime.providers import estimate_tokens  # noqa: PLC0415

        return cls(tier=tier, title=title, text=text, tokens_est=estimate_tokens(text))


@dataclass(slots=True)
class ContextBundle:
    sections: list[ContextSection] = field(default_factory=list)
    budget_tokens: int = 8000
    dropped_tiers: list[int] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum(s.tokens_est for s in self.sections)

    def render(self) -> str:
        parts = []
        for section in self.sections:
            header = f"## [{section.tier}] {section.title}"
            if section.truncated_tokens > 0:
                header += f" [truncated ~{section.truncated_tokens} tokens]"
            parts.append(f"{header}\n{section.text}")
        if self.dropped_tiers:
            parts.append(
                "(tiers omitted due to context budget: "
                + ", ".join(f"T{t}" for t in self.dropped_tiers)
                + ")"
            )
        return "\n\n".join(parts)


def truncate_text(text: str, max_tokens: int, *, keep: str = "head") -> tuple[str, int]:
    """Truncate ``text`` to ``max_tokens`` (estimated) with an omission marker.

    ``keep="head"`` keeps the first lines (definitions, task statement);
    ``keep="tail"`` keeps the last lines (recent history). Returns
    ``(new_text, truncated_away_est)``; intact text returns ``(text, 0)``.
    The result (including the marker) never exceeds ``max_tokens``.
    """
    from app.agents_runtime.providers import estimate_tokens  # noqa: PLC0415

    total = estimate_tokens(text)
    if total <= max_tokens:
        return text, 0
    lines = text.splitlines() or [text]
    ordered = list(lines) if keep == "head" else list(reversed(lines))
    kept: list[str] = []
    for line in ordered:
        if estimate_tokens(_compose(kept + [line], keep, _marker(total))) <= max_tokens:
            kept.append(line)
        else:
            break
    # Shrink to a strict fit: the real marker (with the omitted count) may be
    # a token or two larger than the placeholder used above.
    while kept:
        omitted = max(0, total - estimate_tokens(_compose(kept, keep, "")))
        new_text = _compose(kept, keep, _marker(omitted))
        if estimate_tokens(new_text) <= max_tokens:
            return new_text, omitted
        kept.pop()  # pop() always drops the least important kept line
    marker_only = _marker(total)
    return marker_only, total - estimate_tokens(marker_only)


def _compose(kept: list[str], keep: str, marker: str) -> str:
    body = "\n".join(kept if keep == "head" else list(reversed(kept)))
    if not marker:
        return body
    return f"{body}\n{marker}".strip("\n") if keep == "head" else f"{marker}\n{body}".strip("\n")


def _marker(omitted_tokens: int) -> str:
    return f"[…context truncated ~{omitted_tokens} tokens…]"


def assemble(
    *,
    safety_text: str,
    task_text: str,
    state_text: str = "",
    code_text: str = "",
    history_text: str = "",
    evidence_text: str = "",
    budget_tokens: int = 8000,
    min_section_tokens: int = MIN_SECTION_TOKENS,
) -> ContextBundle:
    """Assemble sections tier-by-tier, truncating before dropping.

    T0 safety is always first (truncated to the budget when oversized, never
    dropped). Tiers 1+ that fit are kept whole; tiers that do not fit are
    truncated to the remaining budget when at least ``min_section_tokens``
    remain, and only dropped below that floor. History (T4) truncates from the
    front (recency wins); every other tier truncates from the back.
    """
    candidates = [
        ContextSection.make(0, TIER_LABELS[0], safety_text),
    ]
    if task_text:
        candidates.append(ContextSection.make(1, TIER_LABELS[1], task_text))
    if state_text:
        candidates.append(ContextSection.make(2, TIER_LABELS[2], state_text))
    if code_text:
        candidates.append(ContextSection.make(3, TIER_LABELS[3], code_text))
    if history_text:
        candidates.append(ContextSection.make(4, TIER_LABELS[4], history_text))
    if evidence_text:
        candidates.append(ContextSection.make(5, TIER_LABELS[5], evidence_text))

    bundle = ContextBundle(budget_tokens=budget_tokens)
    for section in candidates:
        remaining = budget_tokens - bundle.total_tokens
        if section.tier == 0:
            if section.tokens_est > budget_tokens:
                text, omitted = truncate_text(section.text, budget_tokens, keep="head")
                section = ContextSection(
                    tier=section.tier,
                    title=section.title,
                    text=text,
                    tokens_est=_estimate(text),
                    truncated_tokens=omitted,
                )
            bundle.sections.append(section)
            continue
        if bundle.total_tokens + section.tokens_est <= budget_tokens:
            bundle.sections.append(section)
        elif remaining >= min_section_tokens:
            keep = "tail" if section.tier in _TRUNCATE_KEEP_TAIL_TIERS else "head"
            text, omitted = truncate_text(section.text, remaining, keep=keep)
            bundle.sections.append(
                ContextSection(
                    tier=section.tier,
                    title=section.title,
                    text=text,
                    tokens_est=_estimate(text),
                    truncated_tokens=omitted,
                )
            )
        else:
            bundle.dropped_tiers.append(section.tier)
    return bundle


def _estimate(text: str) -> int:
    from app.agents_runtime.providers import estimate_tokens  # noqa: PLC0415

    return estimate_tokens(text)

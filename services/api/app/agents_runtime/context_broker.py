"""Context broker: tiered context assembly with token budgets (spec §15).

Pure assembly core (unit-testable) + DB loading helpers. Priority order follows
the spec: T0 safety/policy → T1 task+criteria → T2 project/plan state → T3
relevant code/tests → T4 recent history → T5 evidence → T6 raw details.
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


@dataclass(slots=True)
class ContextSection:
    tier: int
    title: str
    text: str
    tokens_est: int

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
            parts.append(f"## [{section.tier}] {section.title}\n{section.text}")
        if self.dropped_tiers:
            parts.append(
                "(tiers omitted due to context budget: "
                + ", ".join(f"T{t}" for t in self.dropped_tiers)
                + ")"
            )
        return "\n\n".join(parts)


def assemble(
    *,
    safety_text: str,
    task_text: str,
    state_text: str = "",
    code_text: str = "",
    history_text: str = "",
    evidence_text: str = "",
    budget_tokens: int = 8000,
) -> ContextBundle:
    """Assemble sections tier-by-tier, dropping the lowest-priority *last*.

    Higher tiers are more important; when the budget runs out we drop from the
    highest tier number down (raw details first, safety never).
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
        if section.tier == 0:
            bundle.sections.append(section)  # safety is never dropped
            continue
        if bundle.total_tokens + section.tokens_est <= budget_tokens:
            bundle.sections.append(section)
        else:
            bundle.dropped_tiers.append(section.tier)
    return bundle

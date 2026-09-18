"""Context-broker compaction: truncate-before-drop with per-tier strategies."""

from __future__ import annotations

from app.agents_runtime.context_broker import assemble, truncate_text
from app.agents_runtime.providers import estimate_tokens


def test_oversized_task_is_truncated_not_dropped() -> None:
    task = "\n".join(f"requirement line {i}" for i in range(200))
    bundle = assemble(safety_text="policy", task_text=task, budget_tokens=100)
    assert [s.tier for s in bundle.sections] == [0, 1]
    assert bundle.dropped_tiers == []
    task_section = bundle.sections[1]
    assert task_section.truncated_tokens > 0
    assert bundle.total_tokens <= 100
    assert "requirement line 0" in task_section.text  # head kept
    assert "[truncated" in bundle.render()


def test_history_truncation_keeps_the_tail() -> None:
    history = "\n".join(f"event {i}" for i in range(200))
    bundle = assemble(
        safety_text="policy",
        task_text="task",
        history_text=history,
        budget_tokens=60,
    )
    history_section = next(s for s in bundle.sections if s.tier == 4)
    assert history_section.truncated_tokens > 0
    assert "event 199" in history_section.text  # most recent kept
    assert "event 0" not in history_section.text  # oldest compacted away
    assert bundle.total_tokens <= 60


def test_code_truncation_keeps_the_head() -> None:
    code = "\n".join(f"def fn_{i}(): ..." for i in range(200))
    bundle = assemble(safety_text="policy", task_text="t", code_text=code, budget_tokens=60)
    code_section = next(s for s in bundle.sections if s.tier == 3)
    assert "def fn_0" in code_section.text
    assert "def fn_199" not in code_section.text
    assert bundle.total_tokens <= 60


def test_tiny_remaining_budget_still_drops() -> None:
    bundle = assemble(
        safety_text="policy",
        task_text="task details",
        state_text="state",
        code_text="code",
        history_text="history",
        evidence_text="evidence",
        budget_tokens=2,  # only T0 (1 token) fits; stubs below the floor are dropped
    )
    assert [s.tier for s in bundle.sections] == [0, 2]
    assert set(bundle.dropped_tiers) == {1, 3, 4, 5}
    assert all(s.truncated_tokens == 0 for s in bundle.sections)


def test_oversized_safety_is_truncated_never_dropped() -> None:
    safety = "\n".join(f"policy rule {i}" for i in range(100))
    bundle = assemble(safety_text=safety, task_text="task", budget_tokens=50)
    assert [s.tier for s in bundle.sections] == [0]
    assert bundle.sections[0].truncated_tokens > 0
    assert bundle.total_tokens <= 50
    assert bundle.dropped_tiers == [1]


def test_truncate_text_is_intact_within_budget() -> None:
    text, omitted = truncate_text("short text", 100)
    assert (text, omitted) == ("short text", 0)


def test_truncate_text_never_exceeds_max() -> None:
    text = "\n".join(f"line {i} with some content here" for i in range(500))
    for keep in ("head", "tail"):
        new_text, omitted = truncate_text(text, 40, keep=keep)
        assert estimate_tokens(new_text) <= 40
        assert omitted > 0
        assert "truncated" in new_text

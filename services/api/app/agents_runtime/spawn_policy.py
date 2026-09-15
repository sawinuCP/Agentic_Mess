"""Dynamic spawn policy (spec §11/§13, FR-007): bounded recursion, explicit decisions.

Pure functions — unit-testable without a DB or a model. The scheduler consults this
policy before creating child agents/tasks; the policy never touches durable state
(spec §48: the LLM/agent is never the authority on execution state).
"""

from __future__ import annotations

from dataclasses import dataclass

# Roles that may spawn child agents/tasks (spec §11 role catalogue). Workers in the
# execution plane may recurse (debugger → implementer subtasks), bounded by depth.
SPAWNING_ROLES = frozenset(
    {"supervisor", "planner", "implementer", "debugger", "reviewer", "tester", "researcher"}
)

DEFAULT_MAX_DEPTH = 2


@dataclass(frozen=True, slots=True)
class SpawnDecision:
    allowed: bool
    reason: str
    depth: int
    child_depth: int


def evaluate_spawn(
    role: str,
    depth: int,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> SpawnDecision:
    """Decide whether an agent of ``role`` at recursion ``depth`` may spawn a child.

    Rules (spec §9/§11):
    - recursion is bounded: ``depth < max_depth`` (0-based; a depth-2 agent with
      max_depth=2 may not spawn a depth-3 child)
    - only roles in ``SPAWNING_ROLES`` may spawn at all
    """
    if max_depth < 0:
        raise ValueError("max_depth must be >= 0")
    if role not in SPAWNING_ROLES:
        return SpawnDecision(
            allowed=False,
            reason=f"role {role!r} is not a spawning role",
            depth=depth,
            child_depth=depth + 1,
        )
    if depth >= max_depth:
        return SpawnDecision(
            allowed=False,
            reason=f"spawn depth {depth} reached the configured maximum ({max_depth})",
            depth=depth,
            child_depth=depth + 1,
        )
    return SpawnDecision(
        allowed=True, reason="within recursion bound", depth=depth, child_depth=depth + 1
    )


def child_spawn_depth(parent_payload: dict) -> int:
    """The spawn depth a child task inherits from its parent's payload.

    No clamping: the depth records reality, and the *bound* is enforced by
    ``evaluate_spawn``/the scheduler — clamping here would hide violations.
    """
    return int(parent_payload.get("spawn_depth", 0)) + 1


def may_schedule_depth(depth: int, max_depth: int) -> bool:
    """A task at ``depth`` exists because a depth-``depth-1`` agent spawned it;
    top-level tasks (depth 0) are always schedulable."""
    return 0 <= depth <= max_depth

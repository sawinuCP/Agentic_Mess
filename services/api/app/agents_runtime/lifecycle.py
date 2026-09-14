"""Agent lifecycle state machine (spec §12).

The runtime — never the UI and never a model — controls transitions. Every
transition is validated here and produces a durable event at the call site.
"""

from __future__ import annotations

# Spec §12 states.
CREATED = "created"
PLANNING = "planning"
RUNNING = "running"
WAITING = "waiting"
BLOCKED = "blocked"
PAUSE_REQUESTED = "pause_requested"
DRAINING = "draining"
PAUSED = "paused"
RESUMING = "resuming"
VERIFYING = "verifying"
COMPLETED = "completed"
FAILED = "failed"
RECOVERING = "recovering"
CANCELLED = "cancelled"

ALL_STATES = (
    CREATED,
    PLANNING,
    RUNNING,
    WAITING,
    BLOCKED,
    PAUSE_REQUESTED,
    DRAINING,
    PAUSED,
    RESUMING,
    VERIFYING,
    COMPLETED,
    FAILED,
    RECOVERING,
    CANCELLED,
)

# Allowed transitions (spec §12 diagram; CANCELLED reachable from any active state).
TRANSITIONS: dict[str, tuple[str, ...]] = {
    CREATED: (PLANNING, RUNNING, CANCELLED),
    PLANNING: (RUNNING, FAILED, CANCELLED),
    RUNNING: (WAITING, BLOCKED, PAUSE_REQUESTED, VERIFYING, FAILED, CANCELLED),
    WAITING: (RUNNING, BLOCKED, FAILED, CANCELLED),
    BLOCKED: (RUNNING, FAILED, CANCELLED),
    PAUSE_REQUESTED: (PAUSED, RUNNING, CANCELLED),  # checkpoint, then suspended
    DRAINING: (PAUSED, RUNNING, CANCELLED),
    PAUSED: (RESUMING, CANCELLED),
    RESUMING: (RUNNING, FAILED, CANCELLED),
    VERIFYING: (COMPLETED, RUNNING, FAILED, CANCELLED),
    FAILED: (RECOVERING, CANCELLED),
    RECOVERING: (RUNNING, PLANNING, FAILED, CANCELLED),
    COMPLETED: (),
    CANCELLED: (),
}


class InvalidTransition(Exception):
    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"Invalid agent transition: {current} -> {target}")
        self.current = current
        self.target = target
        self.message = f"Invalid agent transition: {current} -> {target}"


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, ())


def assert_transition(current: str, target: str) -> None:
    if current not in ALL_STATES:
        raise InvalidTransition(current, target)
    if target not in ALL_STATES:
        raise InvalidTransition(current, target)
    if not can_transition(current, target):
        raise InvalidTransition(current, target)


def next_work_state(current: str) -> str:
    """State an agent enters when it resumes producing work (used by the runtime)."""
    if current in (PAUSED, RESUMING, RECOVERING, CREATED, PLANNING):
        return RUNNING
    return current

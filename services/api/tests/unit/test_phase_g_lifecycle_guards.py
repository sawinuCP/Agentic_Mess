"""Phase G6: exhaustive lifecycle transition guards (spec §12).

The existing suite proves happy paths; this file locks the negative space:
every (current, target) pair NOT in TRANSITIONS raises, terminal states have
no exits, and CANCELLED stays reachable from every active state. Routes and
services must validate through ``assert_transition`` — arbitrary mutation is
a boundary violation.
"""

from __future__ import annotations

import pytest

from app.agents_runtime import lifecycle


def test_every_unlisted_pair_is_illegal() -> None:
    illegal = 0
    for current in lifecycle.ALL_STATES:
        for target in lifecycle.ALL_STATES:
            if target in lifecycle.TRANSITIONS[current]:
                assert lifecycle.can_transition(current, target)
            else:
                illegal += 1
                assert not lifecycle.can_transition(current, target)
                with pytest.raises(lifecycle.InvalidTransition):
                    lifecycle.assert_transition(current, target)
    # The table is intentionally sparse: most pairs are illegal.
    assert illegal > len(lifecycle.ALL_STATES) * 2


def test_terminal_states_have_no_exits() -> None:
    for terminal in ("completed", "cancelled"):
        assert lifecycle.TRANSITIONS[terminal] == ()
        for target in lifecycle.ALL_STATES:
            assert not lifecycle.can_transition(terminal, target)


def test_cancel_reachable_from_every_active_state() -> None:
    for state in lifecycle.ALL_STATES:
        if state in ("completed", "cancelled"):
            continue
        assert lifecycle.can_transition(state, "cancelled"), state


def test_no_self_transitions() -> None:
    for state in lifecycle.ALL_STATES:
        assert not lifecycle.can_transition(state, state), state


def test_completed_only_via_verifying() -> None:
    for state in lifecycle.ALL_STATES:
        if state == "verifying":
            assert lifecycle.can_transition(state, "completed")
        else:
            assert not lifecycle.can_transition(state, "completed"), state

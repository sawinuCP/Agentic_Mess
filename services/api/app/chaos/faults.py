"""Deterministic failure injection for tests (Wave 11 §6).

Explicitly opt-in: every hook consults a ``FaultState`` built from settings
(``HARNESS_FAILURE_INJECTION`` master switch + ``HARNESS_FAILURE_INJECTION_POINTS``).
Production behavior is untouched when disabled (one boolean check). Points:

* ``model_unavailable`` — every provider call raises transiently.
* ``model_flaky:N`` — the first N provider calls per route raise transiently.
* ``tool_fail`` — tool invocations return a failed observation (simulated).
* ``tool_timeout`` — tool invocations return a timed-out observation.

Faults never bypass policy: the gateway hook runs *after* ``check_policy``,
and injected errors are labeled ``(simulation)`` while carrying realistic,
classifiable text (toolchain/provider wording the classifier understands).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FaultState:
    """Per-run fault configuration. ``enabled`` is the master switch."""

    enabled: bool = False
    points: dict[str, str] = field(default_factory=dict)
    _counters: dict[str, int] = field(default_factory=dict, repr=False)

    @classmethod
    def from_settings(cls, settings: Any) -> FaultState:
        enabled = bool(getattr(settings, "failure_injection", False))
        points: dict[str, str] = {}
        raw = str(getattr(settings, "failure_injection_points", "") or "")
        for item in raw.split(","):
            item = item.strip()
            if not item:
                continue
            name, _, arg = item.partition(":")
            points[name.strip()] = arg.strip()
        return cls(enabled=enabled, points=points)

    def armed(self, point: str, scope: str = "") -> bool:
        """True when the point should fire now (consumes flaky budgets).

        ``scope`` partitions flaky budgets (e.g. per provider route) so one
        flaky dependency does not consume another's budget.
        """
        if not self.enabled or point not in self.points:
            return False
        arg = self.points[point]
        if not arg:
            return True
        try:
            remaining = int(arg)
        except ValueError:
            return True
        key = f"remaining:{point}:{scope}"
        left = self._counters.get(key, remaining)
        if left <= 0:
            return False
        self._counters[key] = left - 1
        return True

    def reset(self) -> None:
        self._counters.clear()

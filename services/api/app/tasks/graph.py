"""Task dependency-graph integrity.

Cycle detection runs at creation/edit time (spec §18: detect dependency cycles
before scheduling where possible). Pure functions — unit-testable without a DB.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping


class DependencyCycleError(Exception):
    def __init__(self, cycle: list[uuid.UUID]) -> None:
        pretty = " -> ".join(str(node)[:8] for node in cycle)
        super().__init__(f"Task dependency cycle detected: {pretty}")
        self.cycle = cycle
        self.message = f"Task dependency cycle detected: {pretty}"


def find_cycle(
    *,
    task_id: uuid.UUID,
    depends_on: list[uuid.UUID],
    existing: Mapping[uuid.UUID, list[uuid.UUID]],
) -> list[uuid.UUID] | None:
    """Return a cycle (list of task ids ending with ``task_id``) if adding the edges
    ``task_id -> depends_on`` to the graph ``existing`` (task -> its dependencies)
    would create one; ``None`` when the graph stays acyclic."""
    graph: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for node, deps in existing.items():
        graph[node].extend(deps)
    graph[task_id].extend(depends_on)

    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[uuid.UUID, int] = defaultdict(int)
    stack: list[uuid.UUID] = []

    def visit(node: uuid.UUID) -> list[uuid.UUID] | None:
        color[node] = GREY
        stack.append(node)
        for dep in graph.get(node, []):
            if color[dep] == GREY:
                cycle = stack[stack.index(dep) :]
                cycle.append(dep)
                return cycle
            if color[dep] == WHITE:
                found = visit(dep)
                if found is not None:
                    return found
        stack.pop()
        color[node] = BLACK
        return None

    return visit(task_id)


def ready_status(depends_on_ids: list[uuid.UUID], completed_ids: set[uuid.UUID]) -> str:
    """A task with unmet dependencies is blocked; otherwise it is ready to run."""
    return "ready" if all(dep in completed_ids for dep in depends_on_ids) else "blocked"

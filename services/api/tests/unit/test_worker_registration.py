"""Worker registration guard: every activity the workflow can dispatch must be
registered on the worker, or the run fails at that step with zero product
signal (found live: snapshot_attempt_activity unregistered → orphaned task).

Pure AST check over workflows.py (dispatched names), activities/__init__.py
(public surface) and worker.py (registered list). No Temporal server needed.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"


def _dispatched_activities() -> set[str]:
    """Activity names passed to workflow.execute_activity in workflows.py."""
    tree = ast.parse((APP / "durable" / "workflows.py").read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "execute_activity"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            found.add(node.args[0].value)
    return found


def _worker_registered() -> set[str]:
    """Names in the activities=[...] list of worker.py."""
    tree = ast.parse((APP / "durable" / "worker.py").read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "activities":
            value = node.value
            if isinstance(value, ast.List):
                for elt in value.elts:
                    if isinstance(elt, ast.Name):
                        found.add(elt.id)
    return found


def _public_surface() -> set[str]:
    """Names exported by app.durable.activities (__all__)."""
    tree = ast.parse((APP / "durable" / "activities" / "__init__.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)
            and isinstance(node.value, ast.List)
        ):
            return {
                elt.value
                for elt in node.value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            }
    return set()


def test_workflow_dispatches_are_registered() -> None:
    dispatched = _dispatched_activities()
    assert dispatched, "expected execute_activity call sites in workflows.py"
    registered = _worker_registered()
    missing = sorted(dispatched - registered)
    assert missing == [], f"activities dispatched but not registered on the worker: {missing}"


def test_worker_registers_only_public_activities() -> None:
    registered = _worker_registered()
    public = _public_surface()
    assert registered <= public, f"worker registers non-public names: {sorted(registered - public)}"

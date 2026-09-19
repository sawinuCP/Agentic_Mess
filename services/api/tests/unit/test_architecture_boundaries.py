"""Architectural boundary enforcement (Phase F7): CI-failing AST guards.

These tests lock the target-architecture dependency rules that hold today:
deterministic workflows, framework-free agent domain, and no engine
construction in routes. Each rule cites its rationale; violations fail here
before they reach production.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(("." * node.level + node.module) if node.level else node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def _app_files(*parts: str) -> list[Path]:
    base = APP.joinpath(*parts)
    if base.is_file():
        return [base]
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)


def _imported_names(path: Path) -> set[str]:
    """Fully-qualified imported names (module.attr) for precision checks."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            base = ("." * node.level + node.module) if node.level else node.module
            for alias in node.names:
                found.add(f"{base}.{alias.name}")
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def test_workflows_stay_deterministic() -> None:
    """Temporal replay safety: no clocks, RNG, UUIDs or infra imports."""
    names = _imported_names(APP / "durable" / "workflows.py")
    modules = {name.split(".")[0] for name in names}
    assert not (modules & {"random", "sqlalchemy", "fastapi", "nats", "redis", "httpx"}), sorted(
        names
    )
    assert "uuid.uuid4" not in names, sorted(names)
    datetime_uses = {name for name in names if name.split(".")[0] == "datetime"}
    assert datetime_uses <= {"datetime.timedelta"}, sorted(datetime_uses)
    # The pure policy core is the only app import allowance.
    app_imports = {name for name in names if name.startswith("app.")}
    assert app_imports == {"app.services.orchestration.recovery.recovery_decision"}, sorted(
        app_imports
    )


def test_agent_domain_has_no_database_coupling() -> None:
    """Policy/routing stays testable without Postgres."""
    offenders = []
    for path in _app_files("agents_runtime"):
        names = _imports(path)
        bad = sorted(
            name
            for name in names
            if name.split(".")[0] == "sqlalchemy" or name.startswith("app.db")
        )
        if bad:
            offenders.append((path.name, bad))
    assert offenders == []


def test_routes_never_construct_engines() -> None:
    """Sessions arrive via get_db; routes must not own engine lifecycle."""
    offenders = []
    for path in _app_files("api", "routes"):
        text = path.read_text(encoding="utf-8")
        if "create_engine" in text or "build_session_factory" in text:
            offenders.append(path.name)
    assert offenders == []


def test_realtime_projection_never_writes_domain_tables() -> None:
    """The live hop is a projection: gateway/bus/route must not import
    write-capable domain services (they read rows and publish only)."""
    offenders = []
    for path in [
        APP / "realtime" / "gateway.py",
        APP / "realtime" / "bus.py",
        APP / "realtime" / "route.py",
        APP / "realtime" / "bridge.py",
    ]:
        names = _imports(path)
        bad = sorted(
            name
            for name in names
            if name.startswith("app.services.")
            or name.startswith("app.durable.")
            or name.startswith("app.agents_runtime.")
        )
        if bad:
            offenders.append((path.name, bad))
    assert offenders == []

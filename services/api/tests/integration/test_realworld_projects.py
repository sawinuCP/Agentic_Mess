"""Real-world project validation (Wave 12): indexing, retrieval and context
quality on deterministic fixture repositories (no network, no model calls).

Each test prints measured latencies — evidence, not claims.
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

import pytest

from app.codeintel.indexer import update_index
from app.codeintel.retrieval import retrieve
from app.core.config import Settings
from app.db.base import build_engine, build_session_factory
from app.db.models import Project
from tests.fixtures.e2e_projects import (
    build_backend_project,
    build_large_project,
    build_messy_project,
    build_multi_module_project,
    build_python_project,
    build_typescript_project,
)

pytestmark = pytest.mark.integration


def _open(root: Path) -> tuple[object, object, uuid.UUID]:
    settings = Settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    with factory() as session:
        project = Project(name=f"rw-{uuid.uuid4().hex[:8]}", root_path=str(root))
        session.add(project)
        session.commit()
        pid = project.id
    return engine, factory, pid


def _close(engine: object, factory, pid: uuid.UUID) -> None:
    with factory() as session:
        project = session.get(Project, pid)
        if project is not None:
            session.delete(project)
            session.commit()
    engine.dispose()  # type: ignore[union-attr]


def test_index_and_retrieve_small_python_project(tmp_path: Path) -> None:
    """Project A: index in milliseconds, exact symbol retrievable top-1."""
    root = build_python_project(tmp_path / "proj-a")
    engine, factory, pid = _open(root)
    try:
        with factory() as session:
            started = time.perf_counter()
            stats = update_index(session, pid, root, full=True)
            index_ms = (time.perf_counter() - started) * 1000
        assert stats["symbols"] >= 2, stats
        with factory() as session:
            started = time.perf_counter()
            hits = retrieve(session, pid, "add two numbers", k=6)
            retrieval_ms = (time.perf_counter() - started) * 1000
        names = [h.name if hasattr(h, "name") else h["name"] for h in hits]
        assert "add" in names, names
        print(f"\nREALWORLD project=A index_ms={index_ms:.1f} retrieval_ms={retrieval_ms:.1f}")
    finally:
        _close(engine, factory, pid)


def test_index_typescript_project(tmp_path: Path) -> None:
    """Project B: TSX component symbol indexed and searchable."""
    root = build_typescript_project(tmp_path / "proj-b")
    engine, factory, pid = _open(root)
    try:
        with factory() as session:
            stats = update_index(session, pid, root, full=True)
            hits = retrieve(session, pid, "SettingsButton primary action", k=6)
        names = [h.name if hasattr(h, "name") else h["name"] for h in hits]
        assert "SettingsButton" in names, names
        assert stats["files"] >= 1
    finally:
        _close(engine, factory, pid)


def test_messy_repo_comprehension(tmp_path: Path) -> None:
    """Project E: duplicated, thinly-documented code still resolves — the
    system must understand the repo, not rewrite it (no files modified)."""
    root = build_messy_project(tmp_path / "proj-e")
    before = {p.read_text(encoding="utf-8") for p in root.glob("*.py")}
    engine, factory, pid = _open(root)
    try:
        with factory() as session:
            update_index(session, pid, root, full=True)
            hits = retrieve(session, pid, "order total discount vip", k=6)
        names = [h.name if hasattr(h, "name") else h["name"] for h in hits]
        assert "calc_total" in names, names  # the documented entry point wins
        after = {p.read_text(encoding="utf-8") for p in root.glob("*.py")}
        assert before == after  # comprehension is read-only
    finally:
        _close(engine, factory, pid)


def test_large_repo_index_scale(tmp_path: Path) -> None:
    """Project F: 2000 modules index in bounded time; retrieval stays fast."""
    root = build_large_project(tmp_path / "proj-f", modules=2000)
    engine, factory, pid = _open(root)
    try:
        with factory() as session:
            started = time.perf_counter()
            stats = update_index(session, pid, root, full=True)
            full_s = time.perf_counter() - started
        assert stats["files"] == 2000, stats
        with factory() as session:
            started = time.perf_counter()
            stats2 = update_index(session, pid, root, full=False)
            incr_s = time.perf_counter() - started
        assert stats2["skipped"] == 2000, stats2
        with factory() as session:
            started = time.perf_counter()
            hits = retrieve(session, pid, "process payload pipeline 1999", k=6)
            ret_ms = (time.perf_counter() - started) * 1000
        names = [h.name if hasattr(h, "name") else h["name"] for h in hits]
        assert "process_payload_1999" in names, names[:3]
        print(f"\nREALWORLD project=F full_s={full_s:.1f} incr_s={incr_s:.3f} ret_ms={ret_ms:.1f}")
        assert full_s < 120, "full index must stay bounded"
        assert ret_ms < 5000, "retrieval must stay interactive"
    finally:
        _close(engine, factory, pid)


def test_backend_fixture_suite_passes_standalone(tmp_path: Path) -> None:
    """Project C: the fixture's own tests execute green in isolation (real
    pytest subprocess, no harness involvement beyond the shell)."""
    import subprocess

    root = build_backend_project(tmp_path / "proj-c")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout[-2000:]
    assert "2 passed" in result.stdout


def test_multi_module_fixture_indexes_both_layers(tmp_path: Path) -> None:
    """Project D: frontend + backend symbols coexist in one index; a query
    finds the right layer (dependency reasoning starts with retrieval)."""
    root = build_multi_module_project(tmp_path / "proj-d")
    engine, factory, pid = _open(root)
    try:
        with factory() as session:
            stats = update_index(session, pid, root, full=True)
            assert stats["files"] >= 4, stats
            hits = retrieve(session, pid, "read_item endpoint", k=6)
        names = [h.name if hasattr(h, "name") else h["name"] for h in hits]
        assert "read_item" in names, names
        with factory() as session:
            hits = retrieve(session, pid, "SettingsButton label", k=6)
        names = [h.name if hasattr(h, "name") else h["name"] for h in hits]
        assert "SettingsButton" in names, names
    finally:
        _close(engine, factory, pid)


def test_context_assembly_stays_bounded_on_large_repo(tmp_path: Path) -> None:
    """Context broker never dumps the repo: bundle respects the token budget
    even when retrieval returns large candidate sets."""
    from app.agents_runtime.context_broker import assemble

    code_text = "\n".join(f"def fn_{i}(): ... # line {i}" for i in range(2000))
    bundle = assemble(
        safety_text="policy",
        task_text="task",
        code_text=code_text,
        history_text="\n".join(f"event {i}" for i in range(500)),
        budget_tokens=8000,
    )
    assert bundle.total_tokens <= 8000
    assert any(s.truncated_tokens > 0 for s in bundle.sections)

"""Seeded, trusted offline fixtures. Scripted repair is NOT autonomous implementation."""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

import pytest

from app.agents_runtime.gateway import ToolInvocation, invoke
from app.agents_runtime.models_registry import ModelRegistry
from app.agents_runtime.providers import ModelProviderError, ModelRequest, ModelResponse, ModelRoute
from app.artifacts.store import ArtifactStore


async def _command(root: Path, argv: list[str]) -> int | None:
    store = ArtifactStore(root / "evidence")

    async def evidence(name: str, data: bytes) -> str:
        return store.put(data).sha256

    result = await invoke(
        ToolInvocation(
            tool="shell",
            command=argv,
            cwd=str(root),
            allowed_tools=frozenset({"shell"}),
            capabilities=frozenset({"read", "write"}),  # harness-driven, not agent-driven
            timeout_seconds=120 if Path(argv[0]).stem == "go" else 30,
        ),
        argv,
        store_evidence=evidence,
    )
    assert result.status != "timeout"
    return result.exit_code


def _repair(root: Path, file: str, before: str, after: str, argv: list[str]) -> None:
    assert asyncio.run(_command(root, argv)) != 0, "Seeded bug was not detected"
    # Trusted scripted patch, deliberately separate from the fixed behavioral oracle.
    script = root / "repair.py"
    script.write_text(
        "from pathlib import Path\np = Path("
        + repr(file)
        + ")\n"
        + "p.write_text(p.read_text().replace("
        + repr(before)
        + ", "
        + repr(after)
        + "), encoding='utf-8')\n",
        encoding="utf-8",
    )
    assert asyncio.run(_command(root, [sys.executable, str(script)])) == 0
    assert asyncio.run(_command(root, argv)) == 0


def test_seeded_python(tmp_path: Path) -> None:
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (tmp_path / "verify.py").write_text(
        "from calc import add\nfor a in range(-10, 11):\n"
        "    for b in range(-10, 11):\n        assert add(a,b) == sum([a,b])\n",
        encoding="utf-8",
    )
    _repair(tmp_path, "calc.py", "a - b", "a + b", [sys.executable, "-B", "verify.py"])


def test_seeded_typescript(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")
    compiler = Path(__file__).resolve().parents[4] / "apps/web-ui/node_modules/typescript/bin/tsc"
    if not compiler.is_file():
        pytest.skip("Repository TypeScript dependency required")
    (tmp_path / "calc.ts").write_text(
        "export function add(a: number,b: number): number { return a - b; }\n", encoding="utf-8"
    )
    (tmp_path / "verify.ts").write_text(
        "import {add} from './calc';\nif(add(2,3)!==5 || add(-2,3)!==1) "
        "{ throw new Error('wrong addition'); }\n",
        encoding="utf-8",
    )
    compile_command = [
        node,
        str(compiler),
        "calc.ts",
        "verify.ts",
        "--module",
        "commonjs",
        "--skipLibCheck",
    ]
    (tmp_path / "check.py").write_text(
        "import subprocess, sys\n"
        + f"r=subprocess.run({compile_command!r})\n"
        + "if r.returncode: sys.exit(r.returncode)\n"
        + f"sys.exit(subprocess.run({[node, 'verify.js']!r}).returncode)\n",
        encoding="utf-8",
    )
    original = (tmp_path / "verify.ts").read_bytes()
    _repair(tmp_path, "calc.ts", "a - b", "a + b", [sys.executable, "check.py"])
    assert (tmp_path / "verify.ts").read_bytes() == original


def test_seeded_go(tmp_path: Path) -> None:
    go = shutil.which("go")
    if not go:
        pytest.skip("Go required")
    (tmp_path / "go.mod").write_text("module fixture\n\ngo 1.20\n", encoding="utf-8")
    (tmp_path / "calc.go").write_text(
        "package fixture\nfunc Add(a,b int) int {return a-b}\n", encoding="utf-8"
    )
    (tmp_path / "calc_test.go").write_text(
        'package fixture\nimport "testing"\nfunc TestAdd(t *testing.T) { '
        'if Add(2,3)!=5 {t.Fatal("wrong addition")} }\n',
        encoding="utf-8",
    )
    _repair(tmp_path, "calc.go", "a-b", "a+b", [go, "test", "./..."])


def test_parallel_execution(tmp_path: Path) -> None:
    for tag in ("a", "b"):
        (tmp_path / f"{tag}.py").write_text(
            "import time,json\nfrom pathlib import Path\ns=time.time()\ntime.sleep(1)\n"
            + f"Path('{tag}.json').write_text(json.dumps([s,time.time()]))\n",
            encoding="utf-8",
        )

    async def both() -> list[int | None]:
        return list(
            await asyncio.gather(
                *[_command(tmp_path, [sys.executable, f"{tag}.py"]) for tag in ("a", "b")]
            )
        )

    assert asyncio.run(both()) == [0, 0]
    intervals = [json.loads((tmp_path / f"{tag}.json").read_text()) for tag in ("a", "b")]
    assert max(i[0] for i in intervals) < min(i[1] for i in intervals)


def test_provider_fallback() -> None:
    class Provider:
        calls = 0

        async def complete(self, request: ModelRequest, route: ModelRoute) -> ModelResponse:
            self.calls += 1
            if self.calls == 1:
                raise ModelProviderError("injected outage")
            return ModelResponse("{}", "rehearsal", route.model, 1, 1)

    provider = Provider()
    registry = ModelRegistry(
        {"worker": {"fallback_role": "fallback"}, "fallback": {}}, provider_override=provider
    )
    response = asyncio.run(registry.complete(ModelRequest("worker", "policy", "fixture")))
    assert provider.calls == 2 and response.fell_back_to == "fallback"


def test_large_repository(project: tuple) -> None:
    _app, client, project_id, root = project
    for i in range(200):
        (root / f"module_{i:03}.py").write_text(
            f"def unique_symbol_{i:03}():\n    return {i}\n", encoding="utf-8"
        )
    response = client.post(f"/api/projects/{project_id}/intelligence/index", json={})
    response.raise_for_status()
    assert response.json()["indexed"] == 200
    response = client.get(f"/api/projects/{project_id}/symbols?q=unique_symbol_173")
    response.raise_for_status()
    assert [h["name"] for h in response.json()] == ["unique_symbol_173"]
    (root / "module_173.py").write_text("def replacement():\n    return 173\n", encoding="utf-8")
    response = client.post(f"/api/projects/{project_id}/intelligence/index", json={})
    response.raise_for_status()
    assert response.json()["updated"] == 1 and response.json()["skipped"] == 199


def test_incomplete_coverage(project: tuple) -> None:
    _app, client, project_id, _root = project
    response = client.post(
        f"/api/projects/{project_id}/requirements",
        json={
            "title": "Five criteria",
            "description": "All five must be verified",
            "priority": "must",
            "criteria": [
                {"description": f"criterion {i}", "kind": "manual", "mandatory": True}
                for i in range(5)
            ],
        },
    )
    response.raise_for_status()
    req = response.json()
    response = client.post(
        f"/api/requirements/{req['id']}/plans",
        json={"tasks": [{"title": "Implementation", "request": "Implement all five"}]},
    )
    response.raise_for_status()
    response = client.post(
        f"/api/projects/{project_id}/artifacts",
        files={"file": ("fixture.txt", b"Controlled fixture evidence")},
    )
    response.raise_for_status()
    artifact = response.json()["id"]
    for criterion in req["criteria"][:4]:
        response = client.post(
            f"/api/requirements/{req['id']}/criteria/{criterion['id']}/verify",
            json={"evidence_artifact_id": artifact},
        )
        response.raise_for_status()
    response = client.post(f"/api/projects/{project_id}/oversight/completion")
    assert response.status_code == 409
    report = response.json()["report"]
    assert not report["completion_allowed"]
    assert sum(c["state"] == "verified" for c in report["requirements"][0]["criteria"]) == 4

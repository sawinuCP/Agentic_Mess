"""Deterministic real-world fixture repositories (Wave 12).

Generated into tmp directories (never committed blobs): small Python,
TypeScript/React, FastAPI backend, multi-module app, messy legacy repo, and
a large generated repo. All local-only: no network, no model calls.
"""

from __future__ import annotations

from pathlib import Path


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


PY_CALC = '''"""Simple calculator (Project A fixture)."""


def add(a, b):
    """Add two numbers."""
    return a + b


def multiply(a, b):
    """Multiply two numbers."""
    return a * b
'''

PY_CALC_TEST = '''"""Unit tests for the calculator."""

from calc import add, multiply


def test_add():
    assert add(2, 3) == 5


def test_multiply():
    assert multiply(2, 3) == 6
'''

TS_BUTTON = """import React from 'react';

export interface ButtonProps {
  label: string;
  onClick: () => void;
  disabled?: boolean;
}

/** Primary action button used across the settings screens. */
export function SettingsButton({ label, onClick, disabled }: ButtonProps) {
  return (
    <button className="btn-primary" disabled={disabled} onClick={onClick}>
      {label}
    </button>
  );
}
"""

TS_BUTTON_TEST = """import { SettingsButton } from './SettingsButton';

describe('SettingsButton', () => {
  it('renders the label', () => {
    const el = SettingsButton({ label: 'Save', onClick: () => undefined });
    expect(el).toBeDefined();
  });
});
"""

FASTAPI_APP = '''"""Tiny FastAPI service (Project C fixture)."""

from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/items/{item_id}")
def read_item(item_id: int):
    return {"item_id": item_id, "name": f"item-{item_id}"}
'''

FASTAPI_TEST = '''"""Endpoint tests (run with pytest, no server needed)."""

from fastapi.testclient import TestClient

from service import app

client = TestClient(app)


def test_health():
    assert client.get("/health").status_code == 200


def test_read_item():
    response = client.get("/items/42")
    assert response.json() == {"item_id": 42, "name": "item-42"}
'''

MESSY_LEGACY = '''"""Order processing (Project E fixture: messy but working)."""

# TODO: nobody knows what the magic numbers mean
DISCOUNT = 0.9  # used only for vip?
TAX = 1.2


def calc_total(items, vip=False):
    # FIXME: duplicates calc2 below, slightly different rounding
    total = 0
    for i in items:
        total = total + i["price"] * i["qty"]
    if vip == True:
        total = total * DISCOUNT
    total = total * TAX  # tax applied after discount?? check with accounting
    return round(total, 2)


def calc2(items):
    t = sum([x["price"] * x["qty"] for x in items])
    return round(t * 1.2, 2)


class OrderRepo:
    """saves orders somewhere. db details lost in the wiki migration."""

    def __init__(self, db):
        self.db = db

    def save_order(self, order):
        return self.db.insert("orders", order)

    def find_order(self, order_id):
        return self.db.get("orders", order_id)
'''

MESSY_TEST = '''"""Existing tests for the messy repo (all passing)."""

from legacy import calc2, calc_total


def test_calc_total_basic():
    assert calc_total([{"price": 10, "qty": 2}]) == 24.0


def test_calc2_basic():
    assert calc2([{"price": 10, "qty": 2}]) == 24.0
'''


def build_python_project(root: Path) -> Path:
    """Project A: small Python package with unit tests + lint config."""
    _write(root, "calc.py", PY_CALC)
    _write(root, "test_calc.py", PY_CALC_TEST)
    _write(root, "pyproject.toml", "[tool.ruff]\nline-length = 100\n")
    return root


def build_typescript_project(root: Path) -> Path:
    """Project B: small React component with a test + tsconfig."""
    _write(root, "package.json", '{"name": "fixture-b", "type": "module"}\n')
    _write(
        root,
        "tsconfig.json",
        '{"compilerOptions": {"jsx": "react", "strict": true, "noEmit": true}}\n',
    )
    _write(root, "src/SettingsButton.tsx", TS_BUTTON)
    _write(root, "src/SettingsButton.test.ts", TS_BUTTON_TEST)
    return root


def build_backend_project(root: Path) -> Path:
    """Project C: FastAPI service with endpoint tests (no server needed)."""
    _write(root, "service.py", FASTAPI_APP)
    _write(root, "test_service.py", FASTAPI_TEST)
    _write(root, "requirements.txt", "fastapi\nhttpx\n")
    return root


def build_multi_module_project(root: Path) -> Path:
    """Project D: frontend + backend + shared config for parallel/dependency tests."""
    build_typescript_project(root / "frontend")
    build_backend_project(root / "backend")
    _write(root, "docker-compose.yml", "services:\n  api:\n    build: ./backend\n")
    return root


def build_messy_project(root: Path) -> Path:
    """Project E: messy legacy repo — duplication, TODOs, thin docs, green tests."""
    _write(root, "legacy.py", MESSY_LEGACY)
    _write(root, "test_legacy.py", MESSY_TEST)
    _write(root, "README.md", "# orders\n\nit works. don't touch calc_total.\n")
    return root


def build_large_project(root: Path, modules: int = 2000) -> Path:
    """Project F: large generated repo for indexing-scale measurement."""
    for i in range(modules):
        _write(
            root,
            f"pkg_{i // 100}/mod_{i}.py",
            f'"""Generated module {i}."""\n\n\ndef process_payload_{i}(payload):\n'
            f'    """Transform payload for pipeline {i}."""\n'
            f"    return {{'id': {i}, 'data': payload}}\n",
        )
    return root

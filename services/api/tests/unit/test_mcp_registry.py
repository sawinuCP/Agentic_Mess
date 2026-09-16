"""MCP registry units: config parsing, authorization, schema validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.errors import DomainError
from app.mcp.registry import load_config, tool_allowed, validate_arguments


def _write_config(tmp_path: Path, payload: dict) -> str:
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_load_config_missing_file_fails_closed(tmp_path: Path) -> None:
    assert load_config("") == []  # no config configured → no servers
    with pytest.raises(DomainError) as excinfo:
        load_config(str(tmp_path / "nope.json"))  # configured but missing → loud failure
    assert excinfo.value.status_code == 503


def test_load_config_rejects_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(DomainError) as excinfo:
        load_config(str(path))
    assert excinfo.value.status_code == 500


def test_load_config_parses_servers_and_allowlists(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        {
            "servers": [
                {"name": "a", "command": ["python", "a.py"]},
                {"name": "b", "command": ["python", "b.py"], "allowed_tools": ["echo"]},
            ]
        },
    )
    servers = load_config(path)
    assert [s.name for s in servers] == ["a", "b"]
    assert tool_allowed(servers[0], "anything") is True  # default allow-all
    assert tool_allowed(servers[1], "echo") is True
    assert tool_allowed(servers[1], "other") is False


def test_load_config_rejects_entries_without_command(tmp_path: Path) -> None:
    path = _write_config(tmp_path, {"servers": [{"name": "broken"}]})
    with pytest.raises(DomainError) as excinfo:
        load_config(path)
    assert excinfo.value.status_code == 500


def test_validate_arguments_checks_required_keys() -> None:
    schema = {"type": "object", "required": ["text"]}
    validate_arguments(schema, {"text": "hi"})
    with pytest.raises(DomainError) as excinfo:
        validate_arguments(schema, {})
    assert excinfo.value.status_code == 422

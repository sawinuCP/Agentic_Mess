"""Credential scanner units (Phase 8 security gate)."""

from __future__ import annotations

from pathlib import Path

from app.services.quality import secrets


def test_detects_high_confidence_credentials() -> None:
    text = "\n".join(
        [
            "aws_access_key_id = AKIAIOSFODNN7EXAMPLE",
            "GITHUB_TOKEN=ghp_abcabcabcabcabcabcabcabcabcabcabcabc",
            "-----BEGIN RSA PRIVATE KEY-----",
            "api_key = 'super-secret-value-1'",
            "Authorization: Bearer abcdef.ghijklmnopqrstuvwxyz0123456789",
        ]
    )
    kinds = {finding.kind for finding in secrets.scan_text(text)}
    assert "aws_access_key" in kinds
    assert "github_token" in kinds
    assert "private_key" in kinds
    assert "generic_api_key_assignment" in kinds
    assert "bearer_token_literal" in kinds


def test_benign_code_is_clean() -> None:
    text = "\n".join(
        [
            "def deploy(api_key: str) -> None:",
            "    client = Client(auth=api_key)",
            "    # TODO rotate credentials",
            "password = os.environ['PASSWORD']",
        ]
    )
    assert secrets.scan_text(text) == []


def test_findings_are_redacted() -> None:
    finding = secrets.scan_text("token = 'abcdefghijklmnop'")[0]
    assert "abcdefghijklmnop" not in finding.snippet
    assert "«redacted»" in finding.snippet


def test_scan_paths_skips_excluded_dirs_and_reports_findings(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "leak.txt").write_text("AKIAIOSFODNN7EXAMPLE", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "clean.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "config.py").write_text("AWS_SECRET = 'A'/+\n", encoding="utf-8")

    summary = secrets.scan_paths(tmp_path)
    assert summary["scanned_files"] == 2  # .git excluded
    assert summary["finding_count"] == 0  # config.py pattern requires 40-char secret form

    (tmp_path / "config.py").write_text(
        "key='ghp_abcabcabcabcabcabcabcabcabcabcabcabc'\n", encoding="utf-8"
    )
    summary = secrets.scan_paths(tmp_path)
    assert summary["finding_count"] == 1
    assert str(summary["findings"][0]["file"]).endswith("config.py")

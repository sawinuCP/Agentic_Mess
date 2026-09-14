"""Toolchain DTOs."""

from pydantic import BaseModel


class ToolRunRequest(BaseModel):
    tool: str
    path: str | None = None
    language: str | None = None


class ToolRunOut(BaseModel):
    language: str
    tool: str
    command: list[str]
    exit_code: int | None
    timed_out: bool
    truncated: bool
    duration_ms: int
    stdout: str
    stderr: str
    diagnostics: list[str]
    file_content: str | None = None
    artifact_ids: list[str] = []


class LanguageOut(BaseModel):
    id: str
    name: str
    monaco_language: str
    manifests: list[str]
    file_count: int
    tools: list[str]
    availability: dict[str, dict]


class ProjectToolchainsOut(BaseModel):
    languages: list[LanguageOut]
    diagnostics: list[str]
    override_file: bool

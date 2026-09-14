"""Toolchain endpoints: registry, availability, detection, run (FR-002/003/004/019)."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.api.deps import get_files_service, get_project
from app.db.models import Project
from app.events.recorder import record_event
from app.files.service import ProjectFiles
from app.toolchains.detection import DetectedLanguage, detect_languages
from app.toolchains.errors import ToolchainError
from app.toolchains.overrides import OVERRIDE_REL, load_definition
from app.toolchains.registry import BUILTIN_LANGUAGES
from app.toolchains.service import ToolRunResult, availability_for, run_tool

router = APIRouter(tags=["toolchains"])


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


def _defn_out(lang: DetectedLanguage, availability: dict[str, dict]) -> LanguageOut:
    return LanguageOut(
        id=lang.id,
        name=lang.name,
        monaco_language=lang.monaco_language,
        manifests=lang.manifests,
        file_count=lang.file_count,
        tools=lang.tools,
        availability=availability,
    )


@router.get("/api/toolchains")
async def list_registry() -> list[dict]:
    """The builtin registry itself (LANG-001 metadata)."""
    return [
        {
            "id": d.id,
            "name": d.name,
            "monaco_language": d.monaco_language,
            "extensions": sorted(d.extensions),
            "manifests": list(d.manifests),
            "tools": {
                name: {"argv": list(spec.argv), "in_place": spec.in_place}
                for name, spec in sorted(d.tools.items())
            },
        }
        for d in BUILTIN_LANGUAGES.values()
    ]


@router.get("/api/toolchains/availability")
async def registry_availability() -> dict[str, dict[str, dict]]:
    return {lang_id: availability_for(defn) for lang_id, defn in BUILTIN_LANGUAGES.items()}


@router.get("/api/projects/{project_id}/toolchains", response_model=ProjectToolchainsOut)
async def project_toolchains(
    project_id: uuid.UUID, project: Project = Depends(get_project)
) -> ProjectToolchainsOut:
    root = Path(project.root_path)
    diagnostics: list[str] = []
    languages: list[LanguageOut] = []
    for detected in detect_languages(root):
        try:
            _definition, diags = load_definition(detected.id, root)
            diagnostics.extend(diags)
        except ToolchainError as exc:
            diagnostics.append(exc.message)
            continue
        availability = availability_for(_definition)
        languages.append(_defn_out(detected, availability))
    return ProjectToolchainsOut(
        languages=languages,
        diagnostics=diagnostics,
        override_file=(root / OVERRIDE_REL).is_file(),
    )


@router.post("/api/projects/{project_id}/toolchains/run", response_model=ToolRunOut)
async def run_tool_endpoint(
    body: ToolRunRequest,
    request: Request,
    project: Project = Depends(get_project),
    files: ProjectFiles = Depends(get_files_service),
) -> ToolRunOut:
    root = Path(project.root_path)
    result: ToolRunResult = await run_tool(
        root, files, body.tool, language_id=body.language, file_rel=body.path
    )
    await record_event(
        request.app.state.session_factory,
        "TOOL_RUN_COMPLETED",
        project_id=project.id,
        payload={
            "language": result.language,
            "tool": result.tool,
            "exit_code": result.exit_code,
            "duration_ms": result.result.duration_ms,
            "path": body.path,
        },
    )
    return ToolRunOut(
        language=result.language,
        tool=result.tool,
        command=result.command,
        exit_code=result.result.exit_code,
        timed_out=result.result.timed_out,
        truncated=result.result.truncated,
        duration_ms=result.result.duration_ms,
        stdout=result.result.stdout,
        stderr=result.result.stderr,
        diagnostics=result.diagnostics,
        file_content=result.file_content,
    )

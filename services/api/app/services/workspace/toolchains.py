"""Toolchain service: detection, availability and tool runs with evidence capture.

Thin orchestration over ``app.toolchains`` (registry/detection/execution) plus
artifact persistence for large raw outputs (FR-019, FR-023, LANG-005).
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.artifacts.store import ArtifactStore
from app.files.service import ProjectFiles
from app.schemas.workspace.toolchains import LanguageOut, ProjectToolchainsOut, ToolRunOut
from app.services.core.artifacts import record_blob
from app.toolchains.detection import detect_languages
from app.toolchains.errors import ToolchainError
from app.toolchains.overrides import OVERRIDE_REL, load_definition
from app.toolchains.registry import BUILTIN_LANGUAGES
from app.toolchains.service import ToolRunResult, availability_for
from app.toolchains.service import run_tool as execute_tool

EVIDENCE_MIN_BYTES = 2000


def registry_view() -> list[dict]:
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


def registry_availability() -> dict[str, dict[str, dict]]:
    return {lang_id: availability_for(defn) for lang_id, defn in BUILTIN_LANGUAGES.items()}


def project_toolchains(db: Session, root: Path) -> ProjectToolchainsOut:
    diagnostics: list[str] = []
    languages: list[LanguageOut] = []
    for detected in detect_languages(root):
        try:
            definition, diags = load_definition(detected.id, root)
            diagnostics.extend(diags)
        except ToolchainError as exc:
            diagnostics.append(exc.message)
            continue
        languages.append(
            LanguageOut(
                id=detected.id,
                name=detected.name,
                monaco_language=detected.monaco_language,
                manifests=detected.manifests,
                file_count=detected.file_count,
                tools=detected.tools,
                availability=availability_for(definition),
            )
        )
    return ProjectToolchainsOut(
        languages=languages,
        diagnostics=diagnostics,
        override_file=(root / OVERRIDE_REL).is_file(),
    )


def _persist_output(
    db: Session, store: ArtifactStore, project_id: uuid.UUID, name: str, text: str
) -> str | None:
    if len(text.encode("utf-8")) < EVIDENCE_MIN_BYTES:
        return None
    artifact = record_blob(db, store, project_id, name, "raw_output", text.encode("utf-8"))
    return str(artifact.id)


async def run_tool(
    db: Session,
    store: ArtifactStore,
    root: Path,
    files: ProjectFiles,
    project_id: uuid.UUID,
    tool: str,
    language_id: str | None,
    file_rel: str | None,
) -> ToolRunOut:
    """Execute a tool and capture large outputs as evidence artifacts (LANG-005)."""
    result: ToolRunResult = await execute_tool(
        root, files, tool, language_id=language_id, file_rel=file_rel
    )
    artifact_ids: list[str] = []
    stdout_id = _persist_output(
        db, store, project_id, f"{tool}-{result.language}-stdout.log", result.result.stdout
    )
    if stdout_id:
        artifact_ids.append(stdout_id)
    stderr_id = _persist_output(
        db, store, project_id, f"{tool}-{result.language}-stderr.log", result.result.stderr
    )
    if stderr_id:
        artifact_ids.append(stderr_id)
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
        artifact_ids=artifact_ids,
    )

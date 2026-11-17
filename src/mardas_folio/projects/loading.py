"""Workspace loading, validation snapshots, and public payload assembly."""
from __future__ import annotations
from pathlib import Path
from typing import Callable, Iterable
from ..book import BookManifest, BookRenderBundle, load_book_manifest, render_book
from ..config import CONFIG_FILENAME, load_project_config
from ..diagnostics import Diagnostic, has_errors
from .validation import project_config_diagnostics, validate_book_project
from ..render_contracts import CancellationCallback, RenderCancelledError
from .models import ProjectWorkspace, WorkspaceError
from .discovery import _relative_path, _workspace_files
from .files import (
    _config_sha256,
)


def validate_workspace_book_payload(
    workspace: ProjectWorkspace,
    *,
    progress: Callable[[str, float], None] | None = None,
    cancelled: CancellationCallback | None = None,
) -> tuple[dict[str, object], ProjectWorkspace]:
    refreshed = refresh_workspace(workspace, progress=progress, cancelled=cancelled)
    payload = workspace_payload(refreshed)
    return {
        "ok": bool(payload["ok"] and refreshed.manifest is not None),
        "book": payload.get("book"),
        "diagnostics": payload["diagnostics"],
    }, refreshed


def _diagnostic_dict(item: Diagnostic, root: Path) -> dict[str, object]:
    data = item.to_dict()
    if item.path is not None:
        relative = _relative_path(root, item.path)
        data["path"] = relative if relative is not None else item.path.name
    return data


def load_workspace(
    target: Path,
    *,
    progress: Callable[[str, float], None] | None = None,
    cancelled: CancellationCallback | None = None,
    validate_content: bool = True,
) -> ProjectWorkspace:
    if cancelled and cancelled():
        raise RenderCancelledError("Project discovery was cancelled.")
    resolved = target.expanduser().resolve(strict=False)
    explicit = resolved if resolved.is_file() and resolved.name == CONFIG_FILENAME else None
    start = resolved.parent if resolved.is_file() else resolved
    result = load_project_config(start=start, explicit_path=explicit, disabled=False)
    diagnostics = list(result.diagnostics)
    config = result.config
    if config.path is None:
        diagnostics.append(
            Diagnostic(
                "MARDAS-E801",
                "error",
                f"Studio project mode requires {CONFIG_FILENAME}.",
                path=resolved,
                hint="Run `folio init --book` or pass a directory containing mardas.toml.",
            )
        )
        raise WorkspaceError(
            f"Studio project mode requires {CONFIG_FILENAME}.",
            code="project_config_not_found",
            diagnostics=diagnostics,
        )
    diagnostics.extend(project_config_diagnostics(config))

    manifest: BookManifest | None = None
    bundle: BookRenderBundle | None = None
    if config.values.get("book_chapters") and not has_errors(diagnostics) and validate_content:
        manifest, bundle, book_diagnostics = validate_book_project(
            config,
            progress=progress,
            cancelled=cancelled,
        )
        diagnostics.extend(book_diagnostics)
    elif not has_errors(diagnostics):
        manifest, manifest_diagnostics = load_book_manifest(config)
        # A project without [book] is still a valid Studio project. Only retain
        # diagnostics when the user actually configured Book Mode.
        if config.values.get("book_chapters"):
            diagnostics.extend(manifest_diagnostics)
        if manifest is not None and validate_content:
            bundle, render_diagnostics = render_book(manifest)
            diagnostics.extend(render_diagnostics)

    files, file_diagnostics = _workspace_files(config.root, manifest, cancelled=cancelled)
    diagnostics.extend(file_diagnostics)
    return ProjectWorkspace(
        config=config,
        manifest=manifest,
        bundle=bundle,
        diagnostics=tuple(diagnostics),
        files=files,
    )


def refresh_workspace(
    workspace: ProjectWorkspace,
    *,
    progress: Callable[[str, float], None] | None = None,
    cancelled: CancellationCallback | None = None,
) -> ProjectWorkspace:
    if workspace.config.path is None:
        raise WorkspaceError(
            "Studio project configuration is unavailable.", code="project_unavailable"
        )
    return load_workspace(workspace.config.path, progress=progress, cancelled=cancelled)


def workspace_diagnostics_payload(
    workspace: ProjectWorkspace, diagnostics: Iterable[Diagnostic]
) -> list[dict[str, object]]:
    """Serialize diagnostics without exposing paths outside the project root."""
    return [_diagnostic_dict(item, workspace.root) for item in diagnostics]


def workspace_payload(workspace: ProjectWorkspace) -> dict[str, object]:
    root = workspace.root
    manifest = workspace.manifest
    book: dict[str, object] | None = None
    if manifest is not None:
        book = {
            "enabled": True,
            "title": workspace.config.values.get("title") or root.name,
            "language": workspace.config.values.get("document_language"),
            "direction": workspace.config.values.get("document_direction"),
            "output": _relative_path(root, manifest.output_path) or manifest.output_path.name,
            "output_name": manifest.output_path.name,
            "chapter_count": len(manifest.chapters),
            "chapters": [
                {
                    "index": chapter.index,
                    "path": chapter.path.relative_to(root).as_posix(),
                    "title": chapter.title_override,
                }
                for chapter in manifest.chapters
            ],
        }
    return {
        "enabled": True,
        "name": root.name,
        "config": workspace.config.path.relative_to(root).as_posix()
        if workspace.config.path
        else None,
        "config_sha256": _config_sha256(workspace),
        "files": [item.to_dict() for item in workspace.files],
        "book": book,
        "ok": not has_errors(workspace.diagnostics),
        "diagnostics": [_diagnostic_dict(item, root) for item in workspace.diagnostics],
    }

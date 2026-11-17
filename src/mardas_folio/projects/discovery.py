"""Bounded, cancellable workspace file discovery."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable
from ..book import BookManifest
from ..config import CONFIG_FILENAME
from ..diagnostics import Diagnostic
from ..render_contracts import CancellationCallback, RenderCancelledError
from .paths import WORKSPACE_IGNORED_PARTS as WORKSPACE_IGNORED_PARTS
from .models import ProjectWorkspace as ProjectWorkspace, WorkspaceError as WorkspaceError, WorkspaceFile as WorkspaceFile

MAX_WORKSPACE_FILES = 2_000
MAX_WORKSPACE_SCAN_ENTRIES = 20_000
MAX_WORKSPACE_DEPTH = 32
WORKSPACE_TEXT_SUFFIXES = frozenset(
    {
        ".md",
        ".markdown",
        ".mdown",
        ".mkd",
        ".toml",
        ".bib",
        ".json",
        ".txt",
        ".yaml",
        ".yml",
    }
)











def _contains_path(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _relative_path(root: Path, path: Path | None) -> str | None:
    if path is None:
        return None
    resolved = path.expanduser().resolve(strict=False)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return None


def _kind_for_path(path: Path) -> str:
    if path.name == CONFIG_FILENAME:
        return "config"
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown", ".mdown", ".mkd"}:
        return "markdown"
    if suffix == ".bib":
        return "bibliography"
    if suffix == ".json":
        return "json"
    if suffix == ".toml":
        return "toml"
    return "text"


def _safe_workspace_file(
    workspace: ProjectWorkspace,
    relative_path: str,
    *,
    must_exist: bool = True,
) -> Path:
    raw = str(relative_path or "").replace("\\", "/").strip()
    if not raw or "\x00" in raw:
        raise WorkspaceError("Project file path is required.", code="invalid_project_path")
    candidate_input = Path(raw)
    if candidate_input.is_absolute() or any(
        part in {"", ".", ".."} for part in candidate_input.parts
    ):
        raise WorkspaceError(
            "Project file path must be a normalized relative path.",
            code="invalid_project_path",
        )
    if any(
        part in WORKSPACE_IGNORED_PARTS or part.startswith(".") for part in candidate_input.parts
    ):
        raise WorkspaceError(
            "Project file path points to a hidden or generated directory.",
            code="blocked_project_path",
        )
    root = workspace.root.resolve()
    unresolved = root / candidate_input
    cursor = root
    for part in candidate_input.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise WorkspaceError(
                "Project file paths must not traverse symbolic links.",
                code="blocked_project_symlink",
            )
    candidate = unresolved.resolve(strict=False)
    if not _contains_path(root, candidate):
        raise WorkspaceError(
            "Project file path escapes the project root.",
            code="project_path_escape",
        )
    if (
        candidate.suffix.lower() not in WORKSPACE_TEXT_SUFFIXES
        and candidate.name != CONFIG_FILENAME
    ):
        raise WorkspaceError(
            "Studio only edits supported project text files.",
            code="unsupported_project_file",
        )
    if must_exist:
        if candidate.is_symlink() or not candidate.is_file():
            raise WorkspaceError(
                "Project file does not exist or is not a regular file.",
                code="project_file_not_found",
                status=404,
            )
    return candidate


def _chapter_map(manifest: BookManifest | None) -> dict[Path, tuple[int, str | None]]:
    if manifest is None:
        return {}
    return {
        chapter.path.resolve(): (chapter.index, chapter.title_override)
        for chapter in manifest.chapters
    }


def _iter_workspace_files(
    root: Path, *, cancelled: CancellationCallback | None = None
) -> Iterable[Path | Diagnostic]:
    """Discover text files within bounded traversal and report omitted entries."""

    pending = [(root, 0)]
    scanned = 0
    depth_limited = False
    while pending:
        if cancelled and cancelled():
            raise RenderCancelledError("Project discovery was cancelled.")
        current_path, depth = pending.pop()
        directories: list[Path] = []
        files: list[Path] = []
        scan_limited = False
        try:
            # os.walk materializes every name in a directory before yielding.
            # Stream entries so a directory of non-text files is bounded too.
            with os.scandir(current_path) as entries:
                for entry in entries:
                    if cancelled and cancelled():
                        raise RenderCancelledError("Project discovery was cancelled.")
                    if scanned >= MAX_WORKSPACE_SCAN_ENTRIES:
                        scan_limited = True
                        break
                    scanned += 1
                    if entry.name.startswith(".") or entry.is_symlink():
                        continue
                    path = current_path / entry.name
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name in WORKSPACE_IGNORED_PARTS:
                                continue
                            if depth >= MAX_WORKSPACE_DEPTH:
                                depth_limited = True
                            else:
                                directories.append(path)
                        elif entry.is_file(follow_symlinks=False) and (
                            path.name == CONFIG_FILENAME
                            or path.suffix.lower() in WORKSPACE_TEXT_SUFFIXES
                        ):
                            files.append(path)
                    except OSError:
                        continue
        except OSError:
            continue
        yield from sorted(files, key=lambda path: path.name.casefold())
        if scan_limited:
            yield Diagnostic(
                "MARDAS-W802",
                "warning",
                f"Studio project discovery is limited to {MAX_WORKSPACE_SCAN_ENTRIES} entries.",
                path=root,
                hint="Exclude generated directories or split very large projects.",
            )
            break
        pending.extend(
            (path, depth + 1)
            for path in sorted(directories, key=lambda path: path.name.casefold(), reverse=True)
        )
    if depth_limited:
        yield Diagnostic(
            "MARDAS-W803",
            "warning",
            f"Studio project discovery is limited to {MAX_WORKSPACE_DEPTH} directory levels.",
            path=root,
            hint="Move source files into shallower directories.",
        )


def _workspace_files(
    root: Path,
    manifest: BookManifest | None,
    *,
    cancelled: CancellationCallback | None = None,
) -> tuple[tuple[WorkspaceFile, ...], tuple[Diagnostic, ...]]:
    chapter_map = _chapter_map(manifest)
    files: list[WorkspaceFile] = []
    diagnostics: list[Diagnostic] = []
    for path in _iter_workspace_files(root, cancelled=cancelled):
        if isinstance(path, Diagnostic):
            diagnostics.append(path)
            continue
        if len(files) >= MAX_WORKSPACE_FILES:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-W801",
                    "warning",
                    f"Studio project tree is limited to {MAX_WORKSPACE_FILES} text files.",
                    path=root,
                    hint="Exclude generated directories or split very large projects.",
                )
            )
            break
        try:
            size = path.stat().st_size
            chapter = chapter_map.get(path.resolve())
        except OSError:
            continue
        files.append(
            WorkspaceFile(
                path=path.relative_to(root).as_posix(),
                size=size,
                kind=_kind_for_path(path),
                chapter_index=chapter[0] if chapter else None,
                chapter_title=chapter[1] if chapter else None,
            )
        )
    files.sort(
        key=lambda item: (
            0 if item.chapter_index is not None else 1,
            item.chapter_index or 0,
            item.path.casefold(),
        )
    )
    return tuple(files), tuple(diagnostics)

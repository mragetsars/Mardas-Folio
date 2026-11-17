"""Bounded workspace reads, revision checks, and conflict-aware atomic saves."""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from pathlib import Path
from typing import Callable

from ..citations import load_bibliography
from ..config import CONFIG_FILENAME, tomllib
from ..diagnostics import has_errors
from ..file_io import FILE_WRITE_LOCK, atomic_write_text, sync_directory
from .discovery import _kind_for_path, _safe_workspace_file
from .models import ProjectWorkspace, WorkspaceError

MAX_WORKSPACE_TEXT_BYTES = 4 * 1024 * 1024
_WORKSPACE_SAVE_LOCK = FILE_WRITE_LOCK


def _file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_file_snapshot(path: Path) -> tuple[bytes, os.stat_result]:
    try:
        with path.open("rb") as handle:
            stat_result = os.fstat(handle.fileno())
            data = handle.read(MAX_WORKSPACE_TEXT_BYTES + 1)
    except OSError as exc:
        raise WorkspaceError(
            "Project file could not be read.",
            code="project_file_unreadable",
        ) from exc
    if len(data) > MAX_WORKSPACE_TEXT_BYTES:
        raise WorkspaceError(
            f"Project text file exceeds the {MAX_WORKSPACE_TEXT_BYTES}-byte Studio limit.",
            code="project_file_too_large",
            status=413,
        )
    return data, stat_result


def _read_bytes(path: Path) -> bytes:
    return _read_file_snapshot(path)[0]


def read_workspace_file(workspace: ProjectWorkspace, relative_path: str) -> dict[str, object]:
    path = _safe_workspace_file(workspace, relative_path)
    data, stat_result = _read_file_snapshot(path)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise WorkspaceError(
            "Project file must be UTF-8 encoded for Studio editing.",
            code="invalid_project_file_encoding",
        ) from exc
    return {
        "path": path.relative_to(workspace.root).as_posix(),
        "kind": _kind_for_path(path),
        "content": text,
        "sha256": _file_hash(data),
        "size": len(data),
        "mtime_ns": stat_result.st_mtime_ns,
    }


def write_workspace_file(
    workspace: ProjectWorkspace,
    relative_path: str,
    content: str,
    *,
    expected_sha256: str,
) -> dict[str, object]:
    with _WORKSPACE_SAVE_LOCK:
        return _write_workspace_file_locked(
            workspace, relative_path, content, expected_sha256=expected_sha256
        )


def _write_workspace_file_locked(
    workspace: ProjectWorkspace,
    relative_path: str,
    content: str,
    *,
    expected_sha256: str,
) -> dict[str, object]:
    path = _safe_workspace_file(workspace, relative_path)
    if not isinstance(content, str):
        raise WorkspaceError("Project file content must be text.", code="invalid_project_content")
    try:
        data = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise WorkspaceError(
            "Project file content must be valid UTF-8 text.",
            code="invalid_project_content",
        ) from exc
    if len(data) > MAX_WORKSPACE_TEXT_BYTES:
        raise WorkspaceError(
            f"Project text file exceeds the {MAX_WORKSPACE_TEXT_BYTES}-byte Studio limit.",
            code="project_file_too_large",
            status=413,
        )
    if path.name == CONFIG_FILENAME:
        try:
            tomllib.loads(content)
        except tomllib.TOMLDecodeError as exc:
            raise WorkspaceError(
                f"Project configuration is not valid TOML: {exc}",
                code="invalid_project_config",
                status=422,
            ) from exc
    current = _read_bytes(path)
    try:
        original_mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise WorkspaceError(
            "Project file metadata could not be read before saving.",
            code="project_file_unreadable",
        ) from exc
    current_hash = _file_hash(current)
    if not expected_sha256 or expected_sha256 != current_hash:
        raise WorkspaceError(
            "Project file changed on disk after it was opened. Reload before saving.",
            code="project_file_changed",
            status=409,
        )

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}.", suffix=path.suffix, dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
            written_stat = os.fstat(handle.fileno())
        sources = tuple(workspace.config.values.get("bibliography_sources") or ())
        is_bibliography = path.suffix.lower() == ".bib" or any(
            Path(source).expanduser().resolve(strict=False) == path for source in sources
        )
        if is_bibliography and path.suffix.lower() in {".bib", ".json"}:
            _, diagnostics = load_bibliography([temporary])
            if has_errors(diagnostics):
                raise WorkspaceError(
                    "Bibliography is invalid. Correct it before saving.",
                    code="invalid_project_bibliography",
                    status=422,
                    diagnostics=diagnostics,
                )
        os.chmod(temporary, original_mode)
        if _file_hash(_read_bytes(path)) != expected_sha256:
            raise WorkspaceError(
                "Project file changed on disk while saving. Reload before saving.",
                code="project_file_changed",
                status=409,
            )
        os.replace(temporary, path)
        sync_directory(path.parent)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "path": path.relative_to(workspace.root).as_posix(),
        "kind": _kind_for_path(path),
        "content": data.decode("utf-8-sig"),
        "sha256": _file_hash(data),
        "size": len(data),
        "mtime_ns": written_stat.st_mtime_ns,
    }


def _atomic_replace_text(
    path: Path,
    content: str,
    *,
    mode: int | None = None,
    before_replace: Callable[[], None] | None = None,
) -> None:
    """Replace one UTF-8 text file atomically and fsync the containing directory."""

    atomic_write_text(path, content, mode=mode, before_replace=before_replace)


def _config_sha256(workspace: ProjectWorkspace) -> str:
    if workspace.config.source_sha256 is not None:
        return workspace.config.source_sha256
    path = workspace.config.path
    if path is None or not path.is_file():
        raise WorkspaceError(
            "Studio project configuration is unavailable.",
            code="project_unavailable",
        )
    return _file_hash(_read_bytes(path))


def _validate_expected_config_sha256(
    workspace: ProjectWorkspace, expected_config_sha256: str
) -> Path:
    path = workspace.config.path
    if path is None or not path.is_file():
        raise WorkspaceError(
            "Studio project configuration is unavailable.",
            code="project_unavailable",
        )
    current = _file_hash(_read_bytes(path))
    snapshot = _config_sha256(workspace)
    if not expected_config_sha256 or expected_config_sha256 != current or snapshot != current:
        raise WorkspaceError(
            "Project configuration changed on disk. Refresh the project before changing chapters.",
            code="project_config_changed",
            status=409,
        )
    return path

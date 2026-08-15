from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .citations import MAX_BIBLIOGRAPHY_ENTRIES, load_bibliography
from .book import (
    BookManifest,
    BookRenderBundle,
    book_pdf_options,
    convert_book,
    load_book_manifest,
    render_book,
)
from .config import CONFIG_FILENAME, LoadedProjectConfig, default_config_text, load_project_config
from .diagnostics import Diagnostic, has_errors
from .project_commands import project_config_diagnostics, validate_book_project
from .markdown import embed_local_images, render_markdown
from .renderer import CancellationCallback, PdfOptions, RenderSession, build_html

MAX_WORKSPACE_FILES = 2_000
MAX_WORKSPACE_TEXT_BYTES = 4 * 1024 * 1024
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
MAX_BOOK_PROJECT_TITLE_CHARS = 200
MAX_BOOK_PROJECT_FOLDER_CHARS = 80
MAX_BOOK_CHAPTER_TITLE_CHARS = 200
MAX_BOOK_CHAPTERS = 500
_BOOK_PROJECT_DIRECTIONS = frozenset({"auto", "rtl", "ltr"})
_BOOK_PROJECT_LANGUAGES = frozenset({"fa-IR", "en-US", "fa", "en"})
_WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)

WORKSPACE_IGNORED_PARTS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".venv",
        "venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "target",
        "patches",
    }
)


class WorkspaceError(ValueError):
    """Stable project-workspace error for Studio API responses."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "project_error",
        status: int = 400,
        diagnostics: Iterable[Diagnostic] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.diagnostics = tuple(diagnostics)


@dataclass(frozen=True, slots=True)
class WorkspaceFile:
    path: str
    size: int
    kind: str
    chapter_index: int | None = None
    chapter_title: str | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "path": self.path,
            "size": self.size,
            "kind": self.kind,
        }
        if self.chapter_index is not None:
            data["chapter_index"] = self.chapter_index
        if self.chapter_title:
            data["chapter_title"] = self.chapter_title
        return data


@dataclass(slots=True)
class ProjectWorkspace:
    config: LoadedProjectConfig
    manifest: BookManifest | None
    bundle: BookRenderBundle | None
    diagnostics: tuple[Diagnostic, ...]
    files: tuple[WorkspaceFile, ...]

    @property
    def root(self) -> Path:
        return self.config.root

    @property
    def enabled(self) -> bool:
        return self.config.path is not None


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


def _file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_bytes(path: Path) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise WorkspaceError(
            "Project file metadata could not be read.",
            code="project_file_unreadable",
        ) from exc
    if size > MAX_WORKSPACE_TEXT_BYTES:
        raise WorkspaceError(
            f"Project text file exceeds the {MAX_WORKSPACE_TEXT_BYTES}-byte Studio limit.",
            code="project_file_too_large",
            status=413,
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise WorkspaceError(
            "Project file could not be read.",
            code="project_file_unreadable",
        ) from exc


def read_workspace_file(workspace: ProjectWorkspace, relative_path: str) -> dict[str, object]:
    path = _safe_workspace_file(workspace, relative_path)
    data = _read_bytes(path)
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
        "mtime_ns": path.stat().st_mtime_ns,
    }


def write_workspace_file(
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

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, original_mode)
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except (AttributeError, OSError):
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            except OSError:
                pass
            finally:
                os.close(directory_fd)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return read_workspace_file(workspace, relative_path)



def _atomic_replace_text(path: Path, content: str, *, mode: int | None = None) -> None:
    """Replace one UTF-8 text file atomically and fsync the containing directory."""

    path = path.expanduser().resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        if path.exists():
            mode = stat.S_IMODE(path.stat().st_mode)
        else:
            current_umask = os.umask(0)
            os.umask(current_umask)
            mode = 0o666 & ~current_umask
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except (AttributeError, OSError):
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            except OSError:
                pass
            finally:
                os.close(directory_fd)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _config_sha256(workspace: ProjectWorkspace) -> str:
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
    current = _config_sha256(workspace)
    if not expected_config_sha256 or expected_config_sha256 != current:
        raise WorkspaceError(
            "Project configuration changed on disk. Refresh the project before changing chapters.",
            code="project_config_changed",
            status=409,
        )
    return path


def _toml_string(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def _relative_book_output(workspace: ProjectWorkspace) -> str:
    value = workspace.config.values.get("book_output")
    if value is None:
        return "dist/book.pdf"
    output = Path(value).expanduser().resolve(strict=False)
    relative = _relative_path(workspace.root, output)
    return relative if relative is not None else str(output)


def _book_chapter_entries(workspace: ProjectWorkspace) -> list[dict[str, str | None]]:
    manifest = workspace.manifest
    if manifest is None:
        raise WorkspaceError(
            "This project is not configured as a book.",
            code="book_not_enabled",
            status=422,
        )
    entries: list[dict[str, str | None]] = []
    for chapter in manifest.chapters:
        relative = _relative_path(workspace.root, chapter.path)
        if relative is None:
            raise WorkspaceError(
                "A configured chapter is outside the project root.",
                code="book_chapter_outside_project",
                status=422,
            )
        entries.append({"path": relative, "title": chapter.title_override})
    return entries


def _book_section_text(
    chapters: Sequence[dict[str, str | None]],
    *,
    output: str,
    chapter_page_break: bool,
) -> str:
    lines = ["[book]", "chapters = ["]
    for chapter in chapters:
        path_value = _toml_string(str(chapter["path"]))
        title = chapter.get("title")
        if title:
            lines.append(
                f"  {{ path = {path_value}, title = {_toml_string(str(title))} }},"
            )
        else:
            lines.append(f"  {path_value},")
    lines.extend(
        [
            "]",
            f"output = {_toml_string(output)}",
            f"chapter_page_break = {'true' if chapter_page_break else 'false'}",
        ]
    )
    return "\n".join(lines) + "\n"


_TOML_KEY_PATTERN = r'(?:[A-Za-z0-9_-]+|"(?:\\.|[^"\\\r\n])*"|\'[^\'\r\n]*\')'
_TOML_TABLE_HEADER = re.compile(
    rf"^\s*\[(?P<array>\[)?\s*{_TOML_KEY_PATTERN}"
    rf"(?:\s*\.\s*{_TOML_KEY_PATTERN})*\s*\](?(array)\])\s*(?:#.*)?$"
)


def _replace_toml_section(text: str, section: str, replacement: str) -> str:
    lines = text.splitlines(keepends=True)
    escaped_section = re.escape(section)
    header = re.compile(
        rf"^\s*\[\s*(?:{escaped_section}|\"{escaped_section}\"|'{escaped_section}')"
        r"\s*\]\s*(?:#.*)?$"
    )
    start: int | None = None
    end: int | None = None
    for index, line in enumerate(lines):
        if header.match(line.rstrip("\r\n")):
            start = index
            break
    if start is not None:
        end = len(lines)
        for index in range(start + 1, len(lines)):
            if _TOML_TABLE_HEADER.match(lines[index].rstrip("\r\n")):
                end = index
                break
        prefix = "".join(lines[:start]).rstrip() + "\n\n"
        suffix = "".join(lines[end:]).lstrip()
        result = prefix + replacement.rstrip() + "\n"
        if suffix:
            result += "\n" + suffix
        return result.rstrip() + "\n"
    return text.rstrip() + "\n\n" + replacement.rstrip() + "\n"


def _write_book_chapters(
    workspace: ProjectWorkspace,
    chapters: Sequence[dict[str, str | None]],
    *,
    expected_config_sha256: str,
) -> ProjectWorkspace:
    if not chapters:
        raise WorkspaceError(
            "A book project must keep at least one chapter.",
            code="book_requires_chapter",
            status=422,
        )
    if len(chapters) > MAX_BOOK_CHAPTERS:
        raise WorkspaceError(
            f"Book projects support at most {MAX_BOOK_CHAPTERS} chapters.",
            code="book_too_many_chapters",
            status=422,
        )
    config_path = _validate_expected_config_sha256(workspace, expected_config_sha256)
    original = config_path.read_text(encoding="utf-8-sig")
    replacement = _book_section_text(
        chapters,
        output=_relative_book_output(workspace),
        chapter_page_break=bool(
            workspace.config.values.get("book_chapter_page_break", True)
        ),
    )
    updated = _replace_toml_section(original, "book", replacement)
    try:
        _atomic_replace_text(config_path, updated)
    except OSError as exc:
        raise WorkspaceError(
            f"Project configuration could not be updated: {exc}",
            code="project_config_write_failed",
        ) from exc
    return load_workspace(config_path)


def _validate_book_title(value: str, *, field: str = "title") -> str:
    title = str(value or "").strip()
    if not title:
        raise WorkspaceError(
            f"Book {field} is required.",
            code=f"invalid_book_{field}",
        )
    limit = (
        MAX_BOOK_PROJECT_TITLE_CHARS
        if field == "title"
        else MAX_BOOK_CHAPTER_TITLE_CHARS
    )
    if len(title) > limit or any(character in title for character in "\x00\r\n"):
        raise WorkspaceError(
            f"Book {field} is invalid or exceeds {limit} characters.",
            code=f"invalid_book_{field}",
        )
    return title


def _safe_project_folder_name(value: str, *, fallback: str = "mardas-book") -> str:
    raw = str(value or "").strip()
    if not raw:
        raw = fallback
    if (
        len(raw) > MAX_BOOK_PROJECT_FOLDER_CHARS
        or raw in {".", ".."}
        or raw.startswith(".")
        or raw.endswith((" ", "."))
        or any(character in raw for character in '<>:"/\\|?*\x00')
        or Path(raw).name != raw
        or raw.upper().split(".", 1)[0] in _WINDOWS_RESERVED_NAMES
    ):
        raise WorkspaceError(
            "Project folder name contains unsupported characters.",
            code="invalid_book_folder",
        )
    return raw


def _slug(value: str, *, fallback: str) -> str:
    pieces: list[str] = []
    previous_dash = False
    for character in str(value).strip().casefold():
        if character.isalnum():
            pieces.append(character)
            previous_dash = False
        elif not previous_dash:
            pieces.append("-")
            previous_dash = True
    slug = "".join(pieces).strip("-")
    return (slug or fallback)[:56].rstrip("-") or fallback


def _next_chapter_path(
    workspace: ProjectWorkspace, title: str, *, preferred_index: int | None = None
) -> tuple[Path, str]:
    chapter_dir = workspace.root / "chapters"
    if chapter_dir.exists() and (not chapter_dir.is_dir() or chapter_dir.is_symlink()):
        raise WorkspaceError(
            "The chapters path must be a regular project directory.",
            code="invalid_chapters_directory",
        )
    chapter_dir.mkdir(parents=True, exist_ok=True)
    used = {
        item["path"]
        for item in _book_chapter_entries(workspace)
        if isinstance(item.get("path"), str)
    }
    index = preferred_index or (len(used) + 1)
    stem = _slug(title, fallback="chapter")
    while index <= MAX_BOOK_CHAPTERS + len(used) + 1:
        relative = f"chapters/{index:02d}-{stem}.md"
        candidate = workspace.root / relative
        if relative not in used and not candidate.exists() and not candidate.is_symlink():
            return candidate, relative
        index += 1
    raise WorkspaceError(
        "Could not allocate a unique chapter filename.",
        code="book_chapter_name_exhausted",
    )


def create_book_workspace(
    parent_path: Path,
    *,
    folder_name: str,
    title: str,
    language: str = "fa-IR",
    direction: str = "auto",
) -> ProjectWorkspace:
    selected_parent = Path(parent_path).expanduser()
    if selected_parent.is_symlink():
        raise WorkspaceError(
            "The selected project location must not be a symbolic link.",
            code="blocked_project_symlink",
        )
    try:
        parent = selected_parent.resolve(strict=True)
    except OSError as exc:
        raise WorkspaceError(
            "The selected project location does not exist.",
            code="project_parent_missing",
        ) from exc
    if not parent.is_dir():
        raise WorkspaceError(
            "The selected project location is not a directory.",
            code="project_parent_invalid",
        )
    project_title = _validate_book_title(title)
    safe_folder = _safe_project_folder_name(
        folder_name,
        fallback=_slug(project_title, fallback="mardas-book"),
    )
    if language not in _BOOK_PROJECT_LANGUAGES:
        raise WorkspaceError(
            "Book language is not supported.",
            code="invalid_book_language",
        )
    if direction not in _BOOK_PROJECT_DIRECTIONS:
        raise WorkspaceError(
            "Book direction must be auto, rtl, or ltr.",
            code="invalid_book_direction",
        )
    project_root = parent / safe_folder
    if project_root.exists() or project_root.is_symlink():
        raise WorkspaceError(
            "A file or directory with this project name already exists.",
            code="book_project_exists",
            status=409,
        )

    project_root.mkdir(mode=0o755)
    try:
        (project_root / "chapters").mkdir(mode=0o755)
        (project_root / "assets").mkdir(mode=0o755)
        (project_root / "bibliography").mkdir(mode=0o755)
        (project_root / "dist").mkdir(mode=0o755)
        introduction = "مقدمه" if language.startswith("fa") else "Introduction"
        chapter_relative = "chapters/01-introduction.md"
        chapter_text = f"# {introduction}\n\n"
        _atomic_replace_text(project_root / chapter_relative, chapter_text)
        config_text = default_config_text()
        config_text = config_text.replace(
            '# title = "My document"', f"title = {_toml_string(project_title)}", 1
        )
        config_text = config_text.replace(
            '# language = "fa-IR"', f"language = {_toml_string(language)}", 1
        )
        config_text = re.sub(
            r"(?m)^direction\s*=\s*\"auto\"\s*$",
            f"direction = {_toml_string(direction)}",
            config_text,
            count=1,
        )
        config_text = re.sub(
            r"(?ms)^# Enable multi-file Book Mode.*?^# chapter_page_break = true\s*",
            "",
            config_text,
            count=1,
        )
        config_text = _replace_toml_section(
            config_text,
            "book",
            _book_section_text(
                [{"path": chapter_relative, "title": introduction}],
                output="dist/book.pdf",
                chapter_page_break=True,
            ),
        )
        _atomic_replace_text(project_root / CONFIG_FILENAME, config_text)
        workspace = load_workspace(project_root)
    except Exception:
        shutil.rmtree(project_root, ignore_errors=True)
        raise
    return workspace


def add_workspace_book_chapter(
    workspace: ProjectWorkspace,
    *,
    title: str,
    expected_config_sha256: str,
    position: int | None = None,
    content: str | None = None,
) -> tuple[ProjectWorkspace, dict[str, object]]:
    chapter_title = _validate_book_title(title, field="chapter_title")
    chapters = _book_chapter_entries(workspace)
    insertion = len(chapters) if position is None else int(position)
    if insertion < 0 or insertion > len(chapters):
        raise WorkspaceError(
            "Chapter position is outside the current book order.",
            code="invalid_book_chapter_position",
        )
    path, relative = _next_chapter_path(workspace, chapter_title)
    body = content if content is not None else f"# {chapter_title}\n\n"
    if not isinstance(body, str) or len(body.encode("utf-8")) > MAX_WORKSPACE_TEXT_BYTES:
        raise WorkspaceError(
            "Chapter content is invalid or too large.",
            code="invalid_book_chapter_content",
            status=413,
        )
    _atomic_replace_text(path, body)
    updated_entries = list(chapters)
    updated_entries.insert(insertion, {"path": relative, "title": chapter_title})
    try:
        refreshed = _write_book_chapters(
            workspace,
            updated_entries,
            expected_config_sha256=expected_config_sha256,
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return refreshed, {
        "path": relative,
        "absolute_path": str(path),
        "title": chapter_title,
        "index": insertion + 1,
    }


def duplicate_workspace_book_chapter(
    workspace: ProjectWorkspace,
    *,
    relative_path: str,
    title: str | None,
    expected_config_sha256: str,
) -> tuple[ProjectWorkspace, dict[str, object]]:
    chapters = _book_chapter_entries(workspace)
    source_index = next(
        (index for index, item in enumerate(chapters) if item["path"] == relative_path),
        None,
    )
    if source_index is None:
        raise WorkspaceError(
            "The selected file is not a configured book chapter.",
            code="book_chapter_not_found",
            status=404,
        )
    source = _safe_workspace_file(workspace, relative_path)
    source_content = source.read_text(encoding="utf-8-sig")
    source_title = chapters[source_index].get("title") or source.stem
    duplicate_title = _validate_book_title(
        title or f"{source_title} Copy", field="chapter_title"
    )
    return add_workspace_book_chapter(
        workspace,
        title=duplicate_title,
        expected_config_sha256=expected_config_sha256,
        position=source_index + 1,
        content=source_content,
    )


def reorder_workspace_book_chapters(
    workspace: ProjectWorkspace,
    *,
    ordered_paths: Sequence[str],
    expected_config_sha256: str,
) -> ProjectWorkspace:
    chapters = _book_chapter_entries(workspace)
    current = [str(item["path"]) for item in chapters]
    requested = [str(item) for item in ordered_paths]
    if (
        len(requested) != len(current)
        or len(set(requested)) != len(requested)
        or set(requested) != set(current)
    ):
        raise WorkspaceError(
            "Chapter reorder must contain every configured chapter exactly once.",
            code="invalid_book_chapter_order",
        )
    by_path = {str(item["path"]): item for item in chapters}
    return _write_book_chapters(
        workspace,
        [by_path[path] for path in requested],
        expected_config_sha256=expected_config_sha256,
    )


def remove_workspace_book_chapter(
    workspace: ProjectWorkspace,
    *,
    relative_path: str,
    expected_config_sha256: str,
) -> ProjectWorkspace:
    chapters = _book_chapter_entries(workspace)
    if len(chapters) <= 1:
        raise WorkspaceError(
            "A book project must keep at least one chapter.",
            code="book_requires_chapter",
            status=422,
        )
    remaining = [item for item in chapters if item["path"] != relative_path]
    if len(remaining) == len(chapters):
        raise WorkspaceError(
            "The selected file is not a configured book chapter.",
            code="book_chapter_not_found",
            status=404,
        )
    # The source file intentionally remains in the project. This is a safe
    # "remove from book" action rather than destructive deletion.
    return _write_book_chapters(
        workspace,
        remaining,
        expected_config_sha256=expected_config_sha256,
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


def _chapter_map(manifest: BookManifest | None) -> dict[Path, tuple[int, str | None]]:
    if manifest is None:
        return {}
    return {
        chapter.path.resolve(): (chapter.index, chapter.title_override)
        for chapter in manifest.chapters
    }


def _iter_workspace_files(root: Path) -> Iterable[Path]:
    """Walk project files while pruning generated, hidden, and symlink directories."""

    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        safe_directories: list[str] = []
        for name in directory_names:
            candidate = current_path / name
            if (
                name.startswith(".")
                or name in WORKSPACE_IGNORED_PARTS
                or candidate.is_symlink()
            ):
                continue
            safe_directories.append(name)
        directory_names[:] = safe_directories

        for name in file_names:
            if name.startswith("."):
                continue
            path = current_path / name
            if path.is_symlink() or not path.is_file():
                continue
            if path.name != CONFIG_FILENAME and path.suffix.lower() not in WORKSPACE_TEXT_SUFFIXES:
                continue
            yield path


def _workspace_files(
    root: Path, manifest: BookManifest | None
) -> tuple[tuple[WorkspaceFile, ...], tuple[Diagnostic, ...]]:
    chapter_map = _chapter_map(manifest)
    files: list[WorkspaceFile] = []
    diagnostics: list[Diagnostic] = []
    for index, path in enumerate(
        sorted(
            _iter_workspace_files(root),
            key=lambda item: item.relative_to(root).as_posix().casefold(),
        )
    ):
        if index >= MAX_WORKSPACE_FILES:
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
        chapter = chapter_map.get(path.resolve())
        files.append(
            WorkspaceFile(
                path=path.relative_to(root).as_posix(),
                size=path.stat().st_size,
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


def load_workspace(
    target: Path,
    *,
    progress: Callable[[str, float], None] | None = None,
    cancelled: CancellationCallback | None = None,
) -> ProjectWorkspace:
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
    if config.values.get("book_chapters") and not has_errors(diagnostics):
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
        if manifest is not None:
            bundle, render_diagnostics = render_book(manifest)
            diagnostics.extend(render_diagnostics)

    files, file_diagnostics = _workspace_files(config.root, manifest)
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


def _validated_book_workspace(
    workspace: ProjectWorkspace,
    *,
    progress: Callable[[str, float], None] | None = None,
    cancelled: CancellationCallback | None = None,
) -> tuple[ProjectWorkspace, BookManifest, BookRenderBundle]:
    refreshed = refresh_workspace(workspace, progress=progress, cancelled=cancelled)
    if refreshed.manifest is None or refreshed.bundle is None or has_errors(refreshed.diagnostics):
        raise WorkspaceError(
            "Book project has validation errors. Resolve Problems before preview or export.",
            code="project_validation_failed",
            status=422,
            diagnostics=refreshed.diagnostics,
        )
    return refreshed, refreshed.manifest, refreshed.bundle


def render_workspace_book_html(
    workspace: ProjectWorkspace,
    *,
    progress: Callable[[str, float], None] | None = None,
    cancelled: CancellationCallback | None = None,
) -> tuple[str, ProjectWorkspace]:
    refreshed, manifest, bundle = _validated_book_workspace(
        workspace,
        progress=(
            (lambda stage, value: progress(stage, value * 0.8)) if progress else None
        ),
        cancelled=cancelled,
    )
    if cancelled and cancelled():
        raise WorkspaceError(
            "Book preview was cancelled.",
            code="book_preview_cancelled",
            status=499,
        )
    if progress:
        progress("Building full-book preview", 0.85)
    options = book_pdf_options(manifest)
    html = build_html(
        bundle.result,
        options,
        include_cover=True,
        include_content=True,
        include_watermark=True,
    )
    if cancelled and cancelled():
        raise WorkspaceError(
            "Book preview was cancelled.",
            code="book_preview_cancelled",
            status=499,
        )
    if progress:
        progress("Full-book preview ready", 1.0)
    return html, refreshed


def export_workspace_book_pdf(
    workspace: ProjectWorkspace,
    output_path: Path,
    *,
    session: RenderSession | None = None,
    progress: Callable[[str, float], None] | None = None,
    cancelled: CancellationCallback | None = None,
) -> tuple[Path, str, ProjectWorkspace]:
    refreshed, manifest, bundle = _validated_book_workspace(
        workspace,
        progress=(
            (lambda stage, value: progress(stage, value * 0.35)) if progress else None
        ),
        cancelled=cancelled,
    )
    built, _bundle, diagnostics = convert_book(
        manifest,
        output_path=output_path,
        bundle=bundle,
        session=session,
        progress=(
            (lambda stage, value: progress(stage, 0.35 + value * 0.65))
            if progress
            else None
        ),
        cancelled=cancelled,
    )
    if built is None or has_errors(diagnostics):
        raise WorkspaceError(
            "Book export failed validation.",
            code="project_export_failed",
            status=422,
            diagnostics=diagnostics,
        )
    return built, manifest.output_path.name, refreshed


def render_workspace_book_pdf(
    workspace: ProjectWorkspace,
    *,
    session: RenderSession | None = None,
    progress: Callable[[str, float], None] | None = None,
    cancelled: CancellationCallback | None = None,
) -> tuple[bytes, str, ProjectWorkspace]:
    with tempfile.TemporaryDirectory(prefix="mardas-studio-book-") as directory:
        output = Path(directory) / "book.pdf"
        built, filename, refreshed = export_workspace_book_pdf(
            workspace,
            output,
            session=session,
            progress=progress,
            cancelled=cancelled,
        )
        data = built.read_bytes()
    return data, filename, refreshed


def _workspace_pdf_options(workspace: ProjectWorkspace, source_path: Path) -> PdfOptions:
    values = workspace.config.values
    if workspace.manifest is not None:
        options = book_pdf_options(workspace.manifest)
        options.input_path = source_path
        options.output_path = workspace.root / ".mardas-studio-preview.pdf"
        return options
    return PdfOptions(
        input_path=source_path,
        output_path=workspace.root / ".mardas-studio-preview.pdf",
        title=values.get("title"),
        author=values.get("author"),
        description=values.get("description"),
        toc=bool(values.get("toc", False)),
        toc_depth=int(values.get("toc_depth", 6)),
        toc_page_break=bool(values.get("toc_page_break", False)),
        h1_page_break=bool(values.get("h1_page_break", False)),
        page_size=str(values.get("page_size", "A4")),
        document_direction=values.get("document_direction"),
        margin_top=str(values.get("margin_top", "18mm")),
        margin_bottom=str(values.get("margin_bottom", "20mm")),
        margin_x=str(values.get("margin_x", "16mm")),
        font_dir=values.get("font_dir"),
        chromium_path=values.get("chromium_path"),
        chromium_sandbox=str(values.get("chromium_sandbox", "auto")),
        no_header_footer=bool(values.get("no_header_footer", False)),
        no_mathjax=bool(values.get("no_mathjax", False)),
        timeout_ms=int(values.get("timeout_ms", 120_000)),
        style=values.get("style"),
        palette=values.get("palette"),
        mode=values.get("mode"),
        cover=not bool(values.get("no_cover", False)),
        cover_logo=values.get("cover_logo"),
        cover_logo_enabled=not bool(values.get("no_cover_logo", False)),
        branding=values.get("branding"),
        brand_name=values.get("brand_name"),
        brand_logo=values.get("brand_logo"),
        brand_footer=values.get("brand_footer"),
        watermark_text=values.get("watermark"),
        watermark_image=values.get("watermark_image"),
        watermark_opacity=float(values.get("watermark_opacity", 0.065)),
        watermark_width=str(values.get("watermark_width", "105mm")),
        unsafe_html=bool(values.get("unsafe_html", False)),
        allow_remote_assets=bool(values.get("allow_remote_assets", False)),
        quality_profile=str(values.get("quality_profile", "standard")),
        math_error_policy=values.get("math_error_policy"),
        font_error_policy=values.get("font_error_policy"),
        navigation_error_policy=values.get("navigation_error_policy"),
        required_fonts=tuple(values.get("required_fonts") or ()),
        quality_report=values.get("quality_report"),
    )


_MISSING_REFERENCE_PREFIX = "Reference target is not defined: "


def _cross_chapter_preview_reference_labels(
    workspace: ProjectWorkspace, source_path: Path
) -> frozenset[str]:
    if workspace.manifest is None or workspace.bundle is None:
        return frozenset()

    source_resolved = source_path.resolve(strict=False)
    current_chapter_index = next(
        (
            chapter.index
            for chapter in workspace.manifest.chapters
            if chapter.path.resolve(strict=False) == source_resolved
        ),
        None,
    )
    if current_chapter_index is None:
        return frozenset()

    labels: set[str] = set()
    for item in workspace.bundle.result.reference_objects:
        label = item.get("label")
        chapter_index = item.get("chapter_index")
        if (
            isinstance(label, str)
            and label
            and chapter_index != current_chapter_index
        ):
            labels.add(label)
    return frozenset(labels)


def _is_valid_cross_chapter_preview_reference(
    diagnostic: Diagnostic, known_labels: frozenset[str]
) -> bool:
    if (
        diagnostic.code != "MARDAS-E602"
        or not diagnostic.message.startswith(_MISSING_REFERENCE_PREFIX)
    ):
        return False

    label = diagnostic.message.removeprefix(_MISSING_REFERENCE_PREFIX).strip()
    return label in known_labels


def render_workspace_file_html(
    workspace: ProjectWorkspace, relative_path: str, content: str
) -> tuple[str, ProjectWorkspace]:
    refreshed = refresh_workspace(workspace)
    source_path = _safe_workspace_file(refreshed, relative_path)
    if _kind_for_path(source_path) != "markdown":
        raise WorkspaceError(
            "Only Markdown project files have renderer-backed previews.",
            code="project_preview_unsupported",
            status=422,
        )
    values = refreshed.config.values
    bibliography_library = None
    bibliography_sources = tuple(values.get("bibliography_sources") or ())
    diagnostics: list[Diagnostic] = []
    if bool(values.get("citations_enabled", False)) and bibliography_sources:
        bibliography_library, bibliography_diagnostics = load_bibliography(bibliography_sources)
        diagnostics.extend(bibliography_diagnostics)
    result = render_markdown(
        content,
        toc=bool(values.get("toc", False)),
        toc_depth=int(values.get("toc_depth", 6)),
        appearance_style=values.get("style"),
        appearance_mode=values.get("mode"),
        unsafe_html=bool(values.get("unsafe_html", False)),
        allow_remote_images=bool(values.get("allow_remote_assets", False)),
        references_enabled=bool(values.get("references_enabled", False)),
        numbering_scope=str(values.get("numbering_scope", "global")),
        list_of_figures=bool(values.get("list_of_figures", False)),
        list_of_tables=bool(values.get("list_of_tables", False)),
        list_of_equations=bool(values.get("list_of_equations", False)),
        list_of_listings=bool(values.get("list_of_listings", False)),
        citations_enabled=bool(values.get("citations_enabled", False)),
        citation_style=str(values.get("citation_style", "author-date")),
        bibliography_title=values.get("bibliography_title"),
        bibliography_include_uncited=bool(values.get("bibliography_include_uncited", False)),
        bibliography_library=bibliography_library,
        source_path=source_path,
    )
    result.body_html = embed_local_images(
        result.body_html,
        source_path.parent,
        document_root=refreshed.root,
        allow_remote_images=bool(values.get("allow_remote_assets", False)),
    )
    known_cross_chapter_references = _cross_chapter_preview_reference_labels(
        refreshed, source_path
    )
    diagnostics.extend(
        item
        for item in result.diagnostics
        if not _is_valid_cross_chapter_preview_reference(
            item, known_cross_chapter_references
        )
    )
    if has_errors(diagnostics):
        raise WorkspaceError(
            "Project file preview has validation errors.",
            code="project_validation_failed",
            status=422,
            diagnostics=diagnostics,
        )
    return (
        build_html(
            result,
            _workspace_pdf_options(refreshed, source_path),
            include_cover=True,
            include_content=True,
            include_watermark=True,
        ),
        refreshed,
    )


MAX_WORKSPACE_SEARCH_RESULTS = 500
MAX_WORKSPACE_SEARCH_QUERY_CHARS = 512

# One Persian letter, typed two ways.
#
# A Persian keyboard produces ی U+06CC and ک U+06A9. An Arabic layout, older
# Windows keyboards, and most text pasted from the web produce ي U+064A and
# ك U+0643 instead. The pairs are indistinguishable on screen, so a document
# that mixes them looks uniform — and searching it for a word spelled the other
# way returned nothing at all, which reads as "the text is not there" rather
# than "you typed a different code point".
#
# Every mapping is one character to one character, so folding a line leaves
# every offset in it exactly where it was and the reported column stays true.
# Letters that merely look similar are left alone: آ and ا are different
# letters in Persian, and Persian and Latin digits mean different things.
_PERSIAN_LETTER_FOLD = str.maketrans(
    {
        "ي": "ی",  # ARABIC YEH        -> FARSI YEH
        "ى": "ی",  # ALEF MAKSURA      -> FARSI YEH
        "ك": "ک",  # ARABIC KAF        -> KEHEH
    }
)


def fold_persian_letters(value: str) -> str:
    """Spell the Persian/Arabic letter variants one way, preserving length."""

    return value.translate(_PERSIAN_LETTER_FOLD)
MAX_WORKSPACE_SEARCH_LINE_CHARS = 2_000
_UNSAFE_REGEX_TOKENS = (
    "(?=",
    "(?!",
    "(?<=",
    "(?<!",
    "(?P",
    "\\1",
    "\\2",
    "\\3",
    "\\4",
    "\\5",
    "\\6",
    "\\7",
    "\\8",
    "\\9",
    "\\g<",
)
_LARGE_REGEX_REPEAT = re.compile(r"\{\s*(\d+)(?:\s*,\s*(\d*)?)?\s*\}")
_MAX_REGEX_REPEAT = 1_000


def _has_quantified_regex_group(query: str) -> bool:
    escaped = False
    in_character_class = False
    for index, character in enumerate(query):
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if in_character_class:
            if character == "]":
                in_character_class = False
            continue
        if character == "[":
            in_character_class = True
            continue
        if character != ")" or index + 1 >= len(query):
            continue
        following = query[index + 1]
        if following in {"*", "+", "?"}:
            return True
        if following == "{" and _LARGE_REGEX_REPEAT.match(query, index + 1):
            return True
    return False


def _variable_regex_quantifier_count(query: str) -> int:
    """Count variable-width quantifiers while ignoring literals and character classes."""

    count = 0
    escaped = False
    in_character_class = False
    index = 0
    while index < len(query):
        character = query[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\":
            escaped = True
            index += 1
            continue
        if in_character_class:
            if character == "]":
                in_character_class = False
            index += 1
            continue
        if character == "[":
            in_character_class = True
            index += 1
            continue
        if character in {"*", "+", "?"}:
            if character == "?" and index > 0 and query[index - 1] == "(":
                index += 1
                continue
            count += 1
            index += 1
            if index < len(query) and query[index] in {"?", "+"}:
                index += 1
            continue
        if character == "{":
            repeat = _LARGE_REGEX_REPEAT.match(query, index)
            if repeat is not None:
                lower = int(repeat.group(1))
                upper_text = repeat.group(2)
                if "," in repeat.group(0) and (
                    not upper_text or int(upper_text) != lower
                ):
                    count += 1
                index = repeat.end()
                if index < len(query) and query[index] in {"?", "+"}:
                    index += 1
                continue
        index += 1
    return count


def _compile_workspace_regex(query: str, flags: int) -> re.Pattern[str]:
    """Compile a deliberately limited regex suitable for interactive project search."""

    unsafe_repeat = any(
        int(match.group(1)) > _MAX_REGEX_REPEAT
        or (
            match.group(2)
            and int(match.group(2)) > _MAX_REGEX_REPEAT
        )
        for match in _LARGE_REGEX_REPEAT.finditer(query)
    )
    if (
        any(token in query for token in _UNSAFE_REGEX_TOKENS)
        or _has_quantified_regex_group(query)
        or unsafe_repeat
        or _variable_regex_quantifier_count(query) > 1
    ):
        raise WorkspaceError(
            "Project regex uses an advanced or potentially expensive construct.",
            code="unsafe_project_search_regex",
        )
    try:
        return re.compile(query, flags)
    except re.error as exc:
        raise WorkspaceError(
            f"Invalid regular expression: {exc}",
            code="invalid_project_search_regex",
        ) from exc


def search_workspace(
    workspace: ProjectWorkspace,
    query: str,
    *,
    regex: bool = False,
    case_sensitive: bool = False,
    max_results: int = 200,
    cancelled: CancellationCallback | None = None,
) -> dict[str, object]:
    """Search bounded UTF-8 project files without escaping the workspace root."""

    if not isinstance(query, str) or not query:
        raise WorkspaceError(
            "Project search query is required.",
            code="invalid_project_search",
        )
    if len(query) > MAX_WORKSPACE_SEARCH_QUERY_CHARS:
        raise WorkspaceError(
            f"Project search query exceeds {MAX_WORKSPACE_SEARCH_QUERY_CHARS} characters.",
            code="project_search_query_too_large",
            status=413,
        )
    limit = max(1, min(int(max_results or 200), MAX_WORKSPACE_SEARCH_RESULTS))
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern: re.Pattern[str] | None = None
    # Both kinds of search run as a compiled pattern over the folded line, so a
    # reported column is an offset into the line as it is stored. Case-folding
    # the line instead would not be: `casefold` may return a longer string than
    # it was given — ß becomes ss — and every column after such a character
    # would be reported past where it is.
    if regex:
        # Folding the pattern is safe: none of the letters involved is a regular
        # expression metacharacter, and it keeps a regex answering the same way
        # a literal search does.
        pattern = _compile_workspace_regex(fold_persian_letters(query), flags)
    else:
        pattern = re.compile(re.escape(fold_persian_letters(query)), flags)
    matches: list[dict[str, object]] = []
    searched_files = 0
    truncated = False

    for item in workspace.files:
        if cancelled and cancelled():
            raise WorkspaceError(
                "Project search was cancelled.",
                code="project_search_cancelled",
                status=499,
            )
        if item.kind not in {"markdown", "bibliography", "json", "toml", "text", "config"}:
            continue
        try:
            path = _safe_workspace_file(workspace, item.path)
            data = _read_bytes(path)
            content = data.decode("utf-8-sig")
        except (WorkspaceError, UnicodeDecodeError):
            continue
        searched_files += 1
        for line_number, line in enumerate(content.splitlines(), start=1):
            if cancelled and line_number % 128 == 0 and cancelled():
                raise WorkspaceError(
                    "Project search was cancelled.",
                    code="project_search_cancelled",
                    status=499,
                )
            clipped_line = line[:MAX_WORKSPACE_SEARCH_LINE_CHARS]
            columns = [
                match.start() + 1
                for match in pattern.finditer(fold_persian_letters(clipped_line))
            ]
            for column in columns:
                matches.append(
                    {
                        "path": item.path,
                        "line": line_number,
                        "column": column,
                        "preview": clipped_line.strip()[:300],
                    }
                )
                if len(matches) >= limit:
                    truncated = True
                    break
            if truncated:
                break
        if truncated:
            break

    return {
        "query": query,
        "regex": bool(regex),
        "case_sensitive": bool(case_sensitive),
        "searched_files": searched_files,
        "matches": matches,
        "truncated": truncated,
        "max_results": limit,
    }


def workspace_bibliography(
    workspace: ProjectWorkspace,
    *,
    query: str = "",
    cited_keys: Iterable[str] = (),
    max_results: int = 500,
) -> dict[str, object]:
    """Return a searchable, read-only bibliography index for the desktop UI."""

    raw_sources = tuple(workspace.config.values.get("bibliography_sources") or ())
    sources: list[Path] = []
    diagnostics: list[Diagnostic] = []
    root = workspace.root.resolve()
    for raw_source in raw_sources:
        source = Path(raw_source).expanduser().resolve(strict=False)
        if source.is_symlink() or not _contains_path(root, source):
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E701",
                    "error",
                    "Project bibliography source must be a regular file inside the project root.",
                    path=source,
                )
            )
            continue
        sources.append(source)

    library, library_diagnostics = load_bibliography(sources)
    diagnostics.extend(library_diagnostics)
    normalized_query = str(query or "").strip().casefold()
    cited = {str(key).strip() for key in cited_keys if str(key).strip()}
    limit = max(1, min(int(max_results or 500), MAX_BIBLIOGRAPHY_ENTRIES))
    entries: list[dict[str, object]] = []
    matched_total = 0
    for key in sorted(library.entries, key=str.casefold):
        entry = library.entries[key]
        searchable = " ".join(
            [
                entry.key,
                entry.title,
                entry.year,
                entry.container_title,
                entry.publisher,
                " ".join(author.display for author in entry.authors),
            ]
        ).casefold()
        if normalized_query and normalized_query not in searchable:
            continue
        matched_total += 1
        if len(entries) >= limit:
            continue
        payload = entry.to_dict()
        payload["cited"] = entry.key in cited
        if entry.source_path is not None:
            payload["source_path"] = (
                entry.source_path.resolve(strict=False).relative_to(root).as_posix()
                if _contains_path(root, entry.source_path.resolve(strict=False))
                else entry.source_path.name
            )
        entries.append(payload)

    return {
        "sources": [
            source.relative_to(root).as_posix()
            for source in sources
            if _contains_path(root, source)
        ],
        "entries": entries,
        "entry_count": len(library.entries),
        "matched_count": matched_total,
        "query": str(query or ""),
        "diagnostics": workspace_diagnostics_payload(workspace, diagnostics),
        "ok": not has_errors(diagnostics),
        "truncated": matched_total > len(entries),
    }

"""Book-project creation and transactional chapter/configuration mutations."""
from __future__ import annotations
import json
import re
import shutil
from pathlib import Path
from typing import Sequence
from ..config import CONFIG_FILENAME, default_config_text, tomllib
from ..file_io import serialized_file_write
from .models import ProjectWorkspace, WorkspaceError
from .discovery import _relative_path, _safe_workspace_file
from .files import (
    MAX_WORKSPACE_TEXT_BYTES,
    _atomic_replace_text,
    _read_bytes,
    _validate_expected_config_sha256,
    read_workspace_file,
)
from .loading import (
    load_workspace,
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
_TOML_KEY_PATTERN = r'(?:[A-Za-z0-9_-]+|"(?:\\.|[^"\\\r\n])*"|\'[^\'\r\n]*\')'
_TOML_TABLE_HEADER = re.compile(
    rf"^\s*\[(?P<array>\[)?\s*{_TOML_KEY_PATTERN}"
    rf"(?:\s*\.\s*{_TOML_KEY_PATTERN})*\s*\](?(array)\])\s*(?:#.*)?$"
)



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


def _toml_header_lines(lines: Sequence[str]) -> set[int]:
    """Identify table headers outside comments and multiline TOML strings."""
    headers: set[int] = set()
    multiline: str | None = None
    for line_number, line in enumerate(lines):
        if multiline is None and _TOML_TABLE_HEADER.match(line.rstrip("\r\n")):
            headers.add(line_number)
        index = 0
        while index < len(line):
            if multiline is not None:
                if multiline == '"""' and line[index] == "\\":
                    index += 2
                elif line.startswith(multiline, index):
                    index += 3
                    multiline = None
                else:
                    index += 1
            elif line[index] == "#":
                break
            elif line[index] in {"'", '"'}:
                quote = line[index]
                if line.startswith(quote * 3, index):
                    multiline = quote * 3
                    index += 3
                else:
                    index += 1
                    while index < len(line):
                        if quote == '"' and line[index] == "\\":
                            index += 2
                        elif line[index] == quote:
                            index += 1
                            break
                        else:
                            index += 1
            else:
                index += 1
    return headers


def _replace_toml_section(text: str, section: str, replacement: str) -> str:
    lines = text.splitlines(keepends=True)
    header_lines = _toml_header_lines(lines)
    escaped_section = re.escape(section)
    header = re.compile(
        rf"^\s*\[\s*(?:{escaped_section}|\"{escaped_section}\"|'{escaped_section}')"
        r"\s*\]\s*(?:#.*)?$"
    )
    start: int | None = None
    end: int | None = None
    for index, line in enumerate(lines):
        if index in header_lines and header.match(line.rstrip("\r\n")):
            start = index
            break
    if start is not None:
        end = len(lines)
        for index in range(start + 1, len(lines)):
            if index in header_lines:
                end = index
                break
        prefix = "".join(lines[:start]).rstrip() + "\n\n"
        suffix = "".join(lines[end:]).lstrip()
        result = prefix + replacement.rstrip() + "\n"
        if suffix:
            result += "\n" + suffix
        return result.rstrip() + "\n"
    return text.rstrip() + "\n\n" + replacement.rstrip() + "\n"


def _commit_book_chapters(
    workspace: ProjectWorkspace,
    chapters: Sequence[dict[str, str | None]],
    *,
    expected_config_sha256: str,
) -> Path:
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
    original = _read_bytes(config_path).decode("utf-8-sig")
    replacement = _book_section_text(
        chapters,
        output=_relative_book_output(workspace),
        chapter_page_break=bool(
            workspace.config.values.get("book_chapter_page_break", True)
        ),
    )
    updated = _replace_toml_section(original, "book", replacement)
    try:
        tomllib.loads(updated)
    except tomllib.TOMLDecodeError as exc:
        raise WorkspaceError(
            "Chapter editing requires a [book] table in the project configuration. "
            "Move inline or dotted book settings into that table before changing chapters.",
            code="project_config_edit_unsupported",
        ) from exc

    def check_revision() -> None:
        _validate_expected_config_sha256(workspace, expected_config_sha256)

    try:
        _atomic_replace_text(
            config_path,
            updated,
            before_replace=check_revision,
        )
    except OSError as exc:
        raise WorkspaceError(
            f"Project configuration could not be updated: {exc}",
            code="project_config_write_failed",
        ) from exc
    return config_path


def _write_book_chapters(
    workspace: ProjectWorkspace,
    chapters: Sequence[dict[str, str | None]],
    *,
    expected_config_sha256: str,
) -> ProjectWorkspace:
    path = _commit_book_chapters(
        workspace, chapters, expected_config_sha256=expected_config_sha256
    )
    return load_workspace(path)


def _validate_book_title(value: str, *, field: str = "title") -> str:
    title = str(value or "").strip()
    try:
        title.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise WorkspaceError(
            f"Book {field} must contain valid UTF-8 text.",
            code=f"invalid_book_{field}",
        ) from exc
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
    try:
        raw.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise WorkspaceError(
            "Project folder name must contain valid UTF-8 text.",
            code="invalid_book_folder",
        ) from exc
    if (
        len(raw) > MAX_BOOK_PROJECT_FOLDER_CHARS
        or raw in {".", ".."}
        or raw.startswith(".")
        or raw.endswith((" ", "."))
        or any(character in raw for character in '<>:"/\\|?*\x00')
        or any(ord(character) < 32 for character in raw)
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


@serialized_file_write
def add_workspace_book_chapter(
    workspace: ProjectWorkspace,
    *,
    title: str,
    expected_config_sha256: str,
    position: int | None = None,
    content: str | None = None,
) -> tuple[ProjectWorkspace, dict[str, object]]:
    _validate_expected_config_sha256(workspace, expected_config_sha256)
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
    try:
        body_size = len(body.encode("utf-8")) if isinstance(body, str) else None
    except UnicodeEncodeError as exc:
        raise WorkspaceError(
            "Chapter content must contain valid UTF-8 text.",
            code="invalid_book_chapter_content",
        ) from exc
    if body_size is None or body_size > MAX_WORKSPACE_TEXT_BYTES:
        raise WorkspaceError(
            "Chapter content is invalid or too large.",
            code="invalid_book_chapter_content",
            status=413,
        )
    _atomic_replace_text(path, body)
    updated_entries = list(chapters)
    updated_entries.insert(insertion, {"path": relative, "title": chapter_title})
    try:
        config_path = _commit_book_chapters(
            workspace,
            updated_entries,
            expected_config_sha256=expected_config_sha256,
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    # A refresh can fail after the manifest has been committed (for example,
    # if another application moves the config). Never roll back its source.
    refreshed = load_workspace(config_path)
    return refreshed, {
        "path": relative,
        "absolute_path": str(path),
        "title": chapter_title,
        "index": insertion + 1,
    }


@serialized_file_write
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
    source_content = str(read_workspace_file(workspace, relative_path)["content"])
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


@serialized_file_write
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


@serialized_file_write
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



















from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .citations import MAX_BIBLIOGRAPHY_ENTRIES, load_bibliography
from .book import (
    BookManifest,
    BookRenderBundle,
    book_pdf_options,
    convert_book,
    load_book_manifest,
    render_book,
)
from .config import CONFIG_FILENAME, LoadedProjectConfig, load_project_config
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
    data = content.encode("utf-8")
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
                hint="Run `mrs-md2pdf init --book` or pass a directory containing mardas.toml.",
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
) -> tuple[str, ProjectWorkspace]:
    refreshed, manifest, bundle = _validated_book_workspace(workspace)
    options = book_pdf_options(manifest)
    return (
        build_html(
            bundle.result,
            options,
            include_cover=True,
            include_content=True,
            include_watermark=True,
        ),
        refreshed,
    )


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
    diagnostics.extend(result.diagnostics)
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
    "\\g<",
)
_QUANTIFIED_REGEX_GROUP = re.compile(r"\([^)]*\)(?:[+*]|\{)")
_LARGE_REGEX_REPEAT = re.compile(r"\{\s*(\d+)(?:\s*,\s*(\d*)?)?\s*\}")
_MAX_REGEX_REPEAT = 1_000


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
        or _QUANTIFIED_REGEX_GROUP.search(query)
        or unsafe_repeat
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
    if regex:
        pattern = _compile_workspace_regex(query, flags)
    needle = query if case_sensitive else query.casefold()
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
            if pattern is not None:
                found = list(pattern.finditer(clipped_line))
                columns = [match.start() + 1 for match in found]
            else:
                haystack = clipped_line if case_sensitive else clipped_line.casefold()
                columns = []
                start = 0
                while True:
                    index = haystack.find(needle, start)
                    if index < 0:
                        break
                    columns.append(index + 1)
                    start = index + max(1, len(needle))
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

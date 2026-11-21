from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable

from .book import (
    BookManifest,
    BookRenderBundle,
    book_pdf_options,
    convert_book,
)
from .book import load_book_manifest as load_book_manifest  # noqa: F401 - compatibility facade
from .book import render_book as render_book
from .citations import (
    MAX_BIBLIOGRAPHY_ENTRIES as MAX_BIBLIOGRAPHY_ENTRIES,  # noqa: F401 - compatibility facade
)
from .citations import load_bibliography
from .config import CONFIG_FILENAME as CONFIG_FILENAME  # noqa: F401 - compatibility facade
from .config import default_config_text as default_config_text
from .config import load_project_config as load_project_config
from .config import tomllib as tomllib
from .diagnostics import Diagnostic, has_errors
from .file_io import FILE_WRITE_LOCK as FILE_WRITE_LOCK
from .file_io import atomic_write_text as atomic_write_text  # noqa: F401 - compatibility facade
from .file_io import serialized_file_write as serialized_file_write
from .file_io import sync_directory as sync_directory
from .markdown import embed_local_images, render_markdown
from .projects.books import (
    _BOOK_PROJECT_DIRECTIONS as _BOOK_PROJECT_DIRECTIONS,
)
from .projects.books import (
    _BOOK_PROJECT_LANGUAGES as _BOOK_PROJECT_LANGUAGES,
)
from .projects.books import (
    _TOML_KEY_PATTERN as _TOML_KEY_PATTERN,
)
from .projects.books import (
    _TOML_TABLE_HEADER as _TOML_TABLE_HEADER,
)
from .projects.books import (
    _WINDOWS_RESERVED_NAMES as _WINDOWS_RESERVED_NAMES,
)
from .projects.books import (
    MAX_BOOK_CHAPTER_TITLE_CHARS as MAX_BOOK_CHAPTER_TITLE_CHARS,
)
from .projects.books import (
    MAX_BOOK_CHAPTERS as MAX_BOOK_CHAPTERS,
)
from .projects.books import (
    MAX_BOOK_PROJECT_FOLDER_CHARS as MAX_BOOK_PROJECT_FOLDER_CHARS,
)
from .projects.books import (
    MAX_BOOK_PROJECT_TITLE_CHARS as MAX_BOOK_PROJECT_TITLE_CHARS,
)
from .projects.books import (
    _book_chapter_entries as _book_chapter_entries,
)
from .projects.books import (
    _book_section_text as _book_section_text,
)
from .projects.books import (
    _commit_book_chapters as _commit_book_chapters,
)
from .projects.books import (
    _next_chapter_path as _next_chapter_path,
)
from .projects.books import (
    _relative_book_output as _relative_book_output,
)
from .projects.books import (
    _replace_toml_section as _replace_toml_section,
)
from .projects.books import (
    _safe_project_folder_name as _safe_project_folder_name,
)
from .projects.books import (
    _slug as _slug,
)
from .projects.books import (
    _toml_header_lines as _toml_header_lines,
)
from .projects.books import (
    _toml_string as _toml_string,
)
from .projects.books import (
    _validate_book_title as _validate_book_title,
)
from .projects.books import (
    _write_book_chapters as _write_book_chapters,
)
from .projects.books import (
    add_workspace_book_chapter as add_workspace_book_chapter,
)
from .projects.books import (
    create_book_workspace as create_book_workspace,
)
from .projects.books import (
    duplicate_workspace_book_chapter as duplicate_workspace_book_chapter,
)
from .projects.books import (
    remove_workspace_book_chapter as remove_workspace_book_chapter,
)
from .projects.books import (
    reorder_workspace_book_chapters as reorder_workspace_book_chapters,
)
from .projects.discovery import (
    MAX_WORKSPACE_DEPTH as MAX_WORKSPACE_DEPTH,
)
from .projects.discovery import (
    MAX_WORKSPACE_FILES as MAX_WORKSPACE_FILES,
)
from .projects.discovery import (
    MAX_WORKSPACE_SCAN_ENTRIES as MAX_WORKSPACE_SCAN_ENTRIES,
)
from .projects.discovery import (
    WORKSPACE_TEXT_SUFFIXES as WORKSPACE_TEXT_SUFFIXES,
)
from .projects.discovery import (
    _chapter_map as _chapter_map,
)
from .projects.discovery import (
    _contains_path as _contains_path,
)
from .projects.discovery import (
    _iter_workspace_files as _iter_workspace_files,
)
from .projects.discovery import (
    _kind_for_path as _kind_for_path,
)
from .projects.discovery import (
    _relative_path as _relative_path,
)
from .projects.discovery import (
    _safe_workspace_file as _safe_workspace_file,
)
from .projects.discovery import (
    _workspace_files as _workspace_files,
)
from .projects.files import (
    _WORKSPACE_SAVE_LOCK as _WORKSPACE_SAVE_LOCK,
)
from .projects.files import (
    MAX_WORKSPACE_TEXT_BYTES as MAX_WORKSPACE_TEXT_BYTES,
)
from .projects.files import (
    _atomic_replace_text as _atomic_replace_text,
)
from .projects.files import (
    _config_sha256 as _config_sha256,
)
from .projects.files import (
    _file_hash as _file_hash,
)
from .projects.files import (
    _read_bytes as _read_bytes,
)
from .projects.files import (
    _read_file_snapshot as _read_file_snapshot,
)
from .projects.files import (
    _validate_expected_config_sha256 as _validate_expected_config_sha256,
)
from .projects.files import (
    _write_workspace_file_locked as _write_workspace_file_locked,
)
from .projects.files import (
    read_workspace_file as read_workspace_file,
)
from .projects.files import (
    write_workspace_file as write_workspace_file,
)
from .projects.loading import (
    _diagnostic_dict as _diagnostic_dict,
)
from .projects.loading import (
    load_workspace as load_workspace,
)
from .projects.loading import (
    refresh_workspace as refresh_workspace,
)
from .projects.loading import (
    validate_workspace_book_payload as validate_workspace_book_payload,
)
from .projects.loading import (
    workspace_diagnostics_payload as workspace_diagnostics_payload,
)
from .projects.loading import (
    workspace_payload as workspace_payload,
)
from .projects.models import (
    ProjectWorkspace as ProjectWorkspace,
)
from .projects.models import (
    WorkspaceError as WorkspaceError,
)
from .projects.models import (
    WorkspaceFile as WorkspaceFile,
)
from .projects.paths import (
    WORKSPACE_IGNORED_PARTS as WORKSPACE_IGNORED_PARTS,
)
from .projects.search import (
    _LARGE_REGEX_REPEAT as _LARGE_REGEX_REPEAT,
)
from .projects.search import (
    _MAX_REGEX_REPEAT as _MAX_REGEX_REPEAT,
)
from .projects.search import (
    _PERSIAN_LETTER_FOLD as _PERSIAN_LETTER_FOLD,
)
from .projects.search import (
    _UNSAFE_REGEX_TOKENS as _UNSAFE_REGEX_TOKENS,
)
from .projects.search import (
    MAX_WORKSPACE_SEARCH_LINE_CHARS as MAX_WORKSPACE_SEARCH_LINE_CHARS,
)
from .projects.search import (
    MAX_WORKSPACE_SEARCH_QUERY_CHARS as MAX_WORKSPACE_SEARCH_QUERY_CHARS,
)
from .projects.search import (
    MAX_WORKSPACE_SEARCH_RESULTS as MAX_WORKSPACE_SEARCH_RESULTS,
)
from .projects.search import (
    _compile_workspace_regex as _compile_workspace_regex,
)
from .projects.search import (
    _has_quantified_regex_group as _has_quantified_regex_group,
)
from .projects.search import (
    _variable_regex_quantifier_count as _variable_regex_quantifier_count,
)
from .projects.search import (
    fold_persian_letters as fold_persian_letters,
)
from .projects.search import (
    search_workspace as search_workspace,
)
from .projects.search import (
    workspace_bibliography as workspace_bibliography,
)
from .projects.validation import (  # noqa: F401 - compatibility facade
    project_config_diagnostics as project_config_diagnostics,
)
from .projects.validation import validate_book_project as validate_book_project
from .renderer import CancellationCallback, PdfOptions, RenderSession, build_html
from .renderer import (
    RenderCancelledError as RenderCancelledError,  # noqa: F401 - compatibility facade
)


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
        progress=((lambda stage, value: progress(stage, value * 0.8)) if progress else None),
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
    create_only: bool = False,
) -> tuple[Path, str, ProjectWorkspace]:
    refreshed, manifest, bundle = _validated_book_workspace(
        workspace,
        progress=((lambda stage, value: progress(stage, value * 0.35)) if progress else None),
        cancelled=cancelled,
    )
    built, _bundle, diagnostics = convert_book(
        manifest,
        output_path=output_path,
        bundle=bundle,
        session=session,
        progress=(
            (lambda stage, value: progress(stage, 0.35 + value * 0.65)) if progress else None
        ),
        cancelled=cancelled,
        create_only=create_only,
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
        body_font=str(values.get("body_font", "theme")),
        body_size_pt=float(values.get("body_size_pt", 11)),
        body_leading=float(values.get("body_leading", 1.6)),
        paragraph_align=str(values.get("paragraph_align", "justify")),
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
        if isinstance(label, str) and label and chapter_index != current_chapter_index:
            labels.add(label)
    return frozenset(labels)


def _is_valid_cross_chapter_preview_reference(
    diagnostic: Diagnostic, known_labels: frozenset[str]
) -> bool:
    if diagnostic.code != "MARDAS-E602" or not diagnostic.message.startswith(
        _MISSING_REFERENCE_PREFIX
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
    known_cross_chapter_references = _cross_chapter_preview_reference_labels(refreshed, source_path)
    diagnostics.extend(
        item
        for item in result.diagnostics
        if not _is_valid_cross_chapter_preview_reference(item, known_cross_chapter_references)
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

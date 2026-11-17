"""Document and book validation shared by CLI and project services."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from bs4 import BeautifulSoup

from ..book import BookManifest, BookRenderBundle, load_book_manifest, render_book
from ..config import LoadedProjectConfig
from ..diagnostics import Diagnostic, has_errors
from ..markdown import MarkdownInputError, render_markdown_file
from ..render_contracts import RenderCancelledError


def _input_diagnostics(path: Path, *, required_file: bool) -> list[Diagnostic]:
    if not path.exists():
        return [Diagnostic("MARDAS-E201", "error", "Input path does not exist.", path=path)]
    if required_file and not path.is_file():
        return [
            Diagnostic("MARDAS-E202", "error", "Input must be a regular Markdown file.", path=path)
        ]
    return []


def _project_config_diagnostics(config: LoadedProjectConfig) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    path_checks = [
        ("brand_logo", "MARDAS-E113", "Configured branding logo is not a regular file."),
        ("watermark_image", "MARDAS-E114", "Configured watermark image is not a regular file."),
    ]
    for key, code, message in path_checks:
        value = config.values.get(key)
        if value is not None and not Path(value).is_file():
            diagnostics.append(Diagnostic(code, "error", message, path=Path(value)))
    for source in config.values.get("bibliography_sources", ()):
        path = Path(source)
        if not path.is_file():
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E701",
                    "error",
                    "Configured bibliography source does not exist or is not a regular file.",
                    path=path,
                )
            )

    font_dir = config.values.get("font_dir")
    if font_dir is not None and not Path(font_dir).is_dir():
        diagnostics.append(
            Diagnostic(
                "MARDAS-E115",
                "error",
                "Configured font directory does not exist or is not a directory.",
                path=Path(font_dir),
            )
        )
    if config.values.get("unsafe_html") is True:
        diagnostics.append(
            Diagnostic(
                "MARDAS-W301",
                "warning",
                "Project configuration enables unsanitized raw HTML.",
                path=config.path,
                hint="Keep security.unsafe_html=false for untrusted Markdown.",
            )
        )
    if config.values.get("allow_remote_assets") is True:
        diagnostics.append(
            Diagnostic(
                "MARDAS-W302",
                "warning",
                "Project configuration permits remote network assets.",
                path=config.path,
                hint="Remote assets can disclose network metadata and make builds non-reproducible.",
            )
        )
    return diagnostics


def _validate_document(
    path: Path,
    config: LoadedProjectConfig,
    *,
    document_root: Path | None = None,
    defer_reference_resolution: bool = False,
    defer_citation_resolution: bool = False,
) -> tuple[list[Diagnostic], dict[str, Any]]:
    diagnostics: list[Diagnostic] = []
    values = config.values
    try:
        result = render_markdown_file(
            path,
            toc=bool(values.get("toc", False)),
            toc_depth=int(values.get("toc_depth", 6)),
            language=values.get("document_language"),
            unsafe_html=bool(values.get("unsafe_html", False)),
            allow_remote_images=bool(values.get("allow_remote_assets", False)),
            document_root=document_root,
            references_enabled=values.get("references_enabled"),
            numbering_scope=values.get("numbering_scope"),
            list_of_figures=values.get("list_of_figures"),
            list_of_tables=values.get("list_of_tables"),
            list_of_equations=values.get("list_of_equations"),
            list_of_listings=values.get("list_of_listings"),
            defer_reference_resolution=defer_reference_resolution,
            citations_enabled=values.get("citations_enabled"),
            bibliography_sources=values.get("bibliography_sources"),
            citation_style=values.get("citation_style"),
            bibliography_title=values.get("bibliography_title"),
            bibliography_include_uncited=values.get("bibliography_include_uncited"),
            defer_citation_resolution=defer_citation_resolution,
        )
    except (MarkdownInputError, OSError, UnicodeError, ValueError) as exc:
        diagnostics.append(
            Diagnostic(
                "MARDAS-E203",
                "error",
                str(exc),
                path=path,
                hint="Fix the Markdown/front matter error and run validation again.",
            )
        )
        return diagnostics, {}

    if not values.get("title") and not result.metadata.get("title") and result.title == "Document":
        diagnostics.append(
            Diagnostic(
                "MARDAS-W201",
                "warning",
                "Document has no explicit title or level-one heading.",
                path=path,
                hint="Add `title` to front matter or add a `# Heading`.",
            )
        )
    if not defer_reference_resolution:
        diagnostics.extend(result.diagnostics)
    soup = BeautifulSoup(result.body_html, "html.parser")
    for placeholder in soup.select(".md2pdf-image-placeholder[data-md2pdf-blocked-src]"):
        source = str(placeholder.get("data-md2pdf-blocked-src") or "").strip()
        reason = str(placeholder.get("data-md2pdf-blocked-reason") or "").strip()
        code = "MARDAS-W203" if reason == "local" else "MARDAS-W204"
        message = (
            f"Local image could not be embedded: {source}"
            if reason == "local"
            else f"Remote image is blocked by project policy: {source}"
        )
        diagnostics.append(
            Diagnostic(
                code,
                "warning",
                message,
                path=path,
                hint=(
                    "Keep the image inside the document directory and verify its path."
                    if reason == "local"
                    else "Use a local image or explicitly enable security.allow_remote_assets for trusted projects."
                ),
            )
        )

    previous_level: int | None = None
    for level, title, _heading_id, _number in result.toc_entries:
        if previous_level is not None and level > previous_level + 1:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-W202",
                    "warning",
                    f"Heading hierarchy jumps from level {previous_level} to level {level}: {title}",
                    path=path,
                    hint="Use consecutive heading levels for a clearer document outline.",
                )
            )
        previous_level = level
    return diagnostics, {
        "title": values.get("title") or result.metadata.get("title") or result.title,
        "headings": len(result.toc_entries),
        "metadata_keys": sorted(result.metadata),
        "numbered_objects": len(result.reference_objects),
        "cited_entries": len(result.cited_keys),
        "bibliography_entries": len(result.citation_entries),
    }


def _book_validation(
    config: LoadedProjectConfig,
    *,
    progress: Callable[[str, float], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[BookManifest | None, BookRenderBundle | None, list[Diagnostic]]:
    manifest, manifest_diagnostics = load_book_manifest(config)
    diagnostics = list(manifest_diagnostics)
    if manifest is None or has_errors(diagnostics):
        return manifest, None, diagnostics

    chapter_count = max(1, len(manifest.chapters))
    for chapter in manifest.chapters:
        if cancelled and cancelled():
            raise RenderCancelledError("PDF rendering was cancelled.")
        if progress:
            progress(
                f"Validating chapter {chapter.index} of {chapter_count}",
                0.02 + 0.28 * ((chapter.index - 1) / chapter_count),
            )
        chapter_diagnostics, _context = _validate_document(
            chapter.path,
            config,
            document_root=manifest.root,
            defer_reference_resolution=bool(config.values.get("references_enabled", False)),
            defer_citation_resolution=bool(config.values.get("citations_enabled", False)),
        )
        diagnostics.extend(chapter_diagnostics)
    bundle, render_diagnostics = render_book(
        manifest,
        progress=((lambda stage, value: progress(stage, 0.3 + value * 0.7)) if progress else None),
        cancelled=cancelled,
    )
    diagnostics.extend(render_diagnostics)

    if bundle is not None:
        titles: dict[str, Path] = {}
        for summary in bundle.chapters:
            key = summary.title.strip().casefold()
            previous = titles.get(key)
            if key and previous is not None:
                diagnostics.append(
                    Diagnostic(
                        "MARDAS-W503",
                        "warning",
                        f"Book contains duplicate chapter title: {summary.title}",
                        path=summary.path,
                        hint=f"The same title was first used by {previous}.",
                    )
                )
            elif key:
                titles[key] = summary.path
    return manifest, bundle, diagnostics


def project_config_diagnostics(config: LoadedProjectConfig) -> list[Diagnostic]:
    """Return project-level diagnostics for Studio and CLI integrations."""
    return _project_config_diagnostics(config)


def validate_book_project(
    config: LoadedProjectConfig,
    *,
    progress: Callable[[str, float], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[BookManifest | None, BookRenderBundle | None, list[Diagnostic]]:
    """Validate and render a Book Mode project without formatting CLI output."""
    return _book_validation(config, progress=progress, cancelled=cancelled)

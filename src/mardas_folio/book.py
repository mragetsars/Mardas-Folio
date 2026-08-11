from __future__ import annotations

import html
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup

from .citations import CitationOptions, load_bibliography, resolve_citations
from .config import LoadedProjectConfig
from .diagnostics import Diagnostic, has_errors
from .markdown import (
    MarkdownInputError,
    MarkdownRenderResult,
    build_toc,
    normalize_language,
    render_markdown_file,
)
from .references import ReferenceOptions, resolve_cross_references
from .renderer import (
    CancellationCallback,
    PdfOptions,
    RenderCancelledError,
    RenderSession,
    convert_render_result,
)

BOOK_MARKDOWN_SUFFIXES = frozenset({".md", ".markdown", ".mdown", ".mkd"})
_BOOK_ID_REFERENCE_ATTRIBUTES = (
    "aria-controls",
    "aria-describedby",
    "aria-labelledby",
    "for",
    "headers",
)


@dataclass(frozen=True, slots=True)
class BookChapter:
    index: int
    path: Path
    title_override: str | None = None

    @property
    def prefix(self) -> str:
        return f"book-chapter-{self.index:03d}-"


@dataclass(frozen=True, slots=True)
class BookManifest:
    config: LoadedProjectConfig
    chapters: tuple[BookChapter, ...]
    output_path: Path
    chapter_page_break: bool = True

    @property
    def root(self) -> Path:
        return self.config.root


@dataclass(frozen=True, slots=True)
class BookChapterSummary:
    index: int
    path: Path
    title: str
    headings: int
    metadata_keys: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "path": str(self.path),
            "title": self.title,
            "headings": self.headings,
            "metadata_keys": list(self.metadata_keys),
        }


@dataclass(slots=True)
class BookRenderBundle:
    result: MarkdownRenderResult
    chapters: tuple[BookChapterSummary, ...]


@dataclass(slots=True)
class _PreparedChapter:
    chapter: BookChapter
    result: MarkdownRenderResult
    soup: BeautifulSoup
    entries: list[tuple[int, str, str, str]]
    id_mapping: dict[str, str]
    title: str


def _same_path(left: Path, right: Path) -> bool:
    left_resolved = left.expanduser().resolve(strict=False)
    right_resolved = right.expanduser().resolve(strict=False)
    if os.path.normcase(str(left_resolved)) == os.path.normcase(str(right_resolved)):
        return True
    try:
        return (
            left_resolved.exists()
            and right_resolved.exists()
            and left_resolved.samefile(right_resolved)
        )
    except OSError:
        return False


def _book_output_path(config: LoadedProjectConfig) -> Path:
    configured = config.values.get("book_output")
    if configured is not None:
        return Path(configured).expanduser().resolve(strict=False)
    return (config.root / "book.pdf").resolve(strict=False)


def load_book_manifest(
    config: LoadedProjectConfig,
) -> tuple[BookManifest | None, tuple[Diagnostic, ...]]:
    diagnostics: list[Diagnostic] = []
    raw_chapters = config.values.get("book_chapters")
    if config.path is None:
        diagnostics.append(
            Diagnostic(
                "MARDAS-E501",
                "error",
                "Book Mode requires a project configuration file.",
                hint="Create mardas.toml with `folio init --book`.",
            )
        )
        return None, tuple(diagnostics)
    if not raw_chapters:
        diagnostics.append(
            Diagnostic(
                "MARDAS-E502",
                "error",
                "Project configuration does not define book.chapters.",
                path=config.path,
                hint="Add an ordered [book].chapters array or run `folio init --book`.",
            )
        )
        return None, tuple(diagnostics)

    chapters: list[BookChapter] = []
    seen: list[Path] = []
    for index, item in enumerate(raw_chapters, start=1):
        path = Path(item["path"]).resolve(strict=False)
        title_override = item.get("title")
        if path.suffix.lower() not in BOOK_MARKDOWN_SUFFIXES:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E503",
                    "error",
                    "Book chapter must use a supported Markdown extension.",
                    path=path,
                    hint="Use .md, .markdown, .mdown, or .mkd.",
                )
            )
        if not path.is_file():
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E504",
                    "error",
                    "Book chapter does not exist or is not a regular file.",
                    path=path,
                )
            )
        if any(_same_path(path, previous) for previous in seen):
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E505",
                    "error",
                    "Book chapter is listed more than once.",
                    path=path,
                    hint="Each source file may appear only once in book.chapters.",
                )
            )
        else:
            seen.append(path)
        chapters.append(BookChapter(index=index, path=path, title_override=title_override))

    output_path = _book_output_path(config)
    if output_path.suffix.lower() != ".pdf":
        diagnostics.append(
            Diagnostic(
                "MARDAS-E506",
                "error",
                "Book output path must end in .pdf.",
                path=output_path,
            )
        )
    protected_paths: Iterable[Path] = [config.path, *(chapter.path for chapter in chapters)]
    for protected in protected_paths:
        if _same_path(output_path, protected):
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E507",
                    "error",
                    "Book output path collides with a project source file.",
                    path=output_path,
                    hint="Choose a distinct PDF output path.",
                )
            )
            break

    manifest = BookManifest(
        config=config,
        chapters=tuple(chapters),
        output_path=output_path,
        chapter_page_break=bool(config.values.get("book_chapter_page_break", True)),
    )
    return manifest, tuple(diagnostics)


def _rewrite_id_reference(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, list):
        return [mapping.get(str(item), str(item)) for item in value]
    tokens = str(value).split()
    return " ".join(mapping.get(token, token) for token in tokens)


def _namespace_chapter_html(
    result: MarkdownRenderResult,
    chapter: BookChapter,
) -> tuple[BeautifulSoup, list[tuple[int, str, str, str]], dict[str, str]]:
    soup = BeautifulSoup(result.body_html, "html.parser")
    mapping: dict[str, str] = {}
    for tag in soup.find_all(attrs={"id": True}):
        old_id = str(tag.get("id") or "").strip()
        if not old_id:
            continue
        new_id = f"{chapter.prefix}{old_id}"
        mapping[old_id] = new_id
        tag["id"] = new_id

    for tag in soup.find_all(True):
        href = tag.get("href")
        if isinstance(href, str) and href.startswith("#"):
            target = href[1:]
            if target in mapping:
                tag["href"] = f"#{mapping[target]}"
        xlink_href = tag.get("xlink:href")
        if isinstance(xlink_href, str) and xlink_href.startswith("#"):
            target = xlink_href[1:]
            if target in mapping:
                tag["xlink:href"] = f"#{mapping[target]}"
        for attribute in _BOOK_ID_REFERENCE_ATTRIBUTES:
            if tag.has_attr(attribute):
                tag[attribute] = _rewrite_id_reference(tag.get(attribute), mapping)

    entries: list[tuple[int, str, str, str]] = []
    for level, title, heading_id, title_html in result.toc_entries:
        entries.append(
            (level, title, mapping.get(heading_id, f"{chapter.prefix}{heading_id}"), title_html)
        )

    if chapter.title_override:
        first_h1 = soup.find("h1")
        first_h1_index = next(
            (index for index, entry in enumerate(entries) if entry[0] == 1),
            None,
        )
        if first_h1 is not None and first_h1_index is not None:
            heading_id = str(first_h1.get("id") or entries[first_h1_index][2])
            first_h1.clear()
            first_h1.append(chapter.title_override)
            anchor = soup.new_tag(
                "a",
                attrs={
                    "class": "heading-anchor",
                    "href": f"#{heading_id}",
                    "aria-label": f"Permalink to {chapter.title_override}",
                },
            )
            anchor.string = "#"
            first_h1.append(anchor)
            entries[first_h1_index] = (
                1,
                chapter.title_override,
                heading_id,
                html.escape(chapter.title_override),
            )
    return soup, entries, mapping


def _chapter_title(
    chapter: BookChapter,
    result: MarkdownRenderResult,
    entries: list[tuple[int, str, str, str]],
) -> str:
    if chapter.title_override:
        return chapter.title_override
    metadata_title = result.metadata.get("title")
    if isinstance(metadata_title, str) and metadata_title.strip():
        return metadata_title.strip()
    for level, title, _heading_id, _title_html in entries:
        if level == 1 and title.strip():
            return title.strip()
    if result.title and result.title != "Document":
        return result.title
    return (
        chapter.path.stem.replace("-", " ").replace("_", " ").strip() or f"Chapter {chapter.index}"
    )


def _synthetic_chapter_heading(
    chapter: BookChapter, title: str
) -> tuple[str, tuple[int, str, str, str]]:
    heading_id = f"{chapter.prefix}title"
    title_html = html.escape(title)
    heading = (
        f'<h1 id="{heading_id}" class="md2pdf-book-chapter-title">{title_html}'
        f'<a class="heading-anchor" href="#{heading_id}" '
        f'aria-label="Permalink to {title_html}">#</a></h1>'
    )
    return heading, (1, title, heading_id, title_html)


def _restore_cross_chapter_links(
    prepared: list[_PreparedChapter],
    diagnostics: list[Diagnostic],
) -> None:
    by_path = {item.chapter.path.resolve(strict=False): item for item in prepared}
    for item in prepared:
        for link in item.soup.select("a[data-md2pdf-source]"):
            source = str(link.get("data-md2pdf-source") or "").strip()
            if not source:
                continue
            parsed = urlsplit(source)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            target_path = (item.chapter.path.parent / unquote(parsed.path)).resolve(strict=False)
            target = by_path.get(target_path)
            if target is None:
                continue
            target_id: str | None = None
            fragment = unquote(parsed.fragment).strip()
            if fragment:
                target_id = target.id_mapping.get(fragment)
            else:
                target_id = next(
                    (entry[2] for entry in target.entries if entry[0] == 1),
                    target.entries[0][2] if target.entries else None,
                )
            if target_id is None:
                diagnostics.append(
                    Diagnostic(
                        "MARDAS-W504",
                        "warning",
                        f"Cross-chapter link target could not be resolved: {source}",
                        path=item.chapter.path,
                        hint="Reference an existing heading fragment in a listed book chapter.",
                    )
                )
                continue
            link["href"] = f"#{target_id}"
            classes = [
                value for value in link.get("class", []) if value != "md2pdf-local-link-blocked"
            ]
            if classes:
                link["class"] = classes
            elif link.has_attr("class"):
                del link["class"]
            link.attrs.pop("data-md2pdf-source", None)
            link.attrs.pop("title", None)
            link["data-md2pdf-book-link"] = "cross-chapter"


def render_book(
    manifest: BookManifest,
    *,
    progress: Callable[[str, float], None] | None = None,
    cancelled: CancellationCallback | None = None,
) -> tuple[BookRenderBundle | None, tuple[Diagnostic, ...]]:
    diagnostics: list[Diagnostic] = []
    config_values = manifest.config.values
    all_entries: list[tuple[int, str, str, str]] = []
    summaries: list[BookChapterSummary] = []
    chapter_results: list[MarkdownRenderResult] = []
    prepared: list[_PreparedChapter] = []
    css_blocks: list[str] = []
    citations_enabled = bool(config_values.get("citations_enabled", False))
    bibliography_library = None
    bibliography_sources = tuple(config_values.get("bibliography_sources") or ())
    if cancelled and cancelled():
        raise RenderCancelledError("PDF rendering was cancelled.")
    if progress:
        progress("Preparing book sources", 0.02)
    if citations_enabled:
        if not bibliography_sources:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E701",
                    "error",
                    "Book citations are enabled but bibliography.sources is empty.",
                    path=manifest.config.path,
                    hint="Add local .bib or CSL .json files to [bibliography].sources.",
                )
            )
        else:
            bibliography_library, bibliography_diagnostics = load_bibliography(bibliography_sources)
            diagnostics.extend(bibliography_diagnostics)

    if has_errors(diagnostics):
        return None, tuple(diagnostics)

    chapter_count = max(1, len(manifest.chapters))
    for chapter in manifest.chapters:
        if cancelled and cancelled():
            raise RenderCancelledError("PDF rendering was cancelled.")
        if progress:
            progress(
                f"Parsing chapter {chapter.index} of {chapter_count}",
                0.05 + 0.65 * ((chapter.index - 1) / chapter_count),
            )
        try:
            result = render_markdown_file(
                chapter.path,
                toc=False,
                toc_depth=int(config_values.get("toc_depth", 6)),
                appearance_style=config_values.get("style"),
                appearance_mode=config_values.get("mode"),
                language=config_values.get("document_language"),
                unsafe_html=bool(config_values.get("unsafe_html", False)),
                allow_remote_images=bool(config_values.get("allow_remote_assets", False)),
                document_root=manifest.root,
                references_enabled=bool(config_values.get("references_enabled", False)),
                numbering_scope=str(config_values.get("numbering_scope", "global")),
                defer_reference_resolution=bool(config_values.get("references_enabled", False)),
                citations_enabled=citations_enabled,
                bibliography_library=bibliography_library,
                citation_style=str(config_values.get("citation_style", "author-date")),
                bibliography_title=config_values.get("bibliography_title"),
                bibliography_include_uncited=bool(
                    config_values.get("bibliography_include_uncited", False)
                ),
                defer_citation_resolution=citations_enabled,
            )
        except (MarkdownInputError, OSError, UnicodeError, ValueError) as exc:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E508",
                    "error",
                    f"Could not render book chapter: {exc}",
                    path=chapter.path,
                )
            )
            continue

        diagnostics.extend(result.diagnostics)
        soup, entries, id_mapping = _namespace_chapter_html(result, chapter)
        title = _chapter_title(chapter, result, entries)
        if not any(level == 1 for level, *_rest in entries):
            synthetic_html, synthetic_entry = _synthetic_chapter_heading(chapter, title)
            fragment = BeautifulSoup(synthetic_html, "html.parser")
            first = fragment.find("h1")
            if first is not None:
                soup.insert(0, first)
            entries.insert(0, synthetic_entry)
            id_mapping["title"] = synthetic_entry[2]
            diagnostics.append(
                Diagnostic(
                    "MARDAS-W501",
                    "warning",
                    "Chapter has no level-one heading; Book Mode generated one from its title.",
                    path=chapter.path,
                    hint="Add a single level-one heading to keep the source document self-describing.",
                )
            )
        if not soup.get_text(" ", strip=True):
            diagnostics.append(
                Diagnostic(
                    "MARDAS-W502",
                    "warning",
                    "Book chapter is empty.",
                    path=chapter.path,
                )
            )
        prepared.append(
            _PreparedChapter(
                chapter=chapter,
                result=result,
                soup=soup,
                entries=entries,
                id_mapping=id_mapping,
                title=title,
            )
        )
        chapter_results.append(result)
        if result.pygments_css and result.pygments_css not in css_blocks:
            css_blocks.append(result.pygments_css)

    if has_errors(diagnostics) or not chapter_results:
        return None, tuple(diagnostics)

    if cancelled and cancelled():
        raise RenderCancelledError("PDF rendering was cancelled.")
    if progress:
        progress("Resolving book links and references", 0.74)
    _restore_cross_chapter_links(prepared, diagnostics)
    rendered_bodies: list[str] = []
    for item in prepared:
        separator = (
            '<div class="md2pdf-page-break md2pdf-book-chapter-break" aria-hidden="true"></div>'
            if rendered_bodies and manifest.chapter_page_break
            else ""
        )
        try:
            source_label = item.chapter.path.relative_to(manifest.root).as_posix()
        except ValueError:  # pragma: no cover - manifest containment prevents this
            source_label = item.chapter.path.name
        rendered_bodies.append(
            f'{separator}<section class="md2pdf-book-chapter" '
            f'data-book-chapter="{item.chapter.index}" '
            f'data-book-source="{html.escape(source_label)}">'
            f"{item.soup}</section>"
        )
        all_entries.extend(item.entries)
        summaries.append(
            BookChapterSummary(
                index=item.chapter.index,
                path=item.chapter.path,
                title=item.title,
                headings=len(item.entries),
                metadata_keys=tuple(sorted(str(key) for key in item.result.metadata)),
            )
        )

    first_metadata = dict(chapter_results[0].metadata)
    for key, config_key in (
        ("title", "title"),
        ("author", "author"),
        ("description", "description"),
    ):
        value = config_values.get(config_key)
        if value not in (None, ""):
            first_metadata[key] = value
    language = config_values.get("document_language")
    if language not in (None, "", "auto"):
        first_metadata["lang"] = language
    direction = config_values.get("document_direction")
    if direction not in (None, "", "auto"):
        first_metadata["dir"] = direction

    book_title = str(config_values.get("title") or first_metadata.get("title") or "Book")
    lang = normalize_language(first_metadata.get("lang"), "auto")
    text_hint = " ".join(summary.title for summary in summaries)
    toc_html = build_toc(
        all_entries,
        bool(config_values.get("toc", True)),
        lang=lang,
        text_hint=text_hint,
    )
    combined_body = "".join(rendered_bodies)
    reference_lists_html = ""
    reference_objects: tuple[dict[str, object], ...] = ()
    if bool(config_values.get("references_enabled", False)):
        resolved_references = resolve_cross_references(
            combined_body,
            options=ReferenceOptions(
                enabled=True,
                numbering_scope=str(config_values.get("numbering_scope", "global")),
                list_of_figures=bool(config_values.get("list_of_figures", False)),
                list_of_tables=bool(config_values.get("list_of_tables", False)),
                list_of_equations=bool(config_values.get("list_of_equations", False)),
                list_of_listings=bool(config_values.get("list_of_listings", False)),
            ),
            lang=lang,
            path=manifest.config.path,
        )
        combined_body = resolved_references.body_html
        reference_lists_html = resolved_references.lists_html
        reference_objects = tuple(item.to_dict() for item in resolved_references.objects)
        diagnostics.extend(resolved_references.diagnostics)

    bibliography_html = ""
    citation_entries: tuple[dict[str, object], ...] = ()
    cited_keys: tuple[str, ...] = ()
    if citations_enabled and bibliography_library is not None:
        resolved_citations = resolve_citations(
            combined_body,
            library=bibliography_library,
            options=CitationOptions(
                enabled=True,
                style=str(config_values.get("citation_style", "author-date")),
                title=config_values.get("bibliography_title"),
                include_uncited=bool(config_values.get("bibliography_include_uncited", False)),
            ),
            lang=lang,
            path=manifest.config.path,
        )
        combined_body = resolved_citations.body_html
        bibliography_html = resolved_citations.bibliography_html
        citation_entries = tuple(item.to_dict() for item in resolved_citations.entries)
        cited_keys = resolved_citations.cited_keys
        diagnostics.extend(resolved_citations.diagnostics)

    result = MarkdownRenderResult(
        body_html=combined_body,
        metadata=first_metadata,
        title=book_title,
        pygments_css="\n".join(css_blocks),
        toc_html=toc_html,
        toc_entries=all_entries,
        reference_lists_html=reference_lists_html,
        reference_objects=reference_objects,
        bibliography_html=bibliography_html,
        bibliography_sources=(
            bibliography_library.sources if bibliography_library is not None else ()
        ),
        citation_entries=citation_entries,
        cited_keys=cited_keys,
        diagnostics=tuple(diagnostics),
    )
    if has_errors(diagnostics):
        return None, tuple(diagnostics)
    if progress:
        progress("Book content assembled", 0.9)
    return BookRenderBundle(result=result, chapters=tuple(summaries)), tuple(diagnostics)


def book_pdf_options(
    manifest: BookManifest,
    *,
    output_path: Path | None = None,
    debug_html: Path | None = None,
    progress: Callable[[str, float], None] | None = None,
    cancelled: CancellationCallback | None = None,
) -> PdfOptions:
    values = manifest.config.values
    options = PdfOptions(
        input_path=manifest.config.path or manifest.root / "mardas.toml",
        output_path=(output_path or manifest.output_path).expanduser().resolve(strict=False),
        title=values.get("title"),
        author=values.get("author"),
        description=values.get("description"),
        toc=bool(values.get("toc", True)),
        toc_depth=int(values.get("toc_depth", 6)),
        toc_page_break=bool(values.get("toc_page_break", True)),
        h1_page_break=bool(values.get("h1_page_break", False)),
        debug_html=debug_html.expanduser().resolve(strict=False) if debug_html else None,
        page_size=str(values.get("page_size", "A4")),
        document_language=values.get("document_language"),
        document_direction=values.get("document_direction"),
        margin_top=str(values.get("margin_top", "18mm")),
        margin_bottom=str(values.get("margin_bottom", "20mm")),
        margin_x=str(values.get("margin_x", "16mm")),
        font_dir=values.get("font_dir"),
        chromium_path=str(values["chromium_path"]) if values.get("chromium_path") else None,
        chromium_sandbox=str(values.get("chromium_sandbox", "auto")),
        no_header_footer=bool(values.get("no_header_footer", False)),
        no_mathjax=bool(values.get("no_mathjax", False)),
        timeout_ms=int(values.get("timeout_ms", 120_000)),
        style=values.get("style"),
        palette=values.get("palette"),
        mode=values.get("mode"),
        cover=not bool(values.get("no_cover", False)),
        cover_logo=values.get("brand_logo"),
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
        references_enabled=bool(values.get("references_enabled", False)),
        numbering_scope=str(values.get("numbering_scope", "global")),
        list_of_figures=bool(values.get("list_of_figures", False)),
        list_of_tables=bool(values.get("list_of_tables", False)),
        list_of_equations=bool(values.get("list_of_equations", False)),
        list_of_listings=bool(values.get("list_of_listings", False)),
        citations_enabled=bool(values.get("citations_enabled", False)),
        bibliography_sources=tuple(values.get("bibliography_sources") or ()),
        citation_style=str(values.get("citation_style", "author-date")),
        bibliography_title=values.get("bibliography_title"),
        bibliography_include_uncited=bool(values.get("bibliography_include_uncited", False)),
        quality_profile=str(values.get("quality_profile", "standard")),
        math_error_policy=values.get("math_error_policy"),
        font_error_policy=values.get("font_error_policy"),
        navigation_error_policy=values.get("navigation_error_policy"),
        required_fonts=tuple(values.get("required_fonts") or ()),
        quality_report=values.get("quality_report"),
        progress=progress,
        cancelled=cancelled,
    )
    return options


def convert_book(
    manifest: BookManifest,
    *,
    output_path: Path | None = None,
    debug_html: Path | None = None,
    progress: Callable[[str, float], None] | None = None,
    cancelled: CancellationCallback | None = None,
    session: RenderSession | None = None,
    bundle: BookRenderBundle | None = None,
) -> tuple[Path | None, BookRenderBundle | None, tuple[Diagnostic, ...]]:
    diagnostics: tuple[Diagnostic, ...] = ()
    if bundle is None:
        bundle, diagnostics = render_book(
            manifest,
            progress=(
                (lambda stage, value: progress(stage, value * 0.3)) if progress else None
            ),
            cancelled=cancelled,
        )
    if bundle is None or has_errors(diagnostics):
        return None, bundle, diagnostics
    options = book_pdf_options(
        manifest,
        output_path=output_path,
        debug_html=debug_html,
        progress=(
            (lambda stage, value: progress(stage, 0.3 + value * 0.7)) if progress else None
        ),
        cancelled=cancelled,
    )
    protected = [
        manifest.config.path,
        *(chapter.path for chapter in manifest.chapters),
        *(Path(path) for path in manifest.config.values.get("bibliography_sources", ())),
    ]
    for candidate in (options.output_path, options.debug_html):
        if candidate is None:
            continue
        if any(path is not None and _same_path(candidate, path) for path in protected):
            return (
                None,
                bundle,
                diagnostics
                + (
                    Diagnostic(
                        "MARDAS-E509",
                        "error",
                        "Book output or debug HTML collides with a project source file.",
                        path=candidate,
                    ),
                ),
            )
    if options.debug_html is not None and _same_path(options.output_path, options.debug_html):
        return (
            None,
            bundle,
            diagnostics
            + (
                Diagnostic(
                    "MARDAS-E510",
                    "error",
                    "Book PDF output and debug HTML must use different paths.",
                    path=options.output_path,
                ),
            ),
        )
    if session is None:
        output = convert_render_result(bundle.result, options)
    else:
        output = convert_render_result(bundle.result, options, session=session)
    return output, bundle, diagnostics


def book_context(
    manifest: BookManifest, bundle: BookRenderBundle | None = None
) -> dict[str, object]:
    context: dict[str, object] = {
        "config": str(manifest.config.path) if manifest.config.path else None,
        "project_root": str(manifest.root),
        "output": str(manifest.output_path),
        "chapter_page_break": manifest.chapter_page_break,
        "chapter_count": len(manifest.chapters),
        "chapters": [
            {
                "index": chapter.index,
                "path": str(chapter.path),
                "title_override": chapter.title_override,
            }
            for chapter in manifest.chapters
        ],
    }
    if bundle is not None:
        context["chapters"] = [summary.to_dict() for summary in bundle.chapters]
        context["title"] = bundle.result.title
        context["headings"] = len(bundle.result.toc_entries)
        context["numbered_objects"] = len(bundle.result.reference_objects)
        context["cited_entries"] = len(bundle.result.cited_keys)
        context["bibliography_entries"] = len(bundle.result.citation_entries)
    return context

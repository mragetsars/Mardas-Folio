from __future__ import annotations

import os
import tempfile
from pathlib import Path

from pypdf import PdfReader

from .appearance import Appearance as Appearance  # noqa: F401 - compatibility facade
from .appearance import appearance_body_classes as appearance_body_classes
from .appearance import appearance_from_metadata as appearance_from_metadata
from .appearance import footer_kind as footer_kind
from .appearance import palette_css as palette_css
from .appearance import resolve_appearance as resolve_appearance
from .appearance import style_css_file as style_css_file
from .brand_assets import (
    product_logo_path as product_logo_path,  # noqa: F401 - compatibility facade
)
from .diagnostics import format_diagnostic, has_errors
from .file_io import open_atomic_output as _open_atomic_output  # noqa: F401 - compatibility facade
from .markdown import MarkdownInputError, MarkdownRenderResult, render_markdown_file
from .page_geometry import (
    NAMED_PAGE_DIMENSIONS as NAMED_PAGE_DIMENSIONS,
)
from .page_geometry import (
    _css_page_size as _css_page_size,  # noqa: F401 - compatibility facade
)
from .page_geometry import (
    _playwright_page_size_kwargs as _playwright_page_size_kwargs,  # noqa: F401 - compatibility facade
)
from .page_geometry import (
    page_geometry as page_geometry,
)
from .page_geometry import (
    validate_page_size as validate_page_size,
)
from .pdf_navigation import (  # noqa: F401 - compatibility facade
    NamedDestinationMap as NamedDestinationMap,
)
from .pdf_navigation import NavigationTracker as NavigationTracker
from .pdf_navigation import OutlineSourceEntry as OutlineSourceEntry
from .pdf_navigation import add_pdf_outline as _add_pdf_outline  # noqa: F401 - compatibility facade
from .pdf_navigation import (
    add_pdf_page_labels as _navigation_add_pdf_page_labels,  # noqa: F401 - compatibility facade
)
from .pdf_navigation import (
    copy_pdf_named_destinations as _copy_pdf_named_destinations,  # noqa: F401 - compatibility facade
)
from .pdf_navigation import enforce_navigation_quality as enforce_navigation_quality
from .pdf_navigation import (
    heading_destination_names as _heading_destination_names,  # noqa: F401 - compatibility
)
from .pdf_navigation import (
    locate_outline_pages as _locate_outline_pages,  # noqa: F401 - compatibility facade
)
from .pdf_navigation import pdf_page_texts as _pdf_page_texts  # noqa: F401 - compatibility facade
from .pdf_navigation import (
    rewrite_pdf_link_annotation_destinations as _rewrite_pdf_link_annotation_destinations,  # noqa: F401 - compatibility facade
)
from .print_layout import layout_css as _build_layout_css  # noqa: F401 - compatibility facade
from .publishing.browser_session import (
    _FONT_REPORT_SCRIPT as _FONT_REPORT_SCRIPT,  # noqa: F401 - compatibility facade
)
from .publishing.browser_session import (
    _MATHJAX_REPORT_SCRIPT as _MATHJAX_REPORT_SCRIPT,  # noqa: F401 - compatibility facade
)
from .publishing.browser_session import (
    LOGGER as LOGGER,
)
from .publishing.browser_session import (
    RenderSession as RenderSession,
)
from .publishing.browser_session import (
    _chromium_launch_args as _chromium_launch_args,  # noqa: F401 - compatibility facade
)
from .publishing.browser_session import (
    _render_page as _render_page,  # noqa: F401 - compatibility facade
)
from .publishing.browser_session import (
    _render_pdf as _render_pdf,  # noqa: F401 - compatibility facade
)
from .publishing.browser_session import (
    _resolve_pdf_chromium_path as _resolve_pdf_chromium_path,  # noqa: F401 - compatibility facade
)
from .publishing.browser_session import (
    _should_disable_chromium_sandbox as _should_disable_chromium_sandbox,  # noqa: F401 - compatibility facade
)
from .publishing.browser_session import (
    _typeset_and_validate_mathjax as _typeset_and_validate_mathjax,  # noqa: F401 - compatibility facade
)
from .publishing.browser_session import (
    _validate_browser_fonts as _validate_browser_fonts,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _MATH_SPAN_RE as _MATH_SPAN_RE,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    ALLOWED_EMBED_ASSET_MIME_TYPES as ALLOWED_EMBED_ASSET_MIME_TYPES,
)
from .publishing.html_document import (
    MAX_EMBED_ASSET_BYTES as MAX_EMBED_ASSET_BYTES,
)
from .publishing.html_document import (
    PRODUCT_BRAND_FOOTER as PRODUCT_BRAND_FOOTER,
)
from .publishing.html_document import (
    PRODUCT_BRAND_NAME as PRODUCT_BRAND_NAME,
)
from .publishing.html_document import (
    RTL_LANG_PREFIXES as RTL_LANG_PREFIXES,
)
from .publishing.html_document import (
    CoverBranding as CoverBranding,
)
from .publishing.html_document import (
    DocumentComposition as DocumentComposition,
)
from .publishing.html_document import (
    FooterContext as FooterContext,
)
from .publishing.html_document import (
    _apply_resolved_appearance as _apply_resolved_appearance,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _asset_path as _asset_path,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _asset_text as _asset_text,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _brand_logo_html as _brand_logo_html,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _cached_font_data_uri as _cached_font_data_uri,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _cached_small_image_data_uri as _cached_small_image_data_uri,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _count_math_expressions as _count_math_expressions,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _cover_brand_html as _cover_brand_html,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _cover_detail as _cover_detail,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _cover_html as _cover_html,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _cover_logo_uri as _cover_logo_uri,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _default_logo_path as _default_logo_path,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _detect_document_direction as _detect_document_direction,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _first_metadata_value as _first_metadata_value,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _font_faces as _font_faces,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _font_source_url as _font_source_url,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _footer_context as _footer_context,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _footer_page_label as _footer_page_label,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _footer_template as _footer_template,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _image_data_uri as _image_data_uri,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _language_direction as _language_direction,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _layout_css as _layout_css,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _localized_labels as _localized_labels,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _mathjax_block as _mathjax_block,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _mathjax_script as _mathjax_script,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _metadata_dict as _metadata_dict,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _metadata_items as _metadata_items,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _metadata_nested_value as _metadata_nested_value,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _metadata_path as _metadata_path,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _paragraph_block_html as _paragraph_block_html,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _path_uri as _path_uri,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _plain_html_text as _plain_html_text,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _resolve_cover_branding as _resolve_cover_branding,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _resolved_appearance as _resolved_appearance,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _resolved_document_direction as _resolved_document_direction,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _stringify_metadata_value as _stringify_metadata_value,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _style_css as _style_css,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    _watermark_html as _watermark_html,  # noqa: F401 - compatibility facade
)
from .publishing.html_document import (
    build_html as build_html,
)
from .publishing.html_document import (
    compose_document as compose_document,
)
from .publishing.html_document import (
    normalize_document_direction as normalize_document_direction,
)
from .publishing.html_document import (
    normalize_language as normalize_language,
)
from .publishing.html_document import (
    preview_appearance_payload as preview_appearance_payload,
)
from .publishing.html_document import (
    preview_page_payload as preview_page_payload,
)
from .publishing.pdf_output import (
    _add_pdf_page_labels as _add_pdf_page_labels,  # noqa: F401 - compatibility facade
)
from .publishing.pdf_output import (
    _apply_pdf_catalog_metadata as _apply_pdf_catalog_metadata,  # noqa: F401 - compatibility facade
)
from .publishing.pdf_output import (
    _apply_pdf_metadata as _apply_pdf_metadata,  # noqa: F401 - compatibility facade
)
from .publishing.pdf_output import (
    _atomic_write_pdf as _atomic_write_pdf,  # noqa: F401 - compatibility facade
)
from .publishing.pdf_output import (
    _atomic_write_text as _atomic_write_text,  # noqa: F401 - compatibility facade
)
from .publishing.pdf_output import (
    _copy_pdf_with_metadata as _copy_pdf_with_metadata,  # noqa: F401 - compatibility facade
)
from .publishing.pdf_output import (
    _enforce_navigation_report as _enforce_navigation_report,  # noqa: F401 - compatibility facade
)
from .publishing.pdf_output import (
    _keywords_metadata as _keywords_metadata,  # noqa: F401 - compatibility facade
)
from .publishing.pdf_output import (
    _merge_pdfs as _merge_pdfs,  # noqa: F401 - compatibility facade
)
from .publishing.pdf_output import (
    _outline_source_entries as _outline_source_entries,  # noqa: F401 - compatibility facade
)
from .publishing.pdf_output import (
    _path_identity_key as _path_identity_key,  # noqa: F401 - compatibility facade
)
from .publishing.pdf_output import (
    _paths_refer_to_same_file as _paths_refer_to_same_file,  # noqa: F401 - compatibility facade
)
from .publishing.pdf_output import (
    _pdf_cover_page_prefix as _pdf_cover_page_prefix,  # noqa: F401 - compatibility facade
)
from .publishing.pdf_output import (
    _pdf_date as _pdf_date,  # noqa: F401 - compatibility facade
)
from .publishing.pdf_output import (
    _pdf_date_to_iso as _pdf_date_to_iso,  # noqa: F401 - compatibility facade
)
from .publishing.pdf_output import (
    _pdf_metadata as _pdf_metadata,  # noqa: F401 - compatibility facade
)
from .publishing.pdf_output import (
    _source_date_epoch as _source_date_epoch,  # noqa: F401 - compatibility facade
)
from .publishing.pdf_output import (
    _validate_conversion_paths as _validate_conversion_paths,  # noqa: F401 - compatibility facade
)
from .publishing.pdf_output import (
    _xmp_packet as _xmp_packet,  # noqa: F401 - compatibility facade
)
from .publishing.quality import (
    _check_cancel as _check_cancel,  # noqa: F401 - compatibility facade
)
from .publishing.quality import (
    _enforce_quality_issue as _enforce_quality_issue,  # noqa: F401 - compatibility facade
)
from .publishing.quality import (
    _font_directory_manifest as _font_directory_manifest,  # noqa: F401 - compatibility facade
)
from .publishing.quality import (
    _resolve_quality_options as _resolve_quality_options,  # noqa: F401 - compatibility facade
)
from .publishing.quality import (
    _write_quality_report as _write_quality_report,  # noqa: F401 - compatibility facade
)
from .quality import FontValidationError as FontValidationError  # noqa: F401 - compatibility facade
from .quality import MathJaxRenderError as MathJaxRenderError
from .quality import RenderQualityError as RenderQualityError
from .quality import handle_quality_issue as handle_quality_issue
from .quality import profile_policy as profile_policy
from .quality import validate_quality_profile as validate_quality_profile
from .render_contracts import (
    BRANDING_MODES as BRANDING_MODES,
)
from .render_contracts import (
    CancellationCallback as CancellationCallback,
)
from .render_contracts import (
    DocumentAssetError as DocumentAssetError,
)
from .render_contracts import (
    OutputExistsError as OutputExistsError,
)
from .render_contracts import (
    OutputPathError as OutputPathError,
)
from .render_contracts import (
    OutputSidecarUnsupportedError as OutputSidecarUnsupportedError,
)
from .render_contracts import (
    PdfOptions as PdfOptions,
)
from .render_contracts import (
    ProgressCallback as ProgressCallback,
)
from .render_contracts import (
    RenderCancelledError as RenderCancelledError,
)
from .render_contracts import (
    validate_branding_mode as validate_branding_mode,
)
from .runtime import (
    resolved_chromium_path as resolved_chromium_path,  # noqa: F401 - compatibility facade
)


def _report_progress(callback: ProgressCallback | None, message: str, fraction: float) -> None:
    """Report best-effort progress without letting UI code break conversion."""
    if callback is None:
        return
    try:
        callback(message, max(0.0, min(1.0, float(fraction))))
    except Exception:
        # Progress hooks are optional UX helpers; PDF generation must not fail
        # because a terminal or GUI progress callback raised unexpectedly.
        return


def convert_render_result(
    result: MarkdownRenderResult,
    options: PdfOptions,
    *,
    session: RenderSession | None = None,
) -> Path:
    """Render an already parsed Markdown result with the standard PDF pipeline."""
    progress = options.progress
    options.input_path = Path(options.input_path)
    options.output_path = Path(options.output_path)
    options.debug_html = Path(options.debug_html) if options.debug_html else None
    options.quality_report = Path(options.quality_report) if options.quality_report else None
    options.protected_inputs = tuple(options.protected_inputs) + tuple(
        ("document image", path) for path in result.source_assets
    )
    _resolve_quality_options(options)
    _validate_conversion_paths(options)
    if options.output_create_only:
        if options.debug_html is not None or options.quality_report is not None:
            raise OutputSidecarUnsupportedError(
                "Desktop export cannot safely write debug HTML or a quality report yet. "
                "Clear those paths before exporting."
            )
        if os.path.lexists(options.output_path):
            raise OutputExistsError(
                f"The output PDF already exists. Choose a different output file: {options.output_path}"
            )
    _apply_resolved_appearance(result.metadata, options)
    _check_cancel(options)
    _report_progress(progress, "Markdown parsed", 0.16)

    title = options.title or _stringify_metadata_value(result.metadata.get("title")) or result.title
    pdf_metadata = _pdf_metadata(result, options, str(title))
    footer_context = _footer_context(result, options, str(title))
    outline_source_entries = _outline_source_entries(result)

    options.output_path.parent.mkdir(parents=True, exist_ok=True)

    if options.debug_html:
        full_debug_html = build_html(
            result,
            options,
            include_cover=True,
            include_content=True,
            include_watermark=True,
        )
        _atomic_write_text(options.debug_html, full_debug_html)
    _check_cancel(options)
    _report_progress(progress, "HTML prepared", 0.28)

    with tempfile.TemporaryDirectory(prefix="mardas-folio-") as tmpdir:
        tmp = Path(tmpdir)
        _check_cancel(options)
        with _render_page(options, session) as (page, reused_browser):
            _report_progress(
                progress,
                "Reusing Chromium" if reused_browser else "Starting Chromium",
                0.36,
            )
            if options.cover:
                cover_pdf = tmp / "cover.pdf"
                cover_html = build_html(
                    result,
                    options,
                    include_cover=True,
                    include_content=False,
                    include_watermark=False,
                    cover_full_bleed=True,
                )
                _check_cancel(options)
                _report_progress(progress, "Rendering cover", 0.48)
                _render_pdf(
                    page,
                    cover_html,
                    options,
                    cover_pdf,
                    display_footer=False,
                    footer_context=footer_context,
                )

                content_pdf = tmp / "content.pdf"
                content_html = build_html(
                    result,
                    options,
                    include_cover=False,
                    include_content=True,
                    include_watermark=True,
                )
                _check_cancel(options)
                _report_progress(progress, "Rendering content", 0.72)
                _render_pdf(
                    page,
                    content_html,
                    options,
                    content_pdf,
                    display_footer=True,
                    footer_context=footer_context,
                )
            else:
                content_pdf = tmp / "content.pdf"
                html_text = build_html(
                    result,
                    options,
                    include_cover=False,
                    include_content=True,
                    include_watermark=True,
                )
                _check_cancel(options)
                _report_progress(progress, "Rendering PDF", 0.72)
                _render_pdf(
                    page,
                    html_text,
                    options,
                    content_pdf,
                    display_footer=True,
                    footer_context=footer_context,
                )

        # Close the per-document browser context before PyPDF post-processing.
        # This releases Chromium page memory before large merge/outline operations
        # while keeping the worker's browser process available for the next job.
        _check_cancel(options)
        if options.cover:
            _report_progress(progress, "Merging PDF parts", 0.91)
            cover_page_count = len(PdfReader(str(cover_pdf)).pages)
            _merge_pdfs(
                [cover_pdf, content_pdf],
                options.output_path,
                pdf_metadata,
                outline_source_entries,
                outline_start_page=cover_page_count,
                page_label_lang=footer_context.lang,
                quality_options=options,
            )
        else:
            _report_progress(progress, "Writing metadata", 0.91)
            _copy_pdf_with_metadata(
                content_pdf,
                options.output_path,
                pdf_metadata,
                outline_source_entries,
                page_label_lang=footer_context.lang,
                quality_options=options,
            )
    options.quality_log.record(
        "render",
        "passed",
        "PDF rendering and post-processing completed.",
        details={"output": str(options.output_path)},
    )
    _write_quality_report(options)
    _report_progress(progress, "PDF created", 1.0)
    return options.output_path


def convert(options: PdfOptions, *, session: RenderSession | None = None) -> Path:
    progress = options.progress
    _check_cancel(options)
    _report_progress(progress, "Reading Markdown", 0.03)

    options.input_path = Path(options.input_path)
    result = render_markdown_file(
        options.input_path,
        toc=options.toc,
        toc_depth=options.toc_depth,
        appearance_style=options.style,
        appearance_mode=options.mode,
        language=options.document_language,
        unsafe_html=options.unsafe_html,
        allow_remote_images=options.allow_remote_assets,
        references_enabled=options.references_enabled,
        numbering_scope=options.numbering_scope,
        list_of_figures=options.list_of_figures,
        list_of_tables=options.list_of_tables,
        list_of_equations=options.list_of_equations,
        list_of_listings=options.list_of_listings,
        citations_enabled=options.citations_enabled,
        bibliography_sources=(options.bibliography_sources or None),
        citation_style=options.citation_style,
        bibliography_title=options.bibliography_title,
        bibliography_include_uncited=options.bibliography_include_uncited,
    )
    _check_cancel(options)
    if has_errors(result.diagnostics):
        raise MarkdownInputError("\n".join(format_diagnostic(item) for item in result.diagnostics))
    if not options.bibliography_sources and result.bibliography_sources:
        options.bibliography_sources = result.bibliography_sources
    return convert_render_result(result, options, session=session)

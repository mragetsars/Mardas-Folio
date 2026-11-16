"""PDF metadata, navigation, path validation, and atomic output publication."""
from __future__ import annotations
import html
import os
import re
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from pypdf import PdfReader, PdfWriter
from pypdf.generic import BooleanObject, DictionaryObject, NameObject, TextStringObject
from ..file_io import open_atomic_output as _open_atomic_output
from ..markdown import MarkdownRenderResult
from ..pdf_navigation import NamedDestinationMap, NavigationTracker, OutlineSourceEntry, add_pdf_outline as _add_pdf_outline, add_pdf_page_labels as _navigation_add_pdf_page_labels, copy_pdf_named_destinations as _copy_pdf_named_destinations, enforce_navigation_quality, locate_outline_pages as _locate_outline_pages, pdf_page_texts as _pdf_page_texts, rewrite_pdf_link_annotation_destinations as _rewrite_pdf_link_annotation_destinations
from ..render_contracts import CancellationCallback, OutputExistsError, OutputPathError, PdfOptions, RenderCancelledError
from .html_document import RTL_LANG_PREFIXES, _first_metadata_value, _metadata_items, _stringify_metadata_value, normalize_language
from .quality import _write_quality_report


def _source_date_epoch() -> datetime | None:
    raw_value = os.environ.get("SOURCE_DATE_EPOCH")
    if raw_value in (None, ""):
        return None
    try:
        timestamp = int(raw_value)
    except ValueError:
        warnings.warn(
            "Ignoring invalid SOURCE_DATE_EPOCH value; expected a Unix timestamp.",
            RuntimeWarning,
            stacklevel=2,
        )
        return None
    if timestamp < 0:
        warnings.warn(
            "Ignoring negative SOURCE_DATE_EPOCH value; expected a non-negative Unix timestamp.",
            RuntimeWarning,
            stacklevel=2,
        )
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc)


def _pdf_date(value: datetime | None = None) -> str:
    dt = value or _source_date_epoch() or datetime.now(timezone.utc).astimezone()
    offset = dt.strftime("%z")
    tz = "Z" if not offset else f"{offset[:3]}'{offset[3:]}'"
    return dt.strftime("D:%Y%m%d%H%M%S") + tz


def _keywords_metadata(metadata: dict[str, Any]) -> str:
    value = _first_metadata_value(metadata, "keywords", "tags")
    if isinstance(value, (list, tuple, set)):
        return ", ".join(_metadata_items(value))
    return _stringify_metadata_value(value, item_separator=", ")


def _pdf_date_to_iso(value: str) -> str:
    match = re.fullmatch(
        r"D:(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(Z|[+-]\d{2}'?\d{2}'?)?",
        value,
    )
    if not match:
        return ""
    year, month, day, hour, minute, second, zone = match.groups()
    if not zone or zone == "Z":
        suffix = "Z"
    else:
        compact = zone.replace("'", "")
        suffix = f"{compact[:3]}:{compact[3:]}"
    return f"{year}-{month}-{day}T{hour}:{minute}:{second}{suffix}"


def _xmp_packet(metadata: dict[str, str], *, lang: str | None) -> bytes:
    title = html.escape(str(metadata.get("/Title") or "Document"))
    author = html.escape(str(metadata.get("/Author") or ""))
    subject = html.escape(str(metadata.get("/Subject") or ""))
    keywords = html.escape(str(metadata.get("/Keywords") or ""))
    creator = html.escape(str(metadata.get("/Creator") or "Mardas Folio"))
    producer = html.escape(str(metadata.get("/Producer") or "Mardas Folio"))
    language = html.escape(normalize_language(lang, "und"))
    created = html.escape(_pdf_date_to_iso(str(metadata.get("/CreationDate") or "")))
    modified = html.escape(_pdf_date_to_iso(str(metadata.get("/ModDate") or "")))
    author_xml = (
        f"<dc:creator><rdf:Seq><rdf:li>{author}</rdf:li></rdf:Seq></dc:creator>"
        if author
        else ""
    )
    description_xml = (
        f'<dc:description><rdf:Alt><rdf:li xml:lang="x-default">{subject}</rdf:li></rdf:Alt></dc:description>'
        if subject
        else ""
    )
    keywords_xml = f"<pdf:Keywords>{keywords}</pdf:Keywords>" if keywords else ""
    create_xml = f"<xmp:CreateDate>{created}</xmp:CreateDate>" if created else ""
    modify_xml = f"<xmp:ModifyDate>{modified}</xmp:ModifyDate>" if modified else ""
    packet = (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        '  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '    <rdf:Description rdf:about=""\n'
        '      xmlns:dc="http://purl.org/dc/elements/1.1/"\n'
        '      xmlns:pdf="http://ns.adobe.com/pdf/1.3/"\n'
        '      xmlns:xmp="http://ns.adobe.com/xap/1.0/">\n'
        '      <dc:format>application/pdf</dc:format>\n'
        f'      <dc:title><rdf:Alt><rdf:li xml:lang="x-default">{title}</rdf:li></rdf:Alt></dc:title>\n'
        f'      {author_xml}\n'
        f'      {description_xml}\n'
        f'      <dc:language><rdf:Bag><rdf:li>{language}</rdf:li></rdf:Bag></dc:language>\n'
        f'      <pdf:Producer>{producer}</pdf:Producer>\n'
        f'      {keywords_xml}\n'
        f'      <xmp:CreatorTool>{creator}</xmp:CreatorTool>\n'
        f'      {create_xml}\n'
        f'      {modify_xml}\n'
        '    </rdf:Description>\n'
        '  </rdf:RDF>\n'
        '</x:xmpmeta>\n'
        '<?xpacket end="w"?>'
    )
    return packet.encode("utf-8")


def _apply_pdf_catalog_metadata(
    writer: PdfWriter, metadata: dict[str, str], *, lang: str | None
) -> None:
    language = normalize_language(lang, "und")
    writer.root_object[NameObject("/Lang")] = TextStringObject(language)
    preferences = writer.root_object.get("/ViewerPreferences")
    if preferences is not None and hasattr(preferences, "get_object"):
        preferences = preferences.get_object()
    if not isinstance(preferences, DictionaryObject):
        preferences = DictionaryObject()
        writer.root_object[NameObject("/ViewerPreferences")] = preferences
    preferences[NameObject("/DisplayDocTitle")] = BooleanObject(True)
    writer.xmp_metadata = _xmp_packet(metadata, lang=language)
    metadata_stream = cast(DictionaryObject, writer.root_object[NameObject("/Metadata")].get_object())
    metadata_stream[NameObject("/Type")] = NameObject("/Metadata")
    metadata_stream[NameObject("/Subtype")] = NameObject("/XML")


def _pdf_metadata(result: MarkdownRenderResult, options: PdfOptions, title: str) -> dict[str, str]:
    source = result.metadata
    author = options.author if options.author is not None else _first_metadata_value(source, "authors", "author")
    description = (
        options.description
        if options.description is not None
        else _first_metadata_value(source, "description", "summary", "subject")
    )
    data = {
        "/Title": str(title or result.title or "Document"),
        "/Creator": "Mardas Folio",
        "/Producer": "Mardas Folio + Playwright/Chromium + pypdf",
        "/CreationDate": _pdf_date(),
        "/ModDate": _pdf_date(),
    }
    author_text = _stringify_metadata_value(author)
    if author_text:
        data["/Author"] = author_text
    subject_text = _stringify_metadata_value(description)
    if subject_text:
        data["/Subject"] = subject_text
    keywords_text = _keywords_metadata(source)
    if keywords_text:
        data["/Keywords"] = keywords_text
    return data


def _outline_source_entries(result: MarkdownRenderResult) -> list[OutlineSourceEntry]:
    """Return clean heading entries for PDF outline creation."""
    entries: list[OutlineSourceEntry] = []
    for entry in result.toc_entries:
        if len(entry) < 3:
            continue
        level = max(1, min(int(entry[0]), 6))
        title = _stringify_metadata_value(entry[1]).strip()
        heading_id = str(entry[2] or "").strip()
        if title and heading_id:
            entries.append((level, title, heading_id))
    return entries


def _pdf_cover_page_prefix(lang: str | None = None) -> str:
    return "جلد " if normalize_language(lang).startswith(RTL_LANG_PREFIXES) else "Cover "


def _add_pdf_page_labels(
    writer: PdfWriter,
    *,
    content_start_page: int = 0,
    lang: str | None = None,
) -> None:
    _navigation_add_pdf_page_labels(
        writer,
        content_start_page=content_start_page,
        cover_prefix=_pdf_cover_page_prefix(lang),
    )


def _path_identity_key(path: Path) -> str:
    """Return a normalized path key for non-existent path comparisons."""
    return os.path.normcase(str(path.expanduser().resolve(strict=False)))


def _paths_refer_to_same_file(left: Path, right: Path) -> bool:
    """Detect textual aliases, symlinks, hardlinks, and case-folded path aliases."""
    left = Path(left)
    right = Path(right)
    try:
        if left.exists() and right.exists() and os.path.samefile(left, right):
            return True
    except OSError:
        pass
    return _path_identity_key(left) == _path_identity_key(right)


def _validate_conversion_paths(options: PdfOptions) -> None:
    input_path = Path(options.input_path)
    output_path = Path(options.output_path)
    debug_html = Path(options.debug_html) if options.debug_html else None
    quality_report = Path(options.quality_report) if options.quality_report else None

    if not input_path.exists():
        raise OutputPathError(f"Input Markdown file not found: {input_path}")
    if not input_path.is_file():
        raise OutputPathError(f"Input path is not a regular file: {input_path}")
    if output_path.exists() and output_path.is_dir():
        raise OutputPathError(f"Output PDF path is a directory: {output_path}")
    if debug_html and debug_html.exists() and debug_html.is_dir():
        raise OutputPathError(f"Debug HTML path is a directory: {debug_html}")
    if quality_report and quality_report.exists() and quality_report.is_dir():
        raise OutputPathError(f"Quality report path is a directory: {quality_report}")

    pairs = [("input Markdown", input_path, "output PDF", output_path)]
    if debug_html:
        pairs.extend(
            [
                ("input Markdown", input_path, "debug HTML", debug_html),
                ("output PDF", output_path, "debug HTML", debug_html),
            ]
        )
    if quality_report:
        pairs.extend(
            [
                ("input Markdown", input_path, "quality report", quality_report),
                ("output PDF", output_path, "quality report", quality_report),
            ]
        )
        if debug_html:
            pairs.append(("debug HTML", debug_html, "quality report", quality_report))
    for source in options.bibliography_sources:
        bibliography_path = Path(source)
        pairs.append(("bibliography source", bibliography_path, "output PDF", output_path))
        if debug_html:
            pairs.append(("bibliography source", bibliography_path, "debug HTML", debug_html))
        if quality_report:
            pairs.append(("bibliography source", bibliography_path, "quality report", quality_report))
    protected = list(options.protected_inputs)
    protected.extend(
        (label, Path(path))
        for label, path in (
            ("cover logo", options.cover_logo),
            ("brand logo", options.brand_logo),
            ("watermark image", options.watermark_image),
        )
        if path is not None
    )
    for label, path in protected:
        for output_label, candidate in (
            ("output PDF", output_path), ("debug HTML", debug_html), ("quality report", quality_report),
        ):
            if candidate is not None:
                pairs.append((label, path, output_label, candidate))
    for left_label, left, right_label, right in pairs:
        if _paths_refer_to_same_file(left, right):
            raise OutputPathError(
                f"The {left_label} and {right_label} paths must reference different files."
            )


def _atomic_write_pdf(
    writer: PdfWriter, output_path: Path, *, create_only: bool = False,
    cancelled: CancellationCallback | None = None,
) -> None:
    """Commit a complete PDF with an atomic same-directory replacement."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_path = _open_atomic_output(output_path)
    try:
        with os.fdopen(fd, "wb") as fh:
            writer.write(fh)
            fh.flush()
            os.fsync(fh.fileno())
        if cancelled is not None and cancelled():
            raise RenderCancelledError("PDF rendering was cancelled.")
        if create_only:
            try:
                os.link(temporary_path, output_path)
            except FileExistsError as exc:
                raise OutputExistsError(
                    f"The output PDF already exists. Choose a different output file: {output_path}"
                ) from exc
            temporary_path.unlink()
        else:
            os.replace(temporary_path, output_path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)
        raise


def _atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """Write text without truncating a previous valid artifact on failure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_path = _open_atomic_output(path)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary_path, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)
        raise


def _enforce_navigation_report(options: PdfOptions, tracker: NavigationTracker) -> None:
    try:
        enforce_navigation_quality(
            tracker,
            log=options.quality_log,
            policy=options.navigation_error_policy or "warn",
        )
    finally:
        _write_quality_report(options)


def _copy_pdf_with_metadata(
    input_path: Path,
    output_path: Path,
    metadata: dict[str, str],
    outline_source_entries: list[OutlineSourceEntry] | None = None,
    *,
    outline_start_page: int = 0,
    page_label_lang: str | None = None,
    quality_options: PdfOptions | None = None,
) -> None:
    reader = PdfReader(str(input_path))
    tracker = NavigationTracker()
    page_texts = _pdf_page_texts(reader, tracker=tracker) if outline_source_entries else []
    writer = PdfWriter()
    try:
        for page in reader.pages:
            writer.add_page(page)
        named_destinations = _copy_pdf_named_destinations(writer, reader, tracker=tracker)
        _rewrite_pdf_link_annotation_destinations(writer, named_destinations, tracker=tracker)
        _add_pdf_page_labels(writer, content_start_page=outline_start_page, lang=page_label_lang)
        writer.add_metadata(metadata)
        _apply_pdf_catalog_metadata(writer, metadata, lang=page_label_lang)
        if outline_source_entries:
            _add_pdf_outline(
                writer,
                _locate_outline_pages(
                    page_texts,
                    outline_source_entries,
                    named_destinations=named_destinations,
                    start_page=outline_start_page,
                    tracker=tracker,
                ),
            )
        if quality_options is not None:
            _enforce_navigation_report(quality_options, tracker)
        _atomic_write_pdf(writer, output_path,
                          create_only=bool(quality_options and quality_options.output_create_only),
                          cancelled=quality_options.cancelled if quality_options else None)
    finally:
        writer.close()


def _apply_pdf_metadata(pdf_path: Path, metadata: dict[str, str]) -> None:
    tmp_path = pdf_path.with_suffix(pdf_path.suffix + ".metadata.tmp")
    _copy_pdf_with_metadata(pdf_path, tmp_path, metadata)
    tmp_path.replace(pdf_path)


def _merge_pdfs(
    parts: list[Path],
    output_path: Path,
    metadata: dict[str, str] | None = None,
    outline_source_entries: list[OutlineSourceEntry] | None = None,
    *,
    outline_start_page: int = 0,
    page_label_lang: str | None = None,
    quality_options: PdfOptions | None = None,
) -> None:
    writer = PdfWriter()
    tracker = NavigationTracker()
    try:
        page_texts: list[str] = []
        named_destinations: NamedDestinationMap = {}
        for part in parts:
            reader = PdfReader(str(part))
            page_offset = len(writer.pages)
            if outline_source_entries:
                page_texts.extend(_pdf_page_texts(reader, tracker=tracker))
            for page in reader.pages:
                writer.add_page(page)
            named_destinations.update(
                _copy_pdf_named_destinations(
                    writer, reader, page_offset=page_offset, tracker=tracker
                )
            )
        _rewrite_pdf_link_annotation_destinations(writer, named_destinations, tracker=tracker)
        _add_pdf_page_labels(writer, content_start_page=outline_start_page, lang=page_label_lang)
        if metadata:
            writer.add_metadata(metadata)
            _apply_pdf_catalog_metadata(writer, metadata, lang=page_label_lang)
        if outline_source_entries:
            _add_pdf_outline(
                writer,
                _locate_outline_pages(
                    page_texts,
                    outline_source_entries,
                    named_destinations=named_destinations,
                    start_page=outline_start_page,
                    tracker=tracker,
                ),
            )
        if quality_options is not None:
            _enforce_navigation_report(quality_options, tracker)
        _atomic_write_pdf(writer, output_path,
                          create_only=bool(quality_options and quality_options.output_create_only),
                          cancelled=quality_options.cancelled if quality_options else None)
    finally:
        writer.close()

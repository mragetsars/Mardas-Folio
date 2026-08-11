from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from pypdf import PdfReader
from pypdf.generic import DictionaryObject, IndirectObject

from .diagnostics import Diagnostic


@dataclass(frozen=True, slots=True)
class PdfAuditResult:
    diagnostics: tuple[Diagnostic, ...]
    metrics: dict[str, object]


def _resolve(value: Any) -> Any:
    try:
        return value.get_object()
    except AttributeError:
        return value


def _font_identity(value: Any) -> tuple[int, int] | int:
    if isinstance(value, IndirectObject):
        return value.idnum, value.generation
    return id(value)


def _font_descriptor(font: DictionaryObject) -> DictionaryObject | None:
    descriptor = _resolve(font.get("/FontDescriptor"))
    if isinstance(descriptor, DictionaryObject):
        return descriptor
    descendants = _resolve(font.get("/DescendantFonts"))
    if isinstance(descendants, (list, tuple)) and descendants:
        descendant = _resolve(descendants[0])
        if isinstance(descendant, DictionaryObject):
            descriptor = _resolve(descendant.get("/FontDescriptor"))
            if isinstance(descriptor, DictionaryObject):
                return descriptor
    return None


def _font_to_unicode(font: DictionaryObject) -> bool:
    if font.get("/ToUnicode") is not None:
        return True
    descendants = _resolve(font.get("/DescendantFonts"))
    if isinstance(descendants, (list, tuple)):
        for item in descendants:
            descendant = _resolve(item)
            if isinstance(descendant, DictionaryObject) and descendant.get("/ToUnicode") is not None:
                return True
    return False


def _collect_fonts(reader: PdfReader) -> list[dict[str, object]]:
    fonts: list[dict[str, object]] = []
    seen: set[tuple[int, int] | int] = set()
    for page_index, page in enumerate(reader.pages, start=1):
        resources = _resolve(page.get("/Resources"))
        if not isinstance(resources, DictionaryObject):
            continue
        font_resources = _resolve(resources.get("/Font"))
        if not isinstance(font_resources, DictionaryObject):
            continue
        for resource_name, reference in font_resources.items():
            identity = _font_identity(reference)
            if identity in seen:
                continue
            seen.add(identity)
            font = _resolve(reference)
            if not isinstance(font, DictionaryObject):
                continue
            descriptor = _font_descriptor(font)
            subtype = str(font.get("/Subtype") or "")
            embedded = subtype == "/Type3" or bool(
                descriptor
                and any(descriptor.get(name) is not None for name in ("/FontFile", "/FontFile2", "/FontFile3"))
            )
            fonts.append(
                {
                    "resource": str(resource_name),
                    "base_font": str(font.get("/BaseFont") or ""),
                    "subtype": subtype,
                    "embedded": embedded,
                    "to_unicode": _font_to_unicode(font),
                    "first_page": page_index,
                }
            )
    return fonts


def _xmp_bytes(reader: PdfReader) -> bytes:
    metadata = _resolve(reader.root_object.get("/Metadata"))
    if metadata is None:
        return b""
    try:
        return metadata.get_data()
    except AttributeError:
        return b""


def _marked_pdf(root: DictionaryObject) -> bool:
    mark_info = _resolve(root.get("/MarkInfo"))
    if not isinstance(mark_info, DictionaryObject):
        return False
    return bool(mark_info.get("/Marked"))


def _javascript_present(root: DictionaryObject) -> bool:
    if root.get("/OpenAction") is not None or root.get("/AA") is not None:
        return True
    names = _resolve(root.get("/Names"))
    return isinstance(names, DictionaryObject) and names.get("/JavaScript") is not None


def _attachments_present(root: DictionaryObject) -> bool:
    if root.get("/AF") is not None:
        return True
    names = _resolve(root.get("/Names"))
    return isinstance(names, DictionaryObject) and names.get("/EmbeddedFiles") is not None


def _outline_count(value: Any) -> int:
    if not isinstance(value, list):
        return 0
    total = 0
    for item in value:
        if isinstance(item, list):
            total += _outline_count(item)
        else:
            total += 1
    return total


def _profile_includes(profile: str, concern: str) -> bool:
    return profile == "all" or profile == concern


def audit_pdf(path: Path, *, profile: str = "all") -> PdfAuditResult:
    path = path.expanduser().resolve()
    diagnostics: list[Diagnostic] = []
    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        return PdfAuditResult(
            (
                Diagnostic(
                    "MARDAS-P801",
                    "error",
                    f"PDF could not be opened: {exc}",
                    path=path,
                ),
            ),
            {"path": str(path), "profile": profile, "readable": False},
        )

    root = reader.root_object
    page_count = len(reader.pages)
    if page_count == 0:
        diagnostics.append(Diagnostic("MARDAS-P802", "error", "PDF contains no pages.", path=path))

    metadata = reader.metadata or {}
    language = str(root.get("/Lang") or "").strip()
    xmp = _xmp_bytes(reader)
    xmp_text = xmp.decode("utf-8", errors="ignore")
    fonts = _collect_fonts(reader)
    unembedded_fonts = [item for item in fonts if not item["embedded"]]
    fonts_without_unicode = [item for item in fonts if not item["to_unicode"]]
    tagged = root.get("/StructTreeRoot") is not None and _marked_pdf(root)
    output_intents = _resolve(root.get("/OutputIntents"))
    has_output_intent = bool(output_intents)
    has_pdfa_id = "pdfaid:part" in xmp_text and "pdfaid:conformance" in xmp_text
    has_javascript = _javascript_present(root)
    has_attachments = _attachments_present(root)

    if _profile_includes(profile, "accessibility"):
        if not language:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-P811",
                    "warning",
                    "PDF catalog does not declare a document language (/Lang).",
                    path=path,
                    hint="Set project.language or front-matter lang before rendering.",
                )
            )
        if not tagged:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-P812",
                    "warning",
                    "PDF is not a verified tagged PDF with a structure tree.",
                    path=path,
                    hint="Do not claim PDF/UA compliance; validate a tagged-PDF workflow with an independent checker.",
                )
            )
        if fonts_without_unicode:
            names = ", ".join(str(item["base_font"] or item["resource"]) for item in fonts_without_unicode[:6])
            diagnostics.append(
                Diagnostic(
                    "MARDAS-P813",
                    "warning",
                    f"{len(fonts_without_unicode)} font resource(s) have no ToUnicode map: {names}",
                    path=path,
                    hint="Text extraction and assistive technology may be unreliable for these fonts.",
                )
            )
        if not str(metadata.get("/Title") or "").strip():
            diagnostics.append(
                Diagnostic(
                    "MARDAS-P814",
                    "warning",
                    "PDF metadata does not contain a title.",
                    path=path,
                )
            )

    if _profile_includes(profile, "archival"):
        if not xmp:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-P821",
                    "warning",
                    "PDF does not contain XMP metadata.",
                    path=path,
                )
            )
        if unembedded_fonts:
            names = ", ".join(str(item["base_font"] or item["resource"]) for item in unembedded_fonts[:6])
            diagnostics.append(
                Diagnostic(
                    "MARDAS-P822",
                    "warning",
                    f"{len(unembedded_fonts)} font resource(s) are not embedded: {names}",
                    path=path,
                    hint="Archival PDFs should embed all required fonts.",
                )
            )
        if not has_output_intent:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-P823",
                    "info",
                    "PDF has no output intent profile.",
                    path=path,
                    hint="A verified PDF/A workflow normally requires an appropriate output intent.",
                )
            )
        if not has_pdfa_id:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-P824",
                    "info",
                    "XMP metadata does not declare a PDF/A part and conformance level.",
                    path=path,
                    hint="This report does not claim PDF/A compliance.",
                )
            )
        if reader.is_encrypted:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-P825",
                    "warning",
                    "PDF is encrypted, which is unsuitable for standard PDF/A profiles.",
                    path=path,
                )
            )
        if has_javascript:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-P826",
                    "warning",
                    "PDF contains JavaScript or automatic actions.",
                    path=path,
                )
            )
        if has_attachments:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-P827",
                    "warning",
                    "PDF contains embedded files or associated-file entries.",
                    path=path,
                    hint="Attachments require profile-specific archival validation.",
                )
            )

    try:
        outline_count = _outline_count(reader.outline)
    except Exception:
        outline_count = 0
    try:
        named_destination_count = len(reader.named_destinations)
    except Exception:
        named_destination_count = 0

    metrics: dict[str, object] = {
        "path": str(path),
        "profile": profile,
        "readable": True,
        "pages": page_count,
        "language": language or None,
        "tagged": tagged,
        "struct_tree": root.get("/StructTreeRoot") is not None,
        "marked": _marked_pdf(root),
        "xmp_metadata": bool(xmp),
        "pdfa_identifier": has_pdfa_id,
        "output_intent": has_output_intent,
        "encrypted": bool(reader.is_encrypted),
        "javascript": has_javascript,
        "attachments": has_attachments,
        "fonts": fonts,
        "font_count": len(fonts),
        "embedded_font_count": len(fonts) - len(unembedded_fonts),
        "to_unicode_font_count": len(fonts) - len(fonts_without_unicode),
        "outline_entries": outline_count,
        "named_destinations": named_destination_count,
        "metadata": {
            "title": str(metadata.get("/Title") or ""),
            "author": str(metadata.get("/Author") or ""),
            "subject": str(metadata.get("/Subject") or ""),
            "keywords": str(metadata.get("/Keywords") or ""),
            "creator": str(metadata.get("/Creator") or ""),
            "producer": str(metadata.get("/Producer") or ""),
        },
        "compliance_claims": {
            "pdfua": False,
            "pdfa": False,
            "note": "Readiness signals only; independent standards validation is required.",
        },
    }
    return PdfAuditResult(tuple(diagnostics), metrics)


def diagnostic_counts(diagnostics: Iterable[Diagnostic]) -> dict[str, int]:
    counts = {"error": 0, "warning": 0, "info": 0}
    for item in diagnostics:
        counts[item.severity] += 1
    return counts

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, unquote

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    Fit,
    NameObject,
    NumberObject,
    TextStringObject,
)

from .quality import PdfNavigationError, RenderQualityLog, handle_quality_issue

OutlineSourceEntry = tuple[int, str, str]
LocatedOutlineEntry = tuple[int, str, int, float | None]
NamedDestinationMap = dict[str, tuple[int, float | None, ArrayObject]]


@dataclass(slots=True)
class NavigationTracker:
    source_destinations: int = 0
    copied_destinations: int = 0
    copied_names: list[str] = field(default_factory=list)
    malformed_name_tree_entries: list[str] = field(default_factory=list)
    unmapped_destinations: list[str] = field(default_factory=list)
    out_of_range_destinations: list[str] = field(default_factory=list)
    copy_failures: list[str] = field(default_factory=list)
    annotations_seen: int = 0
    annotations_rewritten: int = 0
    unresolved_annotations: list[str] = field(default_factory=list)
    annotation_errors: list[str] = field(default_factory=list)
    text_fallback_headings: list[str] = field(default_factory=list)
    missing_heading_destinations: list[str] = field(default_factory=list)

    def details(self) -> dict[str, Any]:
        return {
            "source_destinations": self.source_destinations,
            "copied_destinations": self.copied_destinations,
            "copied_names": self.copied_names,
            "malformed_name_tree_entries": self.malformed_name_tree_entries,
            "unmapped_destinations": self.unmapped_destinations,
            "out_of_range_destinations": self.out_of_range_destinations,
            "copy_failures": self.copy_failures,
            "annotations_seen": self.annotations_seen,
            "annotations_rewritten": self.annotations_rewritten,
            "unresolved_annotations": self.unresolved_annotations,
            "annotation_errors": self.annotation_errors,
            "text_fallback_headings": self.text_fallback_headings,
            "missing_heading_destinations": self.missing_heading_destinations,
        }

    def failures(self) -> list[str]:
        messages: list[str] = []
        if self.malformed_name_tree_entries:
            messages.append("malformed destination name-tree entries")
        if self.unmapped_destinations:
            messages.append("destinations whose source pages could not be mapped")
        if self.out_of_range_destinations:
            messages.append("destinations outside the copied page range")
        if self.copy_failures:
            messages.append("named destinations that pypdf could not copy")
        if self.unresolved_annotations:
            messages.append("internal link annotations that could not be resolved")
        if self.annotation_errors:
            messages.append("link annotations that could not be inspected")
        if self.missing_heading_destinations:
            messages.append("headings without preserved named destinations")
        return messages


def destination_object(value: Any) -> Any:
    return value.get_object() if hasattr(value, "get_object") else value


def destination_array(value: Any) -> ArrayObject | None:
    value = destination_object(value)
    if isinstance(value, ArrayObject):
        return value
    if isinstance(value, dict):
        destination = value.get(NameObject("/D")) or value.get("/D")
        destination = destination_object(destination)
        if isinstance(destination, ArrayObject):
            return destination
    return None


def walk_destination_name_tree(
    node: Any,
    *,
    tracker: NavigationTracker | None = None,
    path: str = "/Names/Dests",
) -> list[tuple[str, ArrayObject]]:
    node = destination_object(node)
    if not isinstance(node, dict):
        return []
    results: list[tuple[str, ArrayObject]] = []
    names = node.get(NameObject("/Names")) or node.get("/Names")
    if isinstance(names, list):
        if len(names) % 2 and tracker is not None:
            tracker.malformed_name_tree_entries.append(f"{path}: odd /Names array length")
        for index in range(0, len(names) - 1, 2):
            name = str(names[index])
            destination = destination_array(names[index + 1])
            if destination is None:
                if tracker is not None:
                    tracker.malformed_name_tree_entries.append(f"{path}: {name}")
                continue
            results.append((name, destination))
    kids = node.get(NameObject("/Kids")) or node.get("/Kids")
    if isinstance(kids, list):
        for index, kid in enumerate(kids):
            try:
                results.extend(
                    walk_destination_name_tree(
                        kid,
                        tracker=tracker,
                        path=f"{path}/Kids[{index}]",
                    )
                )
            except (TypeError, ValueError, KeyError, IndexError) as exc:
                if tracker is not None:
                    tracker.malformed_name_tree_entries.append(
                        f"{path}/Kids[{index}]: {type(exc).__name__}: {exc}"
                    )
    return results


def iter_pdf_named_destinations(
    reader: PdfReader,
    *,
    tracker: NavigationTracker | None = None,
) -> list[tuple[str, ArrayObject]]:
    root = reader.trailer.get("/Root", {})
    destinations: list[tuple[str, ArrayObject]] = []

    legacy_dests = destination_object(root.get(NameObject("/Dests")) or root.get("/Dests"))
    if isinstance(legacy_dests, dict):
        for name, value in legacy_dests.items():
            destination = destination_array(value)
            if destination is not None:
                destinations.append((str(name), destination))
            elif tracker is not None:
                tracker.malformed_name_tree_entries.append(f"/Dests: {name}")

    names_root = destination_object(root.get(NameObject("/Names")) or root.get("/Names"))
    if isinstance(names_root, dict):
        dest_tree = names_root.get(NameObject("/Dests")) or names_root.get("/Dests")
        destinations.extend(walk_destination_name_tree(dest_tree, tracker=tracker))

    if tracker is not None:
        tracker.source_destinations += len(destinations)
    return destinations


def reader_page_index(reader: PdfReader, page_reference: Any) -> int | None:
    ref_id = getattr(page_reference, "idnum", None)
    ref_generation = getattr(page_reference, "generation", None)
    for index, page in enumerate(reader.pages):
        reference = getattr(page, "indirect_reference", None)
        if reference is None:
            continue
        if (
            getattr(reference, "idnum", None) == ref_id
            and getattr(reference, "generation", None) == ref_generation
        ):
            return index
        if ref_id is None and destination_object(page_reference) == page:
            return index
    return None


def destination_top(destination: ArrayObject) -> float | None:
    if len(destination) < 2:
        return None
    fit = str(destination[1])
    coordinate_index = 3 if fit == "/XYZ" else 2 if fit in {"/FitH", "/FitBH"} else None
    if coordinate_index is None or coordinate_index >= len(destination):
        return None
    try:
        return float(destination[coordinate_index])
    except (TypeError, ValueError):
        return None


def _writer_page_reference(writer: PdfWriter, page_index: int) -> Any | None:
    page = writer.pages[page_index]
    reference = getattr(page, "indirect_reference", None)
    if reference is not None:
        return reference
    return getattr(page, "indirect_ref", None)


def copy_pdf_named_destinations(
    writer: PdfWriter,
    reader: PdfReader,
    *,
    page_offset: int = 0,
    tracker: NavigationTracker | None = None,
) -> NamedDestinationMap:
    copied: NamedDestinationMap = {}
    destinations = iter_pdf_named_destinations(reader, tracker=tracker)
    if not destinations:
        return copied

    page_count = len(writer.pages)
    for name, destination in destinations:
        if not destination:
            if tracker is not None:
                tracker.malformed_name_tree_entries.append(f"empty destination: {name}")
            continue
        source_page_index = reader_page_index(reader, destination[0])
        if source_page_index is None:
            if tracker is not None:
                tracker.unmapped_destinations.append(name)
            continue
        target_page_index = page_offset + source_page_index
        if target_page_index < 0 or target_page_index >= page_count:
            if tracker is not None:
                tracker.out_of_range_destinations.append(name)
            continue
        page_reference = _writer_page_reference(writer, target_page_index)
        if page_reference is None:
            if tracker is not None:
                tracker.copy_failures.append(f"{name}: writer page has no indirect reference")
            continue
        copied_destination = ArrayObject([page_reference])
        copied_destination.extend(destination[1:])
        try:
            writer.add_named_destination_array(TextStringObject(name), copied_destination)
        except (TypeError, ValueError, KeyError, IndexError) as exc:
            if tracker is not None:
                tracker.copy_failures.append(f"{name}: {type(exc).__name__}: {exc}")
            continue
        copied[name] = (target_page_index, destination_top(copied_destination), copied_destination)
        if tracker is not None:
            tracker.copied_destinations += 1
            tracker.copied_names.append(name)
    return copied


def annotation_destination_lookup_names(value: Any) -> list[str]:
    value = destination_object(value)
    if isinstance(value, ArrayObject):
        return []
    text = str(value or "").strip()
    if not text:
        return []
    bare = text[1:] if text.startswith("/") else text
    encoded = quote(bare, safe="-._~")
    decoded = unquote(bare)
    names = [text, bare, f"/{bare}", encoded, f"/{encoded}", decoded, f"/{decoded}"]
    return list(dict.fromkeys(name for name in names if name))


def clone_destination_array(destination: ArrayObject) -> ArrayObject:
    clone = ArrayObject()
    clone.extend(destination)
    return clone


def resolve_named_destination_for_annotation(
    destination: Any,
    named_destinations: NamedDestinationMap,
) -> ArrayObject | None:
    for name in annotation_destination_lookup_names(destination):
        record = named_destinations.get(name)
        if record is not None:
            return clone_destination_array(record[2])
    return None


def _unresolved_annotation_name(value: Any) -> str:
    names = annotation_destination_lookup_names(value)
    return names[0] if names else str(value or "").strip()


def rewrite_pdf_link_annotation_destinations(
    writer: PdfWriter,
    named_destinations: NamedDestinationMap,
    *,
    tracker: NavigationTracker | None = None,
) -> None:
    if not named_destinations:
        return
    for page_index, page in enumerate(writer.pages):
        annotations = page.get(NameObject("/Annots")) or page.get("/Annots")
        if not annotations:
            continue
        for annotation_index, annotation_ref in enumerate(annotations):
            try:
                annotation = annotation_ref.get_object()
            except (TypeError, ValueError, KeyError, IndexError) as exc:
                if tracker is not None:
                    tracker.annotation_errors.append(
                        f"page {page_index + 1} annotation {annotation_index + 1}: {type(exc).__name__}: {exc}"
                    )
                continue
            if str(annotation.get(NameObject("/Subtype")) or annotation.get("/Subtype") or "") != "/Link":
                continue
            if tracker is not None:
                tracker.annotations_seen += 1

            direct_destination = annotation.get(NameObject("/Dest")) or annotation.get("/Dest")
            if direct_destination is not None:
                resolved = resolve_named_destination_for_annotation(
                    direct_destination, named_destinations
                )
                if resolved is not None:
                    annotation[NameObject("/Dest")] = resolved
                    if tracker is not None:
                        tracker.annotations_rewritten += 1
                    continue
                if tracker is not None and annotation_destination_lookup_names(direct_destination):
                    tracker.unresolved_annotations.append(
                        f"page {page_index + 1}: {_unresolved_annotation_name(direct_destination)}"
                    )
                continue

            action = destination_object(annotation.get(NameObject("/A")) or annotation.get("/A"))
            if not isinstance(action, dict):
                continue
            if str(action.get(NameObject("/S")) or action.get("/S") or "") != "/GoTo":
                continue
            action_destination = action.get(NameObject("/D")) or action.get("/D")
            resolved = resolve_named_destination_for_annotation(
                action_destination, named_destinations
            )
            if resolved is not None:
                action[NameObject("/D")] = resolved
                if tracker is not None:
                    tracker.annotations_rewritten += 1
            elif tracker is not None and annotation_destination_lookup_names(action_destination):
                tracker.unresolved_annotations.append(
                    f"page {page_index + 1}: {_unresolved_annotation_name(action_destination)}"
                )


def heading_destination_names(heading_id: str) -> list[str]:
    heading_id = str(heading_id or "").strip()
    if not heading_id:
        return []
    encoded = quote(heading_id, safe="-._~")
    return list(dict.fromkeys([f"/{encoded}", f"/{heading_id}", encoded, heading_id]))


def normalize_pdf_search_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "")
    text = text.replace("\u200c", " ").replace("\u200f", " ").replace("\u200e", " ")
    text = re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)
    return text.casefold()


def pdf_page_texts(reader: PdfReader, *, tracker: NavigationTracker | None = None) -> list[str]:
    texts: list[str] = []
    for index, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except (TypeError, ValueError, KeyError, IndexError) as exc:
            text = ""
            if tracker is not None:
                tracker.annotation_errors.append(
                    f"page {index + 1} text extraction: {type(exc).__name__}: {exc}"
                )
        texts.append(normalize_pdf_search_text(text))
    return texts


def locate_outline_pages(
    page_texts: list[str],
    outline_entries: list[OutlineSourceEntry],
    *,
    named_destinations: NamedDestinationMap | None = None,
    start_page: int = 0,
    tracker: NavigationTracker | None = None,
) -> list[LocatedOutlineEntry]:
    if not page_texts and not named_destinations:
        return []
    page_count = len(page_texts)
    current_page = max(0, min(start_page, page_count - 1)) if page_count else max(0, start_page)
    located: list[LocatedOutlineEntry] = []

    for level, title, heading_id in outline_entries:
        destination_page: int | None = None
        destination_top_value: float | None = None
        for destination_name in heading_destination_names(heading_id):
            if named_destinations and destination_name in named_destinations:
                destination_page, destination_top_value, _destination = named_destinations[
                    destination_name
                ]
                break

        needle = normalize_pdf_search_text(title)
        page_index = destination_page if destination_page is not None else current_page
        if destination_page is None:
            found = False
            if needle and page_texts:
                for index in range(current_page, page_count):
                    if needle in page_texts[index]:
                        page_index = index
                        found = True
                        break
            if tracker is not None:
                tracker.missing_heading_destinations.append(heading_id)
                if found:
                    tracker.text_fallback_headings.append(heading_id)
        current_page = page_index
        located.append(
            (max(1, min(level, 6)), title, page_index, destination_top_value)
        )
    return located


def add_pdf_outline(writer: PdfWriter, outline_entries: list[LocatedOutlineEntry]) -> None:
    parents: dict[int, Any] = {}
    page_count = len(writer.pages)
    for level, title, page_index, top in outline_entries:
        if not title or page_index < 0 or page_index >= page_count:
            continue
        parent = parents.get(level - 1)
        fit = Fit.xyz(left=0, top=top, zoom=None) if top is not None else Fit.fit()
        item = writer.add_outline_item(title, page_index, parent=parent, fit=fit)
        parents[level] = item
        for child_level in [key for key in parents if key > level]:
            del parents[child_level]


def add_pdf_page_labels(
    writer: PdfWriter,
    *,
    content_start_page: int = 0,
    cover_prefix: str = "Cover ",
) -> None:
    page_count = len(writer.pages)
    if page_count <= 0:
        return
    start = max(0, min(int(content_start_page or 0), page_count - 1))
    nums = ArrayObject()
    if start > 0:
        nums.append(NumberObject(0))
        nums.append(
            DictionaryObject(
                {
                    NameObject("/S"): NameObject("/D"),
                    NameObject("/St"): NumberObject(1),
                    NameObject("/P"): TextStringObject(cover_prefix),
                }
            )
        )
    nums.append(NumberObject(start))
    nums.append(
        DictionaryObject(
            {NameObject("/S"): NameObject("/D"), NameObject("/St"): NumberObject(1)}
        )
    )
    writer.root_object[NameObject("/PageLabels")] = DictionaryObject(
        {NameObject("/Nums"): nums}
    )


def enforce_navigation_quality(
    tracker: NavigationTracker,
    *,
    log: RenderQualityLog,
    policy: str,
) -> None:
    failures = tracker.failures()
    details = tracker.details()
    if failures:
        handle_quality_issue(
            log,
            category="navigation",
            policy=policy,
            message="PDF navigation validation failed: " + "; ".join(failures) + ".",
            details=details,
            error_type=PdfNavigationError,
        )
        return
    log.record(
        "navigation",
        "passed",
        "PDF named destinations, internal TOC links, outlines, and page labels were preserved.",
        details=details,
    )

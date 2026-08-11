from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup, NavigableString, Tag

from .diagnostics import Diagnostic
from .markdown import dominant_direction, normalize_language, ui_label

REFERENCE_KINDS = ("fig", "tbl", "eq", "lst")
REFERENCE_SCOPE_VALUES = ("global", "chapter")
LABEL_NAME_RE = r"[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?"
LABEL_RE = re.compile(rf"^(?P<kind>{'|'.join(REFERENCE_KINDS)}):(?P<name>{LABEL_NAME_RE})$")
LABEL_MARKER_RE = re.compile(rf"\{{#(?P<label>(?:{'|'.join(REFERENCE_KINDS)}):{LABEL_NAME_RE})\}}")
LABEL_MARKER_CANDIDATE_RE = re.compile(
    rf"\{{#(?P<label>(?:{'|'.join(REFERENCE_KINDS)}):[^{{}}\n]*)\}}"
)
REFERENCE_TOKEN_RE = re.compile(
    rf"(?<![\w@])@(?P<label>(?:{'|'.join(REFERENCE_KINDS)}):{LABEL_NAME_RE})"
)

_KIND_LABEL_KEYS = {
    "fig": "caption_figure",
    "tbl": "caption_table",
    "eq": "caption_equation",
    "lst": "caption_code",
}
_LIST_TITLES = {
    "fa": {
        "fig": "فهرست شکل‌ها",
        "tbl": "فهرست جدول‌ها",
        "eq": "فهرست معادله‌ها",
        "lst": "فهرست کدها",
    },
    "en": {
        "fig": "List of Figures",
        "tbl": "List of Tables",
        "eq": "List of Equations",
        "lst": "List of Listings",
    },
}
_CAPTION_PREFIX_RE = re.compile(
    r"^(?:"
    r"figure|fig\.?|image|diagram|table|listing|code|equation|eq\.?|"
    r"شکل|تصویر|نمودار|جدول|کد|معادله"
    r")(?:\s+[0-9۰-۹٠-٩]+(?:[.-][0-9۰-۹٠-٩]+)?)?[\s:：.\-–—]*",
    re.IGNORECASE,
)
_SKIP_REFERENCE_PARENTS = {"a", "code", "pre", "script", "style", "textarea", "kbd", "samp"}


@dataclass(frozen=True, slots=True)
class ReferenceOptions:
    enabled: bool = False
    numbering_scope: str = "global"
    list_of_figures: bool = False
    list_of_tables: bool = False
    list_of_equations: bool = False
    list_of_listings: bool = False

    def list_enabled(self, kind: str) -> bool:
        return {
            "fig": self.list_of_figures,
            "tbl": self.list_of_tables,
            "eq": self.list_of_equations,
            "lst": self.list_of_listings,
        }.get(kind, False)


@dataclass(frozen=True, slots=True)
class NumberedObject:
    label: str
    kind: str
    number: str
    target_id: str
    caption: str
    chapter_index: int | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "label": self.label,
            "kind": self.kind,
            "number": self.number,
            "target_id": self.target_id,
            "caption": self.caption,
        }
        if self.chapter_index is not None:
            data["chapter_index"] = self.chapter_index
        return data


@dataclass(frozen=True, slots=True)
class ReferenceProcessResult:
    body_html: str
    lists_html: str
    objects: tuple[NumberedObject, ...]
    diagnostics: tuple[Diagnostic, ...]


def validate_numbering_scope(value: str | None) -> str:
    normalized = str(value or "global").strip().lower()
    if normalized not in REFERENCE_SCOPE_VALUES:
        raise ValueError(f"must be one of: {', '.join(REFERENCE_SCOPE_VALUES)}")
    return normalized


def _language_family(lang: str | None, text_hint: str = "") -> str:
    normalized = normalize_language(lang, "auto")
    if normalized.startswith(("fa", "ar", "ur", "he", "ps")):
        return "fa"
    if normalized.startswith("en"):
        return "en"
    return "fa" if dominant_direction(text_hint) == "rtl" else "en"


def _localized_number(value: str, family: str) -> str:
    if family != "fa":
        return value
    translation = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
    return value.translate(translation)


def _kind_label(kind: str, *, lang: str | None, text_hint: str = "") -> str:
    key = _KIND_LABEL_KEYS[kind]
    return ui_label(key, lang=lang, text_hint=text_hint)


def _reference_display(kind: str, number: str, *, lang: str | None, text_hint: str = "") -> str:
    family = _language_family(lang, text_hint)
    return (
        f"{_kind_label(kind, lang=lang, text_hint=text_hint)} {_localized_number(number, family)}"
    )


def _target_for_label(label: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", label.replace(":", "-"))
    return f"xref-{safe.strip('-') or 'item'}"


def _kind_for_object(tag: Tag) -> str | None:
    if tag.name == "table":
        return "tbl"
    if tag.name == "div" and "math" in tag.get("class", []) and "display" in tag.get("class", []):
        return "eq"
    if tag.name != "figure":
        return None
    classes = set(tag.get("class", []))
    if "code-block" in classes:
        return "lst"
    if "md2pdf-equation" in classes:
        return "eq"
    return "fig"


def _object_from_container(tag: Tag) -> Tag | None:
    kind = _kind_for_object(tag)
    if kind:
        return tag
    if tag.name == "div" and "table-wrap" in tag.get("class", []):
        table = tag.find("table", recursive=False)
        return table if isinstance(table, Tag) else None
    return None


def _caption_tag(obj: Tag) -> Tag | None:
    if obj.name == "table":
        caption = obj.find("caption", recursive=False)
        return caption if isinstance(caption, Tag) else None
    if obj.name == "figure":
        caption = obj.find("figcaption", recursive=False)
        return caption if isinstance(caption, Tag) else None
    return None


def _append_fragment(parent: Tag, fragment_html: str) -> None:
    fragment = BeautifulSoup(fragment_html, "html.parser")
    for child in list(fragment.contents):
        parent.append(child.extract())


def _has_literal_parent(node: NavigableString, *, boundary: Tag | None = None) -> bool:
    for parent in node.parents:
        if boundary is not None and parent is boundary:
            break
        if isinstance(parent, Tag) and parent.name in _SKIP_REFERENCE_PARENTS:
            return True
    return False


def _strip_label_markers(tag: Tag) -> list[str]:
    labels: list[str] = []
    for node in list(tag.find_all(string=True)):
        if not isinstance(node, NavigableString) or _has_literal_parent(node, boundary=tag):
            continue
        text = str(node)
        matches = list(LABEL_MARKER_RE.finditer(text))
        if not matches:
            continue
        labels.extend(match.group("label") for match in matches)
        replacement = LABEL_MARKER_RE.sub("", text)
        if replacement:
            node.replace_with(NavigableString(replacement))
        else:
            node.extract()
    return labels


def _standalone_marker(paragraph: Tag) -> str | None:
    if paragraph.find(list(_SKIP_REFERENCE_PARENTS)) is not None:
        return None
    text = paragraph.get_text(" ", strip=True)
    match = LABEL_MARKER_RE.fullmatch(text)
    return match.group("label") if match else None


def _nearest_preceding_object(paragraph: Tag) -> Tag | None:
    sibling = paragraph.find_previous_sibling()
    while isinstance(sibling, Tag) and sibling.name in {"br"}:
        sibling = sibling.find_previous_sibling()
    return _object_from_container(sibling) if isinstance(sibling, Tag) else None


def _ensure_figure_for_equation(soup: BeautifulSoup, equation: Tag) -> Tag:
    if equation.name == "figure":
        return equation
    figure = soup.new_tag("figure")
    figure["class"] = ["md2pdf-equation"]
    figure["dir"] = "ltr"
    equation.replace_with(figure)
    figure.append(equation)
    return figure


def _ensure_caption(soup: BeautifulSoup, obj: Tag, kind: str) -> Tag | None:
    existing = _caption_tag(obj)
    if existing is not None:
        return existing
    if kind == "eq":
        return None
    caption_name = "caption" if obj.name == "table" else "figcaption"
    caption = soup.new_tag(caption_name)
    caption["class"] = ["md2pdf-caption", f"md2pdf-caption--{'code' if kind == 'lst' else kind}"]
    caption["dir"] = "auto"
    if kind == "fig":
        image = obj.find("img")
        alt = str(image.get("alt") or "").strip() if isinstance(image, Tag) else ""
        if alt:
            caption.string = alt
    obj.append(caption)
    return caption


def _caption_plain_text(obj: Tag, kind: str) -> str:
    caption = _caption_tag(obj)
    if caption is None:
        if kind == "eq":
            return ""
        return ""
    return _CAPTION_PREFIX_RE.sub("", caption.get_text(" ", strip=True)).strip()


def _replace_caption_prefix(
    soup: BeautifulSoup,
    obj: Tag,
    *,
    kind: str,
    number: str,
    lang: str | None,
) -> str:
    caption = _ensure_caption(soup, obj, kind)
    text_hint = caption.get_text(" ", strip=True) if caption is not None else ""
    display = _reference_display(kind, number, lang=lang, text_hint=text_hint)
    if kind == "eq":
        equation = obj.find(class_=lambda value: value and "math" in value and "display" in value)
        equation_text = equation.get_text(" ", strip=True) if isinstance(equation, Tag) else ""
        equation_text = equation_text.strip("$").strip()
        if len(equation_text) > 160:
            equation_text = equation_text[:157].rstrip() + "..."
        number_span = soup.new_tag("span")
        number_span["class"] = ["md2pdf-equation-number"]
        number_span["aria-label"] = display
        family = _language_family(lang, text_hint)
        number_span.string = f"({_localized_number(number, family)})"
        obj.append(number_span)
        return equation_text

    if caption is None:
        return ""
    for existing in list(caption.select(":scope > .md2pdf-caption-label")):
        existing.decompose()
    for node in list(caption.find_all(string=True)):
        if not isinstance(node, NavigableString):
            continue
        text = str(node)
        stripped = _CAPTION_PREFIX_RE.sub("", text, count=1)
        if stripped != text:
            if stripped:
                node.replace_with(NavigableString(stripped.lstrip()))
            else:
                node.extract()
            break
    label_span = soup.new_tag("span")
    label_span["class"] = ["md2pdf-caption-label"]
    label_span.string = display
    caption.insert(0, NavigableString(" "))
    caption.insert(0, label_span)
    caption_classes = set(caption.get("class", []))
    caption_classes.add("md2pdf-caption--numbered")
    family = _language_family(lang, text_hint)
    number_profile = "persian" if family == "fa" else "latin"
    caption_classes.add(f"md2pdf-caption--{number_profile}-number")
    caption["data-md2pdf-number-profile"] = number_profile
    caption["class"] = sorted(caption_classes)
    return _caption_plain_text(obj, kind)


def _validate_label_marker_syntax(
    soup: BeautifulSoup, diagnostics: list[Diagnostic], path: Path | None
) -> None:
    for node in list(soup.find_all(string=LABEL_MARKER_CANDIDATE_RE)):
        if not isinstance(node, NavigableString) or _has_literal_parent(node):
            continue
        for match in LABEL_MARKER_CANDIDATE_RE.finditer(str(node)):
            marker = match.group(0)
            if LABEL_MARKER_RE.fullmatch(marker):
                continue
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E605",
                    "error",
                    f"Invalid reference label marker: {marker}",
                    path=path,
                    hint=(
                        "Use an ASCII label such as {#fig:architecture}; names may contain "
                        "letters, digits, dots, underscores, and hyphens and must end with "
                        "a letter or digit."
                    ),
                )
            )


def _prepare_objects(soup: BeautifulSoup, diagnostics: list[Diagnostic], path: Path | None) -> None:
    for paragraph in list(soup.find_all("p")):
        label = _standalone_marker(paragraph)
        if not label:
            continue
        obj = _nearest_preceding_object(paragraph)
        if obj is None:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-W603",
                    "warning",
                    f"Reference label is not attached to a supported object: {label}",
                    path=path,
                    hint="Place the label immediately after a figure, table, display equation, or code block.",
                )
            )
            continue
        if _kind_for_object(obj) == "eq":
            obj = _ensure_figure_for_equation(soup, obj)
        existing = str(obj.get("data-md2pdf-label") or "").strip()
        if existing and existing != label:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E604",
                    "error",
                    f"Object has more than one reference label: {existing}, {label}",
                    path=path,
                )
            )
        else:
            obj["data-md2pdf-label"] = label
        paragraph.decompose()

    candidates: list[Tag] = []
    candidates.extend(tag for tag in soup.find_all("figure") if isinstance(tag, Tag))
    candidates.extend(tag for tag in soup.find_all("table") if isinstance(tag, Tag))
    candidates.extend(
        tag
        for tag in soup.find_all(
            "div", class_=lambda value: value and "math" in value and "display" in value
        )
        if isinstance(tag, Tag)
        and not tag.find_parent("figure", class_=lambda value: value and "md2pdf-equation" in value)
    )
    for obj in list(candidates):
        kind = _kind_for_object(obj)
        if kind is None:
            continue
        caption = _caption_tag(obj)
        labels = _strip_label_markers(caption) if caption is not None else []
        existing = str(obj.get("data-md2pdf-label") or "").strip()
        all_labels = ([existing] if existing else []) + labels
        unique = list(dict.fromkeys(label for label in all_labels if label))
        if len(unique) > 1:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E604",
                    "error",
                    f"Object has more than one reference label: {', '.join(unique)}",
                    path=path,
                )
            )
            continue
        if unique:
            obj["data-md2pdf-label"] = unique[0]


def _prepare_reference_tokens(soup: BeautifulSoup) -> None:
    for node in list(soup.find_all(string=REFERENCE_TOKEN_RE)):
        if not isinstance(node, NavigableString):
            continue
        parent = node.parent
        if not isinstance(parent, Tag):
            continue
        if parent.name in _SKIP_REFERENCE_PARENTS or parent.find_parent(_SKIP_REFERENCE_PARENTS):
            continue
        if parent.find_parent(class_=lambda value: value and "math" in value):
            continue
        text = str(node)
        fragments: list[str | Tag] = []
        cursor = 0
        for match in REFERENCE_TOKEN_RE.finditer(text):
            if match.start() > cursor:
                fragments.append(text[cursor : match.start()])
            label = match.group("label")
            anchor = soup.new_tag("a")
            anchor["class"] = ["md2pdf-xref"]
            anchor["data-md2pdf-reference"] = label
            anchor.string = match.group(0)
            fragments.append(anchor)
            cursor = match.end()
        if cursor == 0:
            continue
        if cursor < len(text):
            fragments.append(text[cursor:])
        for fragment in reversed(fragments):
            node.insert_after(fragment if isinstance(fragment, Tag) else NavigableString(fragment))
        node.extract()


def annotate_reference_markup(
    body_html: str,
    *,
    path: Path | None = None,
    lang: str | None = None,
) -> tuple[str, tuple[Diagnostic, ...]]:
    soup = BeautifulSoup(body_html, "html.parser")
    diagnostics: list[Diagnostic] = []
    _validate_label_marker_syntax(soup, diagnostics, path)
    _prepare_objects(soup, diagnostics, path)
    _prepare_reference_tokens(soup)
    normalized_lang = normalize_language(lang, "auto")
    for tag in soup.find_all(attrs={"data-md2pdf-label": True}):
        tag["data-md2pdf-reference-lang"] = normalized_lang
    for tag in soup.find_all(attrs={"data-md2pdf-reference": True}):
        tag["data-md2pdf-reference-lang"] = normalized_lang
    return str(soup), tuple(diagnostics)


def _chapter_index(obj: Tag) -> int | None:
    section = obj.find_parent(attrs={"data-book-chapter": True})
    if not isinstance(section, Tag):
        return None
    try:
        value = int(str(section.get("data-book-chapter") or ""))
    except ValueError:
        return None
    return value if value > 0 else None


def _objects_in_document_order(soup: BeautifulSoup) -> Iterable[Tag]:
    for tag in soup.find_all(attrs={"data-md2pdf-label": True}):
        if isinstance(tag, Tag):
            yield tag


def _build_lists(
    objects: list[NumberedObject],
    *,
    options: ReferenceOptions,
    lang: str | None,
    text_hint: str,
) -> str:
    family = _language_family(lang, text_hint)
    blocks: list[str] = []
    for kind in REFERENCE_KINDS:
        if not options.list_enabled(kind):
            continue
        items = [item for item in objects if item.kind == kind]
        if not items:
            continue
        title = _LIST_TITLES[family][kind]
        entries = []
        for item in items:
            display = _reference_display(kind, item.number, lang=lang, text_hint=item.caption)
            caption = item.caption or display
            entries.append(
                '<li class="md2pdf-reference-list-item">'
                f'<a href="#{html.escape(item.target_id)}">'
                f'<span class="md2pdf-reference-list-number">{html.escape(display)}</span>'
                f'<span class="md2pdf-reference-list-title">{html.escape(caption)}</span>'
                "</a></li>"
            )
        blocks.append(
            f'<nav class="md2pdf-reference-list md2pdf-reference-list--{kind}" '
            f'aria-label="{html.escape(title)}">'
            f'<h2 class="md2pdf-reference-list-heading">{html.escape(title)}</h2>'
            f'<ol class="md2pdf-reference-list-items">{"".join(entries)}</ol>'
            "</nav>"
        )
    if not blocks:
        return ""
    return '<section class="md2pdf-reference-lists">' + "".join(blocks) + "</section>"


def _diagnostic_path_for_tag(tag: Tag, fallback: Path | None) -> Path | None:
    section = tag.find_parent(attrs={"data-book-source": True})
    if isinstance(section, Tag):
        source = str(section.get("data-book-source") or "").strip()
        if source:
            base = (
                fallback
                if fallback is not None and fallback.is_dir()
                else (fallback.parent if fallback is not None else Path.cwd())
            )
            return (base / source).resolve(strict=False)
    return fallback


def resolve_cross_references(
    body_html: str,
    *,
    options: ReferenceOptions,
    lang: str | None = None,
    path: Path | None = None,
) -> ReferenceProcessResult:
    if not options.enabled:
        return ReferenceProcessResult(body_html, "", (), ())

    scope = validate_numbering_scope(options.numbering_scope)
    soup = BeautifulSoup(body_html, "html.parser")
    diagnostics: list[Diagnostic] = []
    seen: dict[str, NumberedObject] = {}
    counters = {kind: 0 for kind in REFERENCE_KINDS}
    chapter_counters: dict[tuple[int, str], int] = {}
    objects: list[NumberedObject] = []
    text_hint = soup.get_text(" ", strip=True)
    original_ids = [str(tag.get("id") or "").strip() for tag in soup.find_all(attrs={"id": True})]
    original_id_counts = Counter(value for value in original_ids if value)
    reserved_ids = set(original_ids)

    for obj in _objects_in_document_order(soup):
        label = str(obj.get("data-md2pdf-label") or "").strip()
        match = LABEL_RE.fullmatch(label)
        if not match:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E605",
                    "error",
                    f"Invalid reference label: {label}",
                    path=_diagnostic_path_for_tag(obj, path),
                    hint="Use labels such as fig:architecture, tbl:results, eq:energy, or lst:training-loop.",
                )
            )
            continue
        kind = _kind_for_object(obj)
        if kind is None:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E605",
                    "error",
                    f"Reference label is not attached to a supported object: {label}",
                    path=_diagnostic_path_for_tag(obj, path),
                )
            )
            continue
        declared_kind = match.group("kind")
        if declared_kind != kind:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E603",
                    "error",
                    f"Reference label kind {declared_kind!r} does not match the attached {kind!r} object: {label}",
                    path=_diagnostic_path_for_tag(obj, path),
                )
            )
            continue
        if label in seen:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E601",
                    "error",
                    f"Reference label is defined more than once: {label}",
                    path=_diagnostic_path_for_tag(obj, path),
                    hint="Use a unique label across the complete document or book.",
                )
            )
            continue

        chapter = _chapter_index(obj)
        if scope == "chapter" and chapter is not None:
            key = (chapter, kind)
            chapter_counters[key] = chapter_counters.get(key, 0) + 1
            number = f"{chapter}.{chapter_counters[key]}"
        else:
            counters[kind] += 1
            number = str(counters[kind])

        existing_id = str(obj.get("id") or "").strip()
        target_base = _target_for_label(label)
        target_id = target_base
        suffix = 2
        while target_id in reserved_ids and not (
            target_id == existing_id and original_id_counts.get(existing_id, 0) == 1
        ):
            target_id = f"{target_base}-{suffix}"
            suffix += 1

        if existing_id and existing_id != target_id:
            # Preserve a unique author-supplied anchor while assigning every semantic
            # object its own deterministic xref destination. Duplicate raw IDs were
            # already ambiguous, so they are removed rather than copied forward.
            if original_id_counts.get(existing_id, 0) == 1:
                legacy_anchor = soup.new_tag("span")
                legacy_anchor["id"] = existing_id
                legacy_anchor["class"] = ["md2pdf-reference-target"]
                legacy_anchor["aria-hidden"] = "true"
                obj.insert_before(legacy_anchor)
            obj.attrs.pop("id", None)
        obj["id"] = target_id
        reserved_ids.add(target_id)

        obj["data-md2pdf-reference-kind"] = kind
        obj["data-md2pdf-reference-number"] = number
        object_lang = str(obj.get("data-md2pdf-reference-lang") or lang or "auto")
        classes = set(obj.get("class", []))
        classes.add("md2pdf-numbered-object")
        classes.add(f"md2pdf-numbered-object--{kind}")
        obj["class"] = sorted(classes)
        caption = _replace_caption_prefix(
            soup,
            obj,
            kind=kind,
            number=number,
            lang=object_lang,
        )
        item = NumberedObject(
            label=label,
            kind=kind,
            number=number,
            target_id=target_id,
            caption=caption,
            chapter_index=chapter,
        )
        seen[label] = item
        objects.append(item)

    for anchor in soup.select("a[data-md2pdf-reference]"):
        label = str(anchor.get("data-md2pdf-reference") or "").strip()
        target = seen.get(label)
        if target is None:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E602",
                    "error",
                    f"Reference target is not defined: {label}",
                    path=_diagnostic_path_for_tag(anchor, path),
                    hint="Add a matching object label or correct the @reference token.",
                )
            )
            anchor.name = "span"
            anchor.attrs.pop("href", None)
            anchor["class"] = ["md2pdf-xref", "md2pdf-xref--unresolved"]
            anchor.string = f"@{label}"
            continue
        anchor["href"] = f"#{target.target_id}"
        anchor["data-md2pdf-reference-kind"] = target.kind
        anchor["data-md2pdf-reference-number"] = target.number
        anchor["class"] = ["md2pdf-xref", "md2pdf-xref--resolved"]
        anchor_lang = str(anchor.get("data-md2pdf-reference-lang") or lang or "auto")
        anchor.string = _reference_display(
            target.kind,
            target.number,
            lang=anchor_lang,
            text_hint=target.caption or text_hint,
        )

    lists_html = _build_lists(
        objects,
        options=options,
        lang=lang,
        text_hint=text_hint,
    )
    return ReferenceProcessResult(
        body_html=str(soup),
        lists_html=lists_html,
        objects=tuple(objects),
        diagnostics=tuple(diagnostics),
    )

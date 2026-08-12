from __future__ import annotations

import base64
import html
import mimetypes
import re
import unicodedata
import warnings
from urllib.parse import unquote, urlparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    from .citations import BibliographyLibrary

try:
    import yaml
except Exception:  # pragma: no cover - PyYAML is declared as dependency
    yaml = None

from bs4 import BeautifulSoup, NavigableString, Tag
from markdown_it import MarkdownIt
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound

from .appearance import appearance_from_metadata, code_style_for_appearance, resolve_appearance
from .diagnostics import Diagnostic
from .mermaid import render_mermaid_to_svg

ARABIC_RANGES = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
LATIN_RANGES = re.compile(r"[A-Za-z]")
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)
FOOTNOTE_DEF_RE = re.compile(r"^\[\^([^\]]+)\]:\s*(.*)$")
INLINE_FOOTNOTE_RE = re.compile(r"\[\^([^\]]+)\]")
INLINE_MATH_RE = re.compile(r"(?<!\\)\$(?![\s$])(.+?)(?<!\\)\$(?!\d)")
DISPLAY_MATH_FENCE_RE = re.compile(r"^\s*\$\$\s*$")
FENCE_RE = re.compile(r"^\s*(```+|~~~+)")
HEADING_RE = re.compile(r"<h([1-6])([^>]*)>(.*?)</h\1>", re.DOTALL | re.IGNORECASE)
BLOCKED_RAW_HTML_TAGS = {"script", "style", "iframe", "object", "embed", "form", "meta", "link", "base"}
SAFE_RAW_HTML_TAGS = {
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "caption",
    "cite",
    "code",
    "col",
    "colgroup",
    "dd",
    "del",
    "details",
    "div",
    "dl",
    "dt",
    "em",
    "figcaption",
    "figure",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "ins",
    "kbd",
    "li",
    "mark",
    "ol",
    "p",
    "pre",
    "s",
    "section",
    "small",
    "span",
    "strong",
    "sub",
    "summary",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}
GLOBAL_SAFE_ATTRS = {
    "class",
    "id",
    "dir",
    "lang",
    "title",
    "role",
    "aria-label",
    "aria-describedby",
    "aria-labelledby",
    "aria-hidden",
    "data-lang",
    "data-line-start",
    "data-lines",
    "data-source-line",
    "data-md2pdf-columns",
    "data-md2pdf-direction-profile",
    "data-md2pdf-number-profile",
    "data-md2pdf-rows",
    "data-md2pdf-label",
    "data-md2pdf-reference",
    "data-md2pdf-reference-kind",
    "data-md2pdf-reference-number",
    "data-md2pdf-reference-lang",
    "data-md2pdf-citation-mode",
    "data-md2pdf-citation-items",
    "data-md2pdf-citation-original",
    "data-md2pdf-citation-key",
    "data-md2pdf-bibliography-key",
}
TAG_SAFE_ATTRS = {
    "a": {"href", "name", "target", "rel"},
    "img": {"src", "alt", "width", "height"},
    "th": {"align", "colspan", "rowspan", "scope"},
    "td": {"align", "colspan", "rowspan"},
    "ol": {"start", "type"},
    "ul": {"type"},
    "code": {"class"},
}
SAFE_URL_SCHEMES = {"", "http", "https", "mailto", "data"}
SAFE_DATA_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "image/avif"}
MAX_EMBED_IMAGE_BYTES = 20 * 1024 * 1024
MAX_FRONTMATTER_DEPTH = 16
MAX_FRONTMATTER_NODES = 2048
MAX_FRONTMATTER_SCALAR_CHARS = 256 * 1024
TRANSPARENT_IMAGE_DATA_URI = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
RTL_LANG_PREFIXES = ("ar", "fa", "he", "iw", "ku", "ps", "sd", "ug", "ur", "yi")


class MarkdownInputError(ValueError):
    """Raised when Markdown metadata or document structure is invalid or unsafe."""


def normalize_language(value: Any, fallback: str = "auto") -> str:
    """Return a compact BCP-47-ish language code used for UI labels.

    The converter only needs the primary subtag for built-in labels such as the
    table-of-contents title and callout captions. Unknown or empty values are
    kept as ``fallback`` so direction detection can still infer a sensible
    default from the actual Markdown body.
    """
    text = str(value or "").strip().replace("_", "-").lower()
    return text or fallback


def is_rtl_language(lang: str | None) -> bool:
    return normalize_language(lang, "").startswith(RTL_LANG_PREFIXES)


def language_family(lang: str | None, text_hint: str = "") -> str:
    """Choose ``fa`` or ``en`` for bundled UI strings.

    Persian is used for RTL languages and Persian-dominant documents. English is
    used for explicit English metadata and for LTR/Latin-dominant documents.
    """
    normalized = normalize_language(lang, "auto")
    if normalized.startswith("en"):
        return "en"
    if is_rtl_language(normalized):
        return "fa"
    if normalized not in {"", "auto", "und"}:
        return "en"
    return "fa" if dominant_direction(text_hint) == "rtl" else "en"


def ui_label(key: str, *, lang: str | None = None, text_hint: str = "") -> str:
    labels = {
        "fa": {
            "toc_title": "فهرست مطالب",
            "toc_aria": "فهرست مطالب",
            "callout_note": "نکته",
            "callout_tip": "پیشنهاد",
            "callout_important": "مهم",
            "callout_warning": "هشدار",
            "callout_caution": "احتیاط",
            "callout_info": "اطلاعات",
            "callout_success": "موفقیت",
            "callout_question": "پرسش",
            "callout_failure": "خطا",
            "callout_danger": "خطر",
            "callout_bug": "اشکال",
            "callout_example": "نمونه",
            "callout_quote": "نقل‌قول",
            "callout_abstract": "خلاصه",
            "footnote": "پانویس",
            "footnotes": "پانویس‌ها",
            "footnote_backref": "بازگشت به ارجاع",
            "caption_figure": "شکل",
            "caption_table": "جدول",
            "caption_code": "کد",
            "caption_diagram": "نمودار",
            "caption_equation": "معادله",
            "bibliography_title": "منابع",
        },
        "en": {
            "toc_title": "Table of Contents",
            "toc_aria": "Table of contents",
            "callout_note": "Note",
            "callout_tip": "Tip",
            "callout_important": "Important",
            "callout_warning": "Warning",
            "callout_caution": "Caution",
            "callout_info": "Info",
            "callout_success": "Success",
            "callout_question": "Question",
            "callout_failure": "Failure",
            "callout_danger": "Danger",
            "callout_bug": "Bug",
            "callout_example": "Example",
            "callout_quote": "Quote",
            "callout_abstract": "Abstract",
            "footnote": "Footnote",
            "footnotes": "Footnotes",
            "footnote_backref": "Back to reference",
            "caption_figure": "Figure",
            "caption_table": "Table",
            "caption_code": "Listing",
            "caption_diagram": "Diagram",
            "caption_equation": "Equation",
            "bibliography_title": "References",
        },
    }
    family = language_family(lang, text_hint)
    return labels[family].get(key, labels["en"].get(key, key))


@dataclass(slots=True)
class MarkdownRenderResult:
    body_html: str
    metadata: dict[str, Any] = field(default_factory=dict)
    title: str = "Document"
    pygments_css: str = ""
    toc_html: str = ""
    toc_entries: list[tuple[int, str, str, str]] = field(default_factory=list)
    reference_lists_html: str = ""
    reference_objects: tuple[dict[str, object], ...] = ()
    bibliography_html: str = ""
    bibliography_sources: tuple[Path, ...] = ()
    citation_entries: tuple[dict[str, object], ...] = ()
    cited_keys: tuple[str, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    source_map: tuple[dict[str, object], ...] = ()


@dataclass(slots=True)
class TocItem:
    level: int
    title: str
    heading_id: str
    number: str
    title_html: str = ""
    children: list["TocItem"] = field(default_factory=list)


class CodeHtmlFormatter(HtmlFormatter):
    """Pygments formatter. The Pygments style is selected by the resolved appearance."""

    def __init__(
        self,
        style: str = "github-dark",
        *,
        linenos: bool = False,
        hl_lines: list[int] | None = None,
        line_start: int = 1,
    ) -> None:
        super().__init__(
            style=style,
            cssclass="codehilite",
            nowrap=False,
            linenos="table" if linenos else False,
            linenostart=max(1, int(line_start or 1)),
            hl_lines=hl_lines or [],
        )


HIGHLIGHT_TRAILING_NEWLINE_RE = re.compile(
    r'(<span class="hll">.*?)(\r?\n)(</span>)',
    re.DOTALL,
)
# Private-use parser sentinels; these are not credentials.
PROTECTED_CODE_TOKEN_PREFIX = "\ue000FOLIOCODE"  # nosec B105
PROTECTED_CODE_TOKEN_SUFFIX = "\ue001"  # nosec B105


def _normalize_highlight_line_breaks(highlighted_html: str) -> str:
    """Keep Pygments highlighted-line wrappers from swallowing the next line's indent.

    Pygments emits highlighted lines as ``<span class="hll">...\n</span>``.
    When print CSS turns that wrapper into a full-width highlight strip, the
    following line's leading spaces can visually attach to the highlighted inline
    box and disappear at the start of the next code row. Moving the line break
    outside the wrapper preserves the logical code text while keeping the
    highlighter scoped to a single physical line.
    """
    return HIGHLIGHT_TRAILING_NEWLINE_RE.sub(r"\1\3\2", highlighted_html)


def _validate_frontmatter_graph(value: Any) -> None:
    """Reject recursive or excessively amplified YAML object graphs."""
    node_count = 0
    scalar_chars = 0
    active: set[int] = set()

    def visit(item: Any, depth: int) -> None:
        nonlocal node_count, scalar_chars
        node_count += 1
        if node_count > MAX_FRONTMATTER_NODES:
            raise MarkdownInputError(
                f"Front matter exceeds the {MAX_FRONTMATTER_NODES}-item complexity limit."
            )
        if depth > MAX_FRONTMATTER_DEPTH:
            raise MarkdownInputError(
                f"Front matter exceeds the maximum nesting depth of {MAX_FRONTMATTER_DEPTH}."
            )

        if isinstance(item, dict):
            identity = id(item)
            if identity in active:
                raise MarkdownInputError("Front matter contains a recursive YAML alias.")
            active.add(identity)
            try:
                for key, child in item.items():
                    visit(key, depth + 1)
                    visit(child, depth + 1)
            finally:
                active.remove(identity)
            return
        if isinstance(item, (list, tuple, set)):
            identity = id(item)
            if identity in active:
                raise MarkdownInputError("Front matter contains a recursive YAML alias.")
            active.add(identity)
            try:
                for child in item:
                    visit(child, depth + 1)
            finally:
                active.remove(identity)
            return

        scalar_chars += len(str(item))
        if scalar_chars > MAX_FRONTMATTER_SCALAR_CHARS:
            raise MarkdownInputError(
                "Front matter scalar content exceeds the supported size limit."
            )

    visit(value, 0)


def extract_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw = match.group(1)
    body = text[match.end() :]
    if yaml is None:
        return {}, body
    try:
        data = yaml.safe_load(raw) or {}
    except Exception as exc:
        problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        mark = getattr(exc, "problem_mark", None)
        location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise MarkdownInputError(f"Invalid YAML front matter{location}: {problem}") from exc
    if not isinstance(data, dict):
        raise MarkdownInputError("YAML front matter must contain a mapping/object at the top level.")
    _validate_frontmatter_graph(data)
    return data, body


def guess_title(markdown: str, metadata: dict[str, Any]) -> str:
    meta_title = metadata.get("title")
    if meta_title:
        return str(meta_title)
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line[2:].strip(" #\t") or "Document"
    return "Document"


def has_persian(text: str) -> bool:
    return bool(ARABIC_RANGES.search(text or ""))


def has_latin(text: str) -> bool:
    return bool(LATIN_RANGES.search(text or ""))


def dominant_direction(text: str) -> str:
    """Return rtl/ltr/auto by scanning the first strong directional character."""
    for char in text:
        direction = unicodedata.bidirectional(char)
        if direction in {"R", "AL"}:
            return "rtl"
        if direction == "L":
            return "ltr"
    return "auto"



ASCII_DIGIT_RE = re.compile(r"[0-9]")
ARABIC_DIGIT_RE = re.compile(r"[\u0660-\u0669\u06F0-\u06F9]")
PERSIAN_PUNCTUATION_RE = re.compile(r"[،؛؟]")
ASCII_RTL_PUNCTUATION_RE = re.compile(r"[?,;](?=\s|$)")
PERSIAN_CAPTION_PREFIX_RE = re.compile(r"^(?:شکل|تصویر|جدول|کد|نمودار)\b")
PERSIAN_DIGIT_TRANSLATION = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
LTR_ISOLATE_RUN_RE = re.compile(
    r"(?<![\w@])"
    r"(?P<run>"
    r"(?:[A-Za-z][A-Za-z0-9]*(?:[._:/-][A-Za-z0-9]+)*"
    r"|[0-9]+(?:[._:/-][A-Za-z0-9]+)+)"
    r"(?:\s+(?:[A-Za-z][A-Za-z0-9]*(?:[._:/-][A-Za-z0-9]+)*"
    r"|[0-9]+(?:[._:/-][A-Za-z0-9]+)+))*"
    r")"
    r"(?P<punct>[.,:;!?])?"
)
LTR_ISOLATE_SKIP_TAGS = {"a", "code", "kbd", "pre", "samp", "script", "style", "textarea"}
LTR_ISOLATE_SKIP_CLASSES = {"math", "math-inline", "math-display", "mjx-container"}
LTR_ISOLATE_CONTEXT_TAGS = {"p", "li", "td", "th", "caption", "figcaption", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}


def strong_direction_counts(text: str) -> tuple[int, int]:
    """Return ``(rtl, ltr)`` strong-character counts for bidi-sensitive text.

    ``dir=auto`` is useful for paragraphs, but tables, captions, and mixed
    Persian/English technical prose need more stable CSS hooks. Counting strong
    directional characters gives the renderer a deterministic profile without
    rewriting the author's text.
    """
    rtl = 0
    ltr = 0
    for char in text or "":
        direction = unicodedata.bidirectional(char)
        if direction in {"R", "AL"}:
            rtl += 1
        elif direction == "L":
            ltr += 1
    return rtl, ltr


def direction_profile(text: str) -> str:
    """Classify text as ``rtl``, ``ltr``, ``mixed``, or ``neutral``."""
    rtl, ltr = strong_direction_counts(text)
    if rtl and ltr:
        return "mixed"
    if rtl:
        return "rtl"
    if ltr:
        return "ltr"
    return "neutral"


def mixed_text_direction(text: str, *, lang: str | None = None) -> str:
    """Return a concrete direction for mixed-script prose.

    ``dir=auto`` is usually fine for ordinary paragraphs, but mixed Persian/Latin
    table cells often start with a Latin technical token or inherit an LTR table
    direction. In those cases Chromium lays the whole Persian sentence out as if
    it were LTR. This helper keeps pure LTR/RTL text unchanged and gives Persian
    mixed prose an explicit RTL base direction while preserving isolated Latin
    identifiers inside the cell.
    """
    profile = direction_profile(text)
    if profile in {"rtl", "ltr"}:
        return profile
    if profile == "neutral":
        return "auto"

    rtl, ltr = strong_direction_counts(text)
    family = language_family(lang, text)
    if has_persian(text) and family == "fa":
        return "rtl"
    if rtl > ltr:
        return "rtl"
    if ltr > rtl:
        return "ltr"
    return "rtl" if family == "fa" else "ltr"


def has_mixed_numerals(text: str) -> bool:
    """Return whether Persian/Arabic and ASCII digits appear together."""
    return bool(ASCII_DIGIT_RE.search(text or "") and ARABIC_DIGIT_RE.search(text or ""))


def numeral_profile(text: str) -> str:
    """Classify digit usage for Persian/Latin number rendering hooks."""
    has_ascii = bool(ASCII_DIGIT_RE.search(text or ""))
    has_arabic = bool(ARABIC_DIGIT_RE.search(text or ""))
    if has_ascii and has_arabic:
        return "mixed"
    if has_arabic:
        return "persian"
    if has_ascii:
        return "latin"
    return "none"


def has_persian_punctuation(text: str) -> bool:
    """Return whether Persian punctuation marks are present."""
    return bool(PERSIAN_PUNCTUATION_RE.search(text or ""))


def has_ascii_rtl_punctuation(text: str) -> bool:
    """Return whether ASCII punctuation appears inside an RTL-dominant string."""
    if not ASCII_RTL_PUNCTUATION_RE.search(text or ""):
        return False
    rtl, ltr = strong_direction_counts(text)
    return rtl > 0 and rtl >= ltr


def localize_digits(value: Any, *, lang: str | None = None, text_hint: str = "") -> str:
    """Return ``value`` with ASCII digits shaped for Persian UI labels when appropriate.

    The renderer does not rewrite author prose. This helper is reserved for
    generated navigation and reference labels such as TOC section numbers and
    footnote markers where the converter owns the number text.
    """
    text = str(value)
    if language_family(lang, text_hint) == "fa":
        return text.translate(PERSIAN_DIGIT_TRANSLATION)
    return text


def localized_number_class(value: Any, *, lang: str | None = None, text_hint: str = "") -> str:
    """Return a stable class for generated localized number labels."""
    return "persian-generated-number" if language_family(lang, text_hint) == "fa" else "latin-generated-number"


def text_quality_classes(text: str) -> list[str]:
    """Return stable CSS hooks for bidi, numeral, and punctuation quality."""
    profile = direction_profile(text)
    classes: list[str] = []
    direction_class = {
        "rtl": "md2pdf-rtl-text",
        "ltr": "md2pdf-ltr-text",
        "mixed": "mixed-script",
    }.get(profile)
    if direction_class:
        classes.append(direction_class)
    if has_persian(text) and has_latin(text):
        classes.append("mixed-script")

    digits = numeral_profile(text)
    if digits == "mixed":
        classes.append("mixed-numeral")
    elif digits == "persian":
        classes.append("persian-numeral")
    elif digits == "latin":
        classes.append("latin-numeral")

    if has_persian_punctuation(text):
        classes.append("persian-punctuation")
    if has_ascii_rtl_punctuation(text):
        classes.append("rtl-ascii-punctuation")
    return sorted(set(classes))


def _add_classes(tag: Tag, *classes: str) -> None:
    existing = set(tag.get("class", []))
    existing.update(item for item in classes if item)
    if existing:
        tag["class"] = sorted(existing)


def _parent_chain(tag: Tag | None) -> list[Tag]:
    chain: list[Tag] = []
    current = tag
    while isinstance(current, Tag):
        chain.append(current)
        current = current.parent if isinstance(current.parent, Tag) else None
    return chain


def _inside_tag(tag: Tag | None, names: set[str]) -> bool:
    return any((ancestor.name or "").lower() in names for ancestor in _parent_chain(tag))


def _inside_class(tag: Tag | None, classes: set[str]) -> bool:
    for ancestor in _parent_chain(tag):
        ancestor_classes = {str(item) for item in ancestor.get("class", [])}
        if ancestor_classes & classes:
            return True
    return False


def _mixed_script_context(tag: Tag | None) -> bool:
    for ancestor in _parent_chain(tag):
        name = (ancestor.name or "").lower()
        if name in LTR_ISOLATE_CONTEXT_TAGS:
            text = ancestor.get_text(" ", strip=True)
            if has_persian(text) and has_latin(text):
                return True
            classes = set(ancestor.get("class", []))
            if "md2pdf-rtl-text" in classes or "mixed-script" in classes:
                return True
            direction = str(ancestor.get("dir") or "").lower()
            if direction == "rtl" and has_latin(text):
                return True
            return False
    return False


def _new_ltr_isolate_span(soup: BeautifulSoup, text: str, *, has_trailing_punctuation: bool = False) -> Tag:
    span = soup.new_tag("span")
    classes = ["md2pdf-ltr-isolate"]
    if has_trailing_punctuation:
        classes.append("md2pdf-ltr-isolate--punct")
    span["class"] = classes
    span["dir"] = "ltr"
    span["lang"] = "en"
    span.string = text
    return span


def _next_meaningful_sibling(tag: Tag) -> Tag | None:
    sibling = tag.next_sibling
    while isinstance(sibling, NavigableString) and not str(sibling).strip():
        sibling = sibling.next_sibling
    return sibling if isinstance(sibling, Tag) else None


def _group_ltr_isolate_footnote_refs(soup: BeautifulSoup) -> None:
    for span in list(soup.find_all("span", class_=lambda c: c and "md2pdf-ltr-isolate--punct" in c)):
        if span.parent and "md2pdf-ltr-isolate-group" in span.parent.get("class", []):
            continue
        sibling = _next_meaningful_sibling(span)
        if not sibling or sibling.name != "sup" or "footnote-ref" not in sibling.get("class", []):
            continue
        wrapper = soup.new_tag("span")
        wrapper["class"] = ["md2pdf-ltr-isolate-group", "md2pdf-ltr-isolate-group--footnote"]
        wrapper["dir"] = "ltr"
        wrapper["lang"] = "en"
        span.wrap(wrapper)
        wrapper.append(sibling.extract())


def isolate_ltr_runs_in_mixed_persian_text(soup: BeautifulSoup) -> None:
    """Wrap Latin technical runs inside Persian prose with bidi isolation spans.

    Chromium's bidi handling is generally reliable for full blocks, but short
    Latin identifiers followed by neutral punctuation can still drift visually in
    Persian paragraphs. This pass keeps author text unchanged while adding an
    inline isolation boundary around Latin/version-like runs and their immediate
    ASCII punctuation. Code, math, preformatted content, and links are skipped so
    semantic Markdown constructs keep their original structure.
    """
    for node in list(soup.find_all(string=True)):
        parent = node.parent if isinstance(node.parent, Tag) else None
        if (
            parent is None
            or _inside_tag(parent, LTR_ISOLATE_SKIP_TAGS)
            or _inside_class(parent, LTR_ISOLATE_SKIP_CLASSES)
        ):
            continue
        text = str(node)
        if not text.strip() or not has_latin(text):
            continue
        if not _mixed_script_context(parent):
            continue

        parts: list[str | Tag] = []
        pos = 0
        changed = False
        for match in LTR_ISOLATE_RUN_RE.finditer(text):
            run = match.group("run") or ""
            punct = match.group("punct") or ""
            if not has_latin(run):
                continue
            start, end = match.span()
            if start > pos:
                parts.append(text[pos:start])
            isolated = run + punct
            parts.append(_new_ltr_isolate_span(soup, isolated, has_trailing_punctuation=bool(punct)))
            pos = end
            changed = True
        if not changed:
            continue
        if pos < len(text):
            parts.append(text[pos:])

        for fragment in reversed(parts):
            if isinstance(fragment, str):
                if fragment:
                    node.insert_after(NavigableString(fragment))
            else:
                node.insert_after(fragment)
        node.extract()

    _group_ltr_isolate_footnote_refs(soup)


CALLOUT_KIND_ALIASES = {
    "NOTE": "note",
    "INFO": "info",
    "TODO": "info",
    "TIP": "tip",
    "HINT": "tip",
    "IMPORTANT": "important",
    "WARNING": "warning",
    "WARN": "warning",
    "CAUTION": "caution",
    "ATTENTION": "caution",
    "SUCCESS": "success",
    "CHECK": "success",
    "DONE": "success",
    "QUESTION": "question",
    "HELP": "question",
    "FAQ": "question",
    "FAILURE": "failure",
    "FAIL": "failure",
    "MISSING": "failure",
    "DANGER": "danger",
    "ERROR": "danger",
    "BUG": "bug",
    "EXAMPLE": "example",
    "QUOTE": "quote",
    "CITE": "quote",
    "ABSTRACT": "abstract",
    "SUMMARY": "abstract",
    "TLDR": "abstract",
}

CALLOUT_MARKER_RE = re.compile(
    r"^\[!(?P<kind>[A-Z][A-Z0-9_-]*)\](?P<fold>[+-])?\s*(?P<title>.*)$",
    re.I,
)


def normalize_github_callouts(soup: BeautifulSoup, *, lang: str | None = None) -> None:
    """Convert GitHub/Obsidian blockquote callouts before bidi isolation.

    The Persian mixed-script isolation pass wraps Latin tokens in inline spans.
    When that pass runs before callout normalization, markers such as
    ``[!NOTE]`` become ``[!<span>NOTE</span>]`` and no longer match the raw
    marker regex.  Normalizing callouts first keeps the marker structural and
    prevents raw ``[!NOTE]`` / ``[!IMPORTANT]`` text from leaking into PDFs.
    """
    text_hint = soup.get_text(" ", strip=True)
    callout_titles = {
        canonical: ui_label(f"callout_{canonical}", lang=lang, text_hint=text_hint)
        for canonical in sorted(set(CALLOUT_KIND_ALIASES.values()))
    }

    for blockquote in soup.find_all("blockquote"):
        first_p = blockquote.find("p")
        if not first_p:
            continue
        text = first_p.get_text("\n", strip=True)
        first_line, _, remainder = text.partition("\n")
        match = CALLOUT_MARKER_RE.match(first_line.strip())
        if not match:
            continue
        raw_kind = match.group("kind").upper().replace("-", "_")
        canonical = CALLOUT_KIND_ALIASES.get(raw_kind)
        if not canonical:
            continue
        custom_title = match.group("title").strip()
        classes = set(blockquote.get("class", []))
        classes.update({"callout", f"callout-{canonical}"})
        if match.group("fold"):
            classes.add("callout-foldable")
        blockquote["class"] = sorted(classes)
        title_tag = soup.new_tag("strong")
        title_tag["class"] = "callout-title"
        title_tag.string = custom_title or callout_titles.get(canonical, canonical.title())
        first_p.clear()
        first_p.append(title_tag)
        if remainder.strip():
            first_p.append("\n" + remainder.strip())


def _dir_for_profile(profile: str) -> str:
    return profile if profile in {"rtl", "ltr"} else "auto"



CODE_FENCE_TITLE_RE = re.compile(r"(?:^|\s)(?:title|filename|file)=(?P<quote>[\"\'])(?P<value>.*?)(?P=quote)")
CODE_FENCE_BRACE_RE = re.compile(r"\{(?P<spec>[^}]*)\}")
CODE_FENCE_KV_RE = re.compile(
    r"(?P<key>[A-Za-z][\w-]*)\s*=\s*"
    r"(?:(?P<quote>[\"'])(?P<quoted>.*?)(?P=quote)|(?P<bare>[^\s}]+))"
)
CODE_FENCE_ATTR_CLASS_RE = re.compile(r"(?<!\S)\.(?P<class>[A-Za-z_][\w.-]*)")
CODE_FENCE_LABEL_RE = re.compile(
    r"(?:^|[\s{])#(?P<label>(?:fig|tbl|eq|lst):[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?)(?=[\s}]|$)"
)
CODE_FENCE_LABEL_CANDIDATE_RE = re.compile(
    r"(?:^|[\s{])#(?P<label>(?:fig|tbl|eq|lst):[^\s}]*)"
)
CODE_FENCE_LABEL_VALUE_RE = re.compile(
    r"^(?:fig|tbl|eq|lst):[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?$"
)
CODE_FENCE_TITLE_KEYS = {"title", "filename", "file", "caption", "name"}
CODE_FENCE_HIGHLIGHT_KEYS = {
    "hl_lines",
    "hl-lines",
    "highlight",
    "line-highlight",
    "lines",
    "emphasize-lines",
}
CODE_FENCE_LINE_NUMBER_KEYS = {
    "linenos",
    "line-numbers",
    "linenumbers",
    "numbered",
    "numberlines",
    "lineNumbers",
}
CODE_FENCE_LINE_START_KEYS = {
    "start",
    "startline",
    "start-line",
    "line-start",
    "linenostart",
    "lineno-start",
    "first-line",
}
CODE_FENCE_LINE_NUMBER_CLASSES = {
    "linenos",
    "line-numbers",
    "linenumbers",
    "numbered",
    "numberlines",
    "numberLines",
}
CODE_FENCE_LINE_NUMBER_KEY_SET = {item.lower() for item in CODE_FENCE_LINE_NUMBER_KEYS}
CODE_FENCE_LINE_START_KEY_SET = {item.lower() for item in CODE_FENCE_LINE_START_KEYS}
CODE_FENCE_LANGUAGE_ALIASES = {
    "mmd": "mermaid",
    "py": "python",
    "js": "javascript",
    "ts": "typescript",
    "sh": "bash",
    "shell": "bash",
    "zsh": "bash",
    "md": "markdown",
    "yml": "yaml",
}


def _parse_line_highlights(spec: str | None) -> list[int]:
    if not spec:
        return []
    values: set[int] = set()
    cleaned = str(spec).strip().strip("{}[]()\"'").replace(";", ",")
    for part in re.split(r"[,\s]+", cleaned):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            start_text, end_text = [chunk.strip() for chunk in part.split('-', 1)]
            if start_text.isdigit() and end_text.isdigit():
                start, end = int(start_text), int(end_text)
                if start > 0 and end >= start:
                    values.update(range(start, end + 1))
            continue
        if part.isdigit() and int(part) > 0:
            values.add(int(part))
    return sorted(values)


def _normalize_code_language(value: str | None) -> str:
    language = (value or "").strip().strip(".").lower()
    return CODE_FENCE_LANGUAGE_ALIASES.get(language, language)


def _parse_code_fence_key_values(attrs: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for match in CODE_FENCE_KV_RE.finditer(attrs or ""):
        key = match.group("key").strip()
        value = match.group("quoted") if match.group("quote") else match.group("bare")
        values[key] = (value or "").strip()
    return values


def _truthy_attr_value(value: str | None) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() not in {"", "0", "false", "no", "off", "none"}


def _positive_int_attr(value: str | None, *, fallback: int = 1) -> int:
    try:
        parsed = int(str(value or "").strip())
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _first_language_class(attrs: str) -> str:
    for match in CODE_FENCE_ATTR_CLASS_RE.finditer(attrs or ""):
        name = match.group("class")
        if name in CODE_FENCE_LINE_NUMBER_CLASSES:
            continue
        if name.startswith("language-"):
            return _normalize_code_language(name.removeprefix("language-"))
        return _normalize_code_language(name)
    return ""


def parse_code_fence_info(info: str | None) -> dict[str, Any]:
    """Parse documentation-style fenced code metadata.

    The parser accepts the common variants used by GitHub, MkDocs, Pandoc,
    Quarto, and documentation generators, for example::

        ```python title="renderer.py" {2,5-6} linenos
        ```{.python .numberLines hl_lines="2 5-6" title=renderer.py}

    Unknown attributes are intentionally preserved in ``attrs`` but ignored by
    the renderer so future syntax can be added without breaking existing input.
    """
    text = (info or "").strip()
    language = ""
    attrs = ""

    if text.startswith("{"):
        match = CODE_FENCE_BRACE_RE.match(text)
        if match:
            attrs = match.group("spec").strip()
            remainder = text[match.end() :].strip()
            if remainder:
                attrs = f"{attrs} {remainder}".strip()
            language = _first_language_class(attrs)
        else:
            attrs = text
    else:
        parts = text.split(maxsplit=1)
        if parts:
            language = _normalize_code_language(parts[0])
        attrs = parts[1] if len(parts) > 1 else ""
        brace_language = _first_language_class(attrs)
        if not language and brace_language:
            language = brace_language

    kv = _parse_code_fence_key_values(attrs)

    title = ""
    for key, value in kv.items():
        if key.lower() in CODE_FENCE_TITLE_KEYS:
            title = value
            break

    highlight_values: list[int] = []
    for brace_match in CODE_FENCE_BRACE_RE.finditer(attrs):
        spec = brace_match.group("spec")
        if re.fullmatch(r"[0-9,;\-\s]+", spec.strip()):
            highlight_values.extend(_parse_line_highlights(spec))
    for key, value in kv.items():
        if key.lower() in CODE_FENCE_HIGHLIGHT_KEYS:
            highlight_values.extend(_parse_line_highlights(value))

    attrs_lower = attrs.lower()
    linenos = bool(
        re.search(
            r"(?:^|\s)(?:linenos|line-numbers|numbered|numberlines|lineNumbers)(?:\s|$)",
            attrs,
            re.I,
        )
        or any(f".{name.lower()}" in attrs_lower for name in CODE_FENCE_LINE_NUMBER_CLASSES)
        or any(
            key.lower() in CODE_FENCE_LINE_NUMBER_KEY_SET and _truthy_attr_value(value)
            for key, value in kv.items()
        )
    )

    line_start = 1
    for key, value in kv.items():
        if key.lower() in CODE_FENCE_LINE_START_KEY_SET:
            line_start = _positive_int_attr(value, fallback=1)
            break

    reference_labels = list(
        dict.fromkeys(match.group("label") for match in CODE_FENCE_LABEL_RE.finditer(attrs))
    )
    reference_label = reference_labels[0] if reference_labels else ""
    invalid_reference_label = ""
    for candidate_match in CODE_FENCE_LABEL_CANDIDATE_RE.finditer(attrs):
        candidate = candidate_match.group("label")
        if not CODE_FENCE_LABEL_VALUE_RE.fullmatch(candidate):
            invalid_reference_label = candidate
            break

    return {
        "language": language,
        "title": title,
        "reference_label": reference_label,
        "reference_labels": reference_labels,
        "invalid_reference_label": invalid_reference_label,
        "linenos": linenos,
        "highlight_lines": sorted(set(highlight_values)),
        "line_start": line_start,
        "attrs": attrs,
    }


def highlight_code(
    code: str,
    lang: str | None,
    attrs: str | None = None,
    *,
    code_style: str = "github-dark",
    caption: str | None = None,
    extra_classes: str = "",
    linenos: bool = False,
    highlight_lines: list[int] | None = None,
    line_start: int = 1,
    reference_label: str | None = None,
) -> str:
    parts = (lang or "").strip().split()
    language = parts[0] if parts else ""
    label = language or "text"
    try:
        lexer = get_lexer_by_name(language, stripall=False) if language else TextLexer(stripall=False)
    except ClassNotFound:
        lexer = TextLexer(stripall=False)
        label = language or "text"
    normalized_highlight_lines = highlight_lines or []
    if line_start > 1 and normalized_highlight_lines and all(
        line >= line_start for line in normalized_highlight_lines
    ):
        normalized_highlight_lines = [line - line_start + 1 for line in normalized_highlight_lines]
    formatter = CodeHtmlFormatter(
        code_style,
        linenos=linenos,
        hl_lines=normalized_highlight_lines,
        line_start=line_start,
    )
    highlighted = _normalize_highlight_line_breaks(highlight(code, lexer, formatter))
    caption_value = caption if caption not in (None, "") else label.upper()
    caption_html = (
        '<figcaption class="md2pdf-caption md2pdf-caption--code" dir="auto">'
        f'{html.escape(caption_value)}'
        '</figcaption>'
        if caption_value
        else ""
    )
    line_count = max(1, len(code.rstrip("\n").splitlines()))
    extra_attrs = f" data-lang=\"{html.escape(language)}\"" if language else ""
    if reference_label:
        extra_attrs += f" data-md2pdf-label=\"{html.escape(reference_label)}\""
    extra_attrs += f" data-lines=\"{line_count}\""
    if linenos and line_start > 1:
        extra_attrs += f" data-line-start=\"{line_start}\""
    classes = "code-block" + (f" {html.escape(extra_classes)}" if extra_classes else "")
    if has_persian(code):
        classes += " code-block--rtl-script"
    if has_persian(code) and has_latin(code):
        classes += " code-block--mixed-script"
    if linenos:
        classes += " code-block--numbered"
    if highlight_lines:
        classes += " code-block--highlighted"
    if line_count >= 18:
        classes += " code-block--medium"
    if line_count >= 36:
        classes += " code-block--long"
    if line_count >= 90:
        classes += " code-block--very-long"
    return (
        f'<figure class="{classes}" dir="ltr"{extra_attrs}>'
        f"{caption_html}"
        f"{highlighted}"
        f"</figure>"
    )



def mermaid_placeholder(
    code: str,
    caption: str | None = None,
    reference_label: str | None = None,
) -> str:
    """Keep Mermaid source safe until post-processing renders it as SVG."""
    escaped = html.escape(code.rstrip("\n"))
    caption_text = html.escape((caption or "MERMAID").strip() or "MERMAID")
    label_attr = (
        f' data-md2pdf-label="{html.escape(reference_label)}"' if reference_label else ""
    )
    return (
        f'<figure class="mermaid-diagram mermaid-diagram--pending" dir="ltr"{label_attr}>'
        '<figcaption class="md2pdf-caption md2pdf-caption--diagram" dir="auto">'
        f'{caption_text}'
        '</figcaption>'
        '<pre><code class="language-mermaid">'
        f"{escaped}"
        '</code></pre>'
        '</figure>'
    )


def is_mermaid_language(value: str | None) -> bool:
    parts = (value or "").strip().split(maxsplit=1)
    language = parts[0].lower() if parts else ""
    return language in {"mermaid", "mmd"}


def _svg_viewbox_size(svg_tag) -> tuple[float, float] | None:
    """Return SVG viewBox dimensions when they are available."""
    viewbox = svg_tag.get("viewBox") or svg_tag.get("viewbox") or ""
    parts = str(viewbox).replace(",", " ").split()
    if len(parts) != 4:
        return None
    try:
        width = float(parts[2])
        height = float(parts[3])
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _classify_mermaid_svg(svg_tag) -> list[str]:
    """Classify generated Mermaid diagrams for print-friendly scaling."""
    size = _svg_viewbox_size(svg_tag)
    if size is None:
        return []
    width, height = size
    aspect = width / height
    classes: list[str] = []
    if aspect < 0.72 or height >= 900:
        classes.append("mermaid-diagram--tall")
    if aspect > 2.4 or width >= 1200:
        classes.append("mermaid-diagram--wide")
    return classes


def render_mermaid_placeholders(soup: BeautifulSoup) -> None:
    """Replace Mermaid placeholder code blocks with generated SVG diagrams."""
    for figure in soup.find_all("figure", class_=lambda c: c and "mermaid-diagram" in c):
        code_tag = figure.find("code", class_=lambda c: c and "language-mermaid" in c)
        if code_tag is None:
            continue
        source = code_tag.get_text()
        svg = render_mermaid_to_svg(source)
        if not svg:
            figure["class"] = list(set(figure.get("class", []) + ["mermaid-diagram--fallback"]))
            continue
        # Parse the generated SVG with the built-in HTML parser instead of
        # BeautifulSoup's ``xml`` feature. The ``xml`` feature requires lxml,
        # but lxml is intentionally not a runtime dependency for Mardas Folio.
        # ``html.parser`` is enough here because the SVG is generated by our
        # own offline Mermaid renderer, and keeping this dependency-free path
        # prevents fresh editable installs from crashing on Mermaid blocks.
        fragment = BeautifulSoup(svg, "html.parser")
        svg_tag = fragment.find("svg")
        if svg_tag is None:
            continue
        for layout_class in _classify_mermaid_svg(svg_tag):
            existing = set(figure.get("class", []))
            existing.add(layout_class)
            figure["class"] = sorted(existing)
        svg_tag["preserveAspectRatio"] = "xMidYMid meet"
        pre = figure.find("pre")
        if pre is not None:
            pre.replace_with(svg_tag)
        else:
            figure.append(svg_tag)
        classes = set(figure.get("class", []))
        classes.discard("mermaid-diagram--pending")
        classes.add("mermaid-diagram--rendered")
        figure["class"] = sorted(classes)

def guess_code_language(code: str) -> tuple[str, str]:
    """Best-effort language guess for indented Markdown code blocks.

    Fenced blocks already carry their language, but many reports use 4-space
    indented blocks. markdown-it emits those as plain ``<pre><code>`` nodes,
    so we infer a readable highlighter and caption here. The heuristic is
    deliberately conservative: when unsure, it returns plain text.
    """
    stripped = code.strip("\n")
    lowered = stripped.lower()
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    first = lines[0] if lines else ""

    if not stripped:
        return "text", ""
    if "#include" in stripped or re.search(r"\bpid_t\b|\bint\s+main\s*\(", stripped):
        return "c", "C"
    if re.search(r"^\s*#\s*define\s+SYS_", stripped, re.M) or "SYSCALL(" in stripped:
        return "c", "C"
    if re.search(r"\bdef\s+\w+\s*\(|\bimport\s+\w+|\bfrom\s+\w+\s+import\b", stripped):
        return "python", "PYTHON"
    if re.search(r"\bconst\s+\w+\s*=|\blet\s+\w+\s*=|console\.log\s*\(", stripped):
        return "javascript", "JAVASCRIPT"
    if re.search(r"^\s*</?[-a-zA-Z][^>]*>\s*$", stripped, re.M):
        return "html", "HTML"
    if re.search(r"^\s*(make|gdb|qemu|cat|dice|ksort|usort|pidtest|ptest|makenums)(\s|$)", stripped, re.M):
        return "bash", "BASH"
    if re.search(r"^\s*\(gdb\)\s+", stripped, re.M):
        return "bash", "GDB"
    if first.startswith("# terminal") or "inside xv6" in lowered:
        return "bash", "BASH"
    if re.search(r"^\s*#\d+\s+\w+", stripped, re.M):
        return "text", "TRACE"
    if re.fullmatch(r"[-+*/=()0-9A-Za-z_\s.]+", stripped) and any(ch.isdigit() for ch in stripped):
        return "text", ""
    return "text", ""


def _replace_outside_inline_code(
    text: str,
    pattern: re.Pattern[str],
    repl: Any,
) -> str:
    """Apply a regex replacement only outside Markdown inline code spans.

    The Markdown parser will later turn backtick-delimited spans into ``<code>``.
    Pre-processing steps such as math and footnote expansion must therefore leave
    literal examples like ``$x$`` and ``[^note]`` untouched. This lightweight
    scanner follows the common Markdown rule that a code span opens with one or
    more backticks and closes with the same run length on the same line.
    """
    output: list[str] = []
    index = 0
    while index < len(text):
        marker_match = re.search(r"`+", text[index:])
        if not marker_match:
            output.append(pattern.sub(repl, text[index:]))
            break

        start = index + marker_match.start()
        marker = marker_match.group(0)
        output.append(pattern.sub(repl, text[index:start]))

        content_start = start + len(marker)
        close = text.find(marker, content_start)
        if close == -1:
            output.append(pattern.sub(repl, text[start:]))
            break

        output.append(text[start : close + len(marker)])
        index = close + len(marker)
    return "".join(output)


def _protected_code_token(index: int) -> str:
    return f"{PROTECTED_CODE_TOKEN_PREFIX}{index:08d}{PROTECTED_CODE_TOKEN_SUFFIX}"


def _protect_code_regions(markdown: str) -> tuple[str, list[str]]:
    """Protect fenced, indented, and multiline inline code before preprocessing."""
    protected: list[str] = []

    def store(value: str) -> str:
        token = _protected_code_token(len(protected))
        protected.append(value)
        return token

    lines = markdown.splitlines(keepends=True)
    block_output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        fence_match = FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            marker_char = marker[0]
            marker_len = len(marker)
            end = index + 1
            while end < len(lines):
                closing = FENCE_RE.match(lines[end])
                if (
                    closing
                    and closing.group(1)[0] == marker_char
                    and len(closing.group(1)) >= marker_len
                ):
                    end += 1
                    break
                end += 1
            segment = "".join(lines[index:end])
            ending = "\r\n" if segment.endswith("\r\n") else ("\n" if segment.endswith("\n") else "")
            block_output.append(store(segment) + ending)
            index = end
            continue

        if line.startswith(("    ", "\t")):
            end = index + 1
            while end < len(lines):
                candidate = lines[end]
                if candidate.startswith(("    ", "\t")) or not candidate.strip():
                    end += 1
                    continue
                break
            segment = "".join(lines[index:end])
            ending = "\r\n" if segment.endswith("\r\n") else ("\n" if segment.endswith("\n") else "")
            block_output.append(store(segment) + ending)
            index = end
            continue

        block_output.append(line)
        index += 1

    text = "".join(block_output)
    inline_output: list[str] = []
    cursor = 0
    while cursor < len(text):
        opening = re.search(r"`+", text[cursor:])
        if not opening:
            inline_output.append(text[cursor:])
            break
        start = cursor + opening.start()
        marker = opening.group(0)
        inline_output.append(text[cursor:start])
        search_from = start + len(marker)
        close = -1
        while True:
            candidate = text.find(marker, search_from)
            if candidate < 0:
                break
            before_is_tick = candidate > 0 and text[candidate - 1] == "`"
            after_index = candidate + len(marker)
            after_is_tick = after_index < len(text) and text[after_index] == "`"
            if not before_is_tick and not after_is_tick:
                close = candidate
                break
            search_from = candidate + len(marker)
        if close < 0:
            inline_output.append(text[start:])
            break
        end = close + len(marker)
        inline_output.append(store(text[start:end]))
        cursor = end
    return "".join(inline_output), protected


def _restore_code_regions(markdown: str, protected: list[str]) -> str:
    for index, value in enumerate(protected):
        token = _protected_code_token(index)
        if value.endswith("\r\n"):
            markdown = markdown.replace(token + "\r\n", value)
        elif value.endswith("\n"):
            markdown = markdown.replace(token + "\n", value)
        markdown = markdown.replace(token, value)
    return markdown


def _fence_transition(
    line: str, in_fence: bool, fence_char: str, fence_len: int
) -> tuple[bool, str, int]:
    match = FENCE_RE.match(line)
    if not match:
        return in_fence, fence_char, fence_len

    marker = match.group(1)
    marker_char = marker[0]
    marker_len = len(marker)
    if not in_fence:
        return True, marker_char, marker_len
    if marker_char == fence_char and marker_len >= fence_len:
        return False, "", 0
    return in_fence, fence_char, fence_len


def protect_and_transform_math(markdown: str) -> str:
    """Transform $...$ and $$...$$ into HTML MathJax wrappers outside code."""
    output: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    in_display_math = False
    display_buffer: list[str] = []

    def repl_inline(match: re.Match[str]) -> str:
        expr = match.group(1).strip()
        if not expr:
            return match.group(0)
        return f'<span class="math inline">\\\\({html.escape(expr)}\\\\)</span>'

    for line in markdown.splitlines(keepends=True):
        next_in_fence, next_fence_char, next_fence_len = _fence_transition(
            line, in_fence, fence_char, fence_len
        )
        fence_changed = (next_in_fence, next_fence_char, next_fence_len) != (
            in_fence,
            fence_char,
            fence_len,
        )
        if fence_changed and not in_display_math:
            in_fence, fence_char, fence_len = next_in_fence, next_fence_char, next_fence_len
            output.append(line)
            continue

        if in_fence:
            output.append(line)
            continue

        if DISPLAY_MATH_FENCE_RE.match(line):
            if in_display_math:
                expr = "".join(display_buffer).strip()
                output.append(f'<div class="math display">$${html.escape(expr)}$$</div>\n')
                display_buffer.clear()
                in_display_math = False
            else:
                in_display_math = True
                display_buffer.clear()
            continue

        if in_display_math:
            display_buffer.append(line)
            continue

        output.append(_replace_outside_inline_code(line, INLINE_MATH_RE, repl_inline))

    if in_display_math:
        output.append("$$\n")
        output.extend(display_buffer)
    return "".join(output)


def _dedent_footnote_line(line: str) -> str:
    if line.startswith("    "):
        return line[4:]
    if line.startswith("\t"):
        return line[1:]
    return line


def extract_footnotes(markdown: str) -> tuple[str, list[tuple[str, str]]]:
    """Extract Markdown footnotes, including indented multi-line bodies.

    The previous implementation only supported single-line definitions such as
    ``[^id]: text``. Standard Markdown footnotes often continue with four-space
    indented paragraphs, lists, or code. This parser keeps those continuation
    blocks together and removes them from the main document body before normal
    rendering.
    """
    lines = markdown.splitlines()
    body_lines: list[str] = []
    footnotes: list[tuple[str, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = FOOTNOTE_DEF_RE.match(line)
        if not match:
            body_lines.append(line)
            index += 1
            continue

        fid = match.group(1).strip()
        raw_lines = [match.group(2).strip()]
        index += 1
        while index < len(lines):
            current = lines[index]
            next_line = lines[index + 1] if index + 1 < len(lines) else ""
            if FOOTNOTE_DEF_RE.match(current):
                break
            if current.startswith(("    ", "\t")):
                raw_lines.append(_dedent_footnote_line(current))
                index += 1
                continue
            if not current.strip() and (next_line.startswith(("    ", "\t")) or not next_line.strip()):
                raw_lines.append("")
                index += 1
                continue
            break
        footnote_text = "\n".join(raw_lines).strip()
        if footnote_text:
            footnotes.append((fid, footnote_text))
    return "\n".join(body_lines), footnotes


@dataclass(slots=True)
class FootnoteEntry:
    fid: str
    raw: str
    index: int
    anchor: str
    ref_count: int = 0


def _safe_footnote_anchor(value: str, used: set[str]) -> str:
    """Return a deterministic, HTML-safe anchor for a footnote identifier."""
    text = unicodedata.normalize("NFKC", str(value or "").strip())
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^\w\u0600-\u06FF:.\-]+", "-", text, flags=re.UNICODE).strip("-._:")
    base = text or "note"
    anchor = base
    suffix = 2
    while anchor in used:
        anchor = f"{base}-{suffix}"
        suffix += 1
    used.add(anchor)
    return anchor


def _normalize_footnotes(footnotes: list[tuple[str, str]] | list[FootnoteEntry]) -> list[FootnoteEntry]:
    if not footnotes:
        return []
    first = footnotes[0]
    if isinstance(first, FootnoteEntry):
        return list(footnotes)  # type: ignore[arg-type]

    entries: list[FootnoteEntry] = []
    seen_ids: set[str] = set()
    used_anchors: set[str] = set()
    for fid, raw in footnotes:  # type: ignore[assignment]
        clean_id = str(fid or "").strip()
        if not clean_id or clean_id in seen_ids:
            continue
        seen_ids.add(clean_id)
        entries.append(
            FootnoteEntry(
                fid=clean_id,
                raw=str(raw or "").strip(),
                index=len(entries) + 1,
                anchor=_safe_footnote_anchor(clean_id, used_anchors),
            )
        )
    return entries


def replace_footnote_refs(
    markdown: str,
    *,
    footnotes: list[tuple[str, str]] | list[FootnoteEntry] | None = None,
    lang: str | None = None,
    text_hint: str = "",
) -> str:
    label = ui_label("footnote", lang=lang, text_hint=text_hint)
    entries = _normalize_footnotes(footnotes or [])
    entry_by_id = {entry.fid: entry for entry in entries}

    def repl(match: re.Match[str]) -> str:
        raw_id = match.group(1).strip()
        entry = entry_by_id.get(raw_id)
        if entry is None:
            # Keep unresolved references visible instead of generating a broken link.
            return html.escape(match.group(0))

        entry.ref_count += 1
        ref_suffix = "" if entry.ref_count == 1 else f"-{entry.ref_count}"
        ref_id = f"fnref-{entry.anchor}{ref_suffix}"
        note_id = f"fn-{entry.anchor}{ref_suffix}"
        display_index = localize_digits(entry.index, lang=lang, text_hint=text_hint)
        number_class = localized_number_class(entry.index, lang=lang, text_hint=text_hint)
        ref_classes = f"footnote-ref {number_class}"
        if language_family(lang, text_hint) == "fa":
            ref_classes += " footnote-ref--rtl"
        safe_label = html.escape(f"{label} {display_index}")
        return (
            f'<sup class="{html.escape(ref_classes)}" id="{html.escape(ref_id)}" '
            f'data-md2pdf-footnote-anchor="{html.escape(entry.anchor)}" '
            f'data-md2pdf-footnote-note-id="{html.escape(note_id)}" '
            f'data-md2pdf-footnote-ref-id="{html.escape(ref_id)}">'
            f'<a href="#{html.escape(note_id)}" aria-describedby="{html.escape(note_id)}" '
            f'aria-label="{safe_label}">{html.escape(display_index)}</a></sup>'
        )

    output: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    for line in markdown.splitlines(keepends=True):
        next_in_fence, next_fence_char, next_fence_len = _fence_transition(
            line, in_fence, fence_char, fence_len
        )
        fence_changed = (next_in_fence, next_fence_char, next_fence_len) != (
            in_fence,
            fence_char,
            fence_len,
        )
        if fence_changed:
            in_fence, fence_char, fence_len = next_in_fence, next_fence_char, next_fence_len
            output.append(line)
            continue
        if in_fence:
            output.append(line)
            continue
        output.append(_replace_outside_inline_code(line, INLINE_FOOTNOTE_RE, repl))
    return "".join(output)



def _render_footnote_item(
    entry: FootnoteEntry,
    md: MarkdownIt,
    *,
    note_id: str,
    ref_ids: list[str],
    lang: str | None = None,
    text_hint: str = "",
) -> str:
    rendered = md.render(entry.raw).strip()
    footnote_text = BeautifulSoup(rendered, "html.parser").get_text(" ", strip=True) or entry.raw
    body_profile = direction_profile(footnote_text)
    body_dir = _dir_for_profile(body_profile)
    body_classes = ["footnote-body", f"footnote-body--{body_profile}"]
    body_classes.extend(text_quality_classes(footnote_text))
    item_classes = ["footnote-item", f"footnote-item--{body_profile}"]
    if has_persian(footnote_text):
        item_classes.append("footnote-item--persian")
    if has_latin(footnote_text):
        item_classes.append("footnote-item--latin")
    note_number_profile = numeral_profile(footnote_text)
    if note_number_profile != "none":
        item_classes.append(f"footnote-item--{note_number_profile}-number")
    display_index = localize_digits(entry.index, lang=lang, text_hint=text_hint)
    number_class = localized_number_class(entry.index, lang=lang, text_hint=text_hint)
    backref_label = ui_label("footnote_backref", lang=lang, text_hint=text_hint)
    backrefs = []
    for ref_id in ref_ids:
        ref_label = html.escape(f"{backref_label} {display_index}")
        backrefs.append(
            f'<a class="footnote-backref" href="#{html.escape(ref_id)}" aria-label="{ref_label}">↩</a>'
        )
    return (
        f'<li class="{html.escape(" ".join(sorted(set(item_classes))))}" id="{html.escape(note_id)}">'
        f'<span class="footnote-marker {number_class}">{html.escape(display_index)}.</span>'
        f'<div class="{html.escape(" ".join(sorted(set(body_classes))))}" dir="{body_dir}" '
        f'data-md2pdf-direction-profile="{body_profile}" data-md2pdf-number-profile="{note_number_profile}">{rendered}</div> '
        f'<span class="footnote-backrefs">{"".join(backrefs)}</span></li>'
    )


def _footnote_container(tag: Tag) -> Tag:
    for parent in tag.parents:
        if not isinstance(parent, Tag):
            continue
        if parent.name in {"p", "li", "td", "th", "blockquote", "figure", "section", "div"}:
            if "footnotes" in parent.get("class", []):
                continue
            return parent
    return tag


def append_footnotes(
    body_html: str,
    footnotes: list[tuple[str, str]] | list[FootnoteEntry],
    md: MarkdownIt,
    *,
    lang: str | None = None,
    text_hint: str = "",
) -> str:
    """Insert footnotes near their references instead of collecting endnotes.

    Markdown libraries commonly render footnotes as a single end-of-document
    section. That is acceptable for web pages, but it is not the expected print
    behavior for a PDF guide. Chromium does not implement CSS ``float: footnote``,
    so Mardas Folio renders each footnote as a local print block immediately
    after the block that contains the reference. The block is kept with the
    reference when page flow allows it, which avoids the older endnote-only
    behavior and keeps repeated references on different pages readable.
    """
    entries = _normalize_footnotes(footnotes)
    if not entries:
        return body_html

    soup = BeautifulSoup(body_html, "html.parser")
    entry_by_anchor = {entry.anchor: entry for entry in entries}
    label = ui_label("footnotes", lang=lang, text_hint=text_hint)
    footnote_family = language_family(lang, text_hint)
    footnote_dir = "rtl" if footnote_family == "fa" else "ltr"
    grouped: dict[int, tuple[Tag, list[tuple[FootnoteEntry, str, str]]]] = {}

    for ref in soup.find_all("sup", class_=lambda c: c and "footnote-ref" in c):
        if not isinstance(ref, Tag):
            continue
        anchor = str(ref.get("data-md2pdf-footnote-anchor") or "")
        note_id = str(ref.get("data-md2pdf-footnote-note-id") or "")
        ref_id = str(ref.get("data-md2pdf-footnote-ref-id") or ref.get("id") or "")
        entry = entry_by_anchor.get(anchor)
        if entry is None or not note_id or not ref_id:
            continue
        container = _footnote_container(ref)
        key = id(container)
        if key not in grouped:
            grouped[key] = (container, [])
        grouped[key][1].append((entry, note_id, ref_id))

    for container, items in list(grouped.values()):
        rendered_items = []
        seen_note_ids: set[str] = set()
        for entry, note_id, ref_id in items:
            if note_id in seen_note_ids:
                continue
            seen_note_ids.add(note_id)
            rendered_items.append(
                _render_footnote_item(entry, md, note_id=note_id, ref_ids=[ref_id], lang=lang, text_hint=text_hint)
            )
        if not rendered_items:
            continue
        section_html = (
            f'<section class="footnotes footnotes--local footnotes--{footnote_dir}" dir="{footnote_dir}" '
            f'aria-label="{html.escape(label)}"><ol>{"".join(rendered_items)}</ol></section>'
        )
        section = BeautifulSoup(section_html, "html.parser").find("section")
        if section is None:
            continue
        if container.name in {"td", "th", "li"}:
            container.append(section)
        else:
            container.insert_after(section)
    return str(soup)


def slugify(value: str, used: set[str]) -> str:
    value = re.sub(r"<.*?>", "", value)
    value = re.sub(r"\s+", "-", value.strip().lower())
    value = re.sub(r"[^\w\u0600-\u06FF\-]+", "", value, flags=re.UNICODE)
    value = value.strip("-") or "section"
    base = value
    index = 2
    while value in used:
        value = f"{base}-{index}"
        index += 1
    used.add(value)
    return value


def add_heading_ids(
    html_text: str,
    *,
    toc_depth: int = 6,
    source_lines: Sequence[int] | None = None,
) -> tuple[str, list[tuple[int, str, str, str]]]:
    used: set[str] = set()
    toc: list[tuple[int, str, str, str]] = []
    max_depth = max(1, min(int(toc_depth or 6), 6))
    line_iter = iter(source_lines or ())

    def repl(match: re.Match[str]) -> str:
        level = int(match.group(1))
        attrs = match.group(2)
        content = match.group(3)
        if " id=" in attrs:
            id_match = re.search(r'id=["\']([^"\']+)["\']', attrs)
            requested_id = id_match.group(1) if id_match else ""
            if requested_id and requested_id not in used:
                heading_id = requested_id
                used.add(heading_id)
            else:
                heading_id = slugify(requested_id or content, used)
                if id_match:
                    attrs = (
                        attrs[: id_match.start(1)]
                        + html.escape(heading_id, quote=True)
                        + attrs[id_match.end(1) :]
                    )
        else:
            heading_id = slugify(content, used)
            attrs += f' id="{heading_id}"'
        source_line = next(line_iter, None)
        if source_line is not None:
            attrs = re.sub(r"\sdata-source-line=[\"'][^\"']*[\"']", "", attrs)
            attrs += f' data-source-line="{max(1, int(source_line))}"'
        plain = BeautifulSoup(content, "html.parser").get_text(" ", strip=True)
        if level <= max_depth and plain:
            toc.append((level, plain, heading_id, content))
        anchor = (
            f'<a class="heading-anchor" href="#{html.escape(heading_id)}" '
            f'aria-label="Permalink to {html.escape(plain)}">#</a>'
        )
        return f"<h{level}{attrs}>{content}{anchor}</h{level}>"

    return HEADING_RE.sub(repl, html_text), toc


def _toc_tree(entries: list[tuple[int, str, str, str]]) -> list[TocItem]:
    """Build a proper nested TOC tree based on Markdown heading levels.

    The stack uses the original HTML heading level, so a skipped level such as
    h1 -> h3 is still treated as a child of the nearest previous parent. The
    displayed section number is based on the actual nesting depth in the tree,
    producing values such as 2, 2-1, 2-2 and 2-2-3.
    """
    roots: list[TocItem] = []
    stack: list[tuple[int, TocItem]] = []
    counters: list[int] = []

    for entry in entries:
        if len(entry) == 3:
            source_level, title, heading_id = entry
            title_html = html.escape(title)
        else:
            source_level, title, heading_id, title_html = entry
        while stack and stack[-1][0] >= source_level:
            stack.pop()
        depth = len(stack) + 1
        counters = counters[:depth]
        while len(counters) < depth:
            counters.append(0)
        counters[depth - 1] += 1
        number = "-".join(str(value) for value in counters)
        item = TocItem(source_level, title, heading_id, number, title_html)
        if stack:
            stack[-1][1].children.append(item)
        else:
            roots.append(item)
        stack.append((source_level, item))
    return roots


def _render_toc_items(
    items: list[TocItem],
    *,
    depth: int = 1,
    lang: str | None = None,
    text_hint: str = "",
) -> str:
    if not items:
        return ""
    nested_class = " toc-list--nested" if depth > 1 else ""
    parts = [f'<ol class="toc-list toc-depth-{depth}{nested_class}" data-depth="{depth}">']
    for item in items:
        display_number = localize_digits(item.number, lang=lang, text_hint=text_hint)
        number_class = localized_number_class(item.number, lang=lang, text_hint=text_hint)
        title_profile = direction_profile(item.title)
        title_dir = _dir_for_profile(title_profile)
        title_classes = ["toc-title", f"toc-title--{title_profile}"]
        title_classes.extend(text_quality_classes(item.title))
        item_classes = ["toc-item", f"toc-level-{item.level}", f"toc-item--{title_profile}"]
        if has_persian(item.title):
            item_classes.append("toc-item--persian")
        if has_latin(item.title):
            item_classes.append("toc-item--latin")
        title_number_profile = numeral_profile(item.title)
        if title_number_profile != "none":
            item_classes.append(f"toc-item--{title_number_profile}-number")
        if title_profile == "mixed":
            item_classes.append("toc-item--mixed-script")
        parts.append(
            f'<li class="{html.escape(" ".join(sorted(set(item_classes))))}" '
            f'data-level="{item.level}" '
            f'data-toc-depth="{depth}" '
            f'data-md2pdf-number="{html.escape(item.number)}" '
            f'data-md2pdf-number-display="{html.escape(display_number)}" '
            f'data-md2pdf-title-profile="{html.escape(title_profile)}" '
            f'data-md2pdf-title-number-profile="{html.escape(title_number_profile)}">'
            f'<a href="#{html.escape(item.heading_id)}">'
            f'<span class="toc-number {number_class}">{html.escape(display_number)}</span>'
            f'<span class="{html.escape(" ".join(dict.fromkeys(title_classes)))}" dir="{html.escape(title_dir)}">'
            f'{item.title_html or html.escape(item.title)}</span>'
            f'</a>'
        )
        parts.append(_render_toc_items(item.children, depth=depth + 1, lang=lang, text_hint=text_hint))
        parts.append('</li>')
    parts.append('</ol>')
    return "".join(parts)


def build_toc(
    toc: list[tuple[int, str, str, str]],
    enabled: bool,
    *,
    lang: str | None = None,
    text_hint: str = "",
) -> str:
    if not enabled or not toc:
        return ""
    tree = _toc_tree(toc)
    title = ui_label("toc_title", lang=lang, text_hint=text_hint)
    aria = ui_label("toc_aria", lang=lang, text_hint=text_hint)
    toc_family = language_family(lang, text_hint)
    toc_dir = "rtl" if toc_family == "fa" else "ltr"
    toc_classes = f"md2pdf-toc md2pdf-toc--{toc_dir} md2pdf-toc--profiled"
    title_profile = direction_profile(title)
    return (
        f'<nav class="{toc_classes}" dir="{toc_dir}" aria-label="{html.escape(aria)}" '
        f'data-md2pdf-direction-profile="{html.escape(toc_dir)}" '
        f'data-md2pdf-title-profile="{html.escape(title_profile)}" '
        f'data-md2pdf-number-locale="{language_family(lang, text_hint)}">'
        f'<h2>{html.escape(title)}</h2>'
        f'{_render_toc_items(tree, lang=lang, text_hint=text_hint)}'
        '</nav>'
    )


def normalize_raw_code_blocks(soup: BeautifulSoup, *, code_style: str) -> None:
    """Wrap and highlight raw indented code blocks.

    markdown-it applies the custom highlighter to fenced code, but not to every
    4-space indented block. Without this pass, those blocks inherit light code
    text without the dark/bright container, which makes them nearly invisible in
    Chromium PDFs.
    """
    skip_parent_classes = {"code-block", "codehilite", "highlight"}
    for pre in list(soup.find_all("pre")):
        parents = list(pre.parents)
        if any(skip_parent_classes.intersection(set(parent.get("class", []))) for parent in parents if isinstance(parent, Tag)):
            continue
        code_tag = pre.find("code")
        code = code_tag.get_text() if code_tag else pre.get_text()
        lang, caption = guess_code_language(code)
        fragment = BeautifulSoup(
            highlight_code(
                code.rstrip("\n"),
                lang,
                code_style=code_style,
                caption=caption,
                extra_classes="raw-code-block",
            ),
            "html.parser",
        )
        figure = fragment.find("figure")
        if figure is not None:
            pre.replace_with(figure)


def _is_path_inside(path: Path, root: Path) -> bool:
    """Return whether a possibly symlinked path stays under the document root."""
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _local_image_candidates(
    src: str,
    base_dir: Path,
    *,
    document_root: Path | None = None,
) -> list[Path]:
    """Return safe local filesystem candidates for an image src.

    Markdown image paths are treated as document-local assets. Remote URLs and
    existing data URIs are intentionally left untouched, while absolute paths,
    ``file:`` URLs, and parent-directory escapes are ignored so a Markdown file
    cannot silently embed arbitrary files from the host machine.
    """
    parsed = urlparse(src.strip())
    if parsed.scheme in {"http", "https", "data", "mailto"}:
        return []
    if parsed.scheme:
        return []

    clean_src = unquote(src.split("#", 1)[0].split("?", 1)[0]).strip()
    if not clean_src:
        return []

    raw_path = Path(clean_src)
    if raw_path.is_absolute():
        return []

    base_dir = base_dir.resolve(strict=False)
    allowed_root = (document_root or base_dir).resolve(strict=False)
    if not _is_path_inside(base_dir, allowed_root):
        return []
    candidates = [base_dir / raw_path]

    # A common authoring mistake is to keep the Markdown reference as
    # images/foo.png while exporting or copying foo.png beside the Markdown file.
    # Falling back to the basename keeps the converter forgiving while still
    # limiting all lookups to the Markdown document directory.
    if len(raw_path.parts) > 1:
        candidates.append(base_dir / raw_path.name)

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not _is_path_inside(candidate, allowed_root):
            continue
        key = str(candidate.resolve(strict=False))
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def _image_file_to_data_uri(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    mime_type = mimetypes.guess_type(str(path))[0] or "image/png"
    if not mime_type.startswith("image/"):
        return None
    size = path.stat().st_size
    if size > MAX_EMBED_IMAGE_BYTES:
        warnings.warn(
            f"Skipping image larger than {MAX_EMBED_IMAGE_BYTES} bytes: {path}",
            RuntimeWarning,
            stacklevel=2,
        )
        return None
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _has_url_control_chars(value: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def _is_safe_data_image_url(value: str) -> bool:
    if not value.lower().startswith("data:") or "," not in value:
        return False
    header = value[5:].split(",", 1)[0].strip().lower()
    media_type = header.split(";", 1)[0].strip()
    return media_type in SAFE_DATA_IMAGE_MIME_TYPES


def _is_safe_url(value: str) -> bool:
    raw_value = str(value or "").strip()
    if _has_url_control_chars(raw_value):
        return False
    parsed = urlparse(raw_value)
    scheme = parsed.scheme.lower()
    if scheme not in SAFE_URL_SCHEMES:
        return False
    if scheme == "data":
        return _is_safe_data_image_url(raw_value)
    return True


def sanitize_html(body_html: str) -> str:
    """Keep a safe, document-oriented subset of raw HTML.

    Markdown authors can still use useful HTML such as ``<img>`` and explicit
    page-break ``<div>`` markers. Active content and event handlers are removed
    before the HTML is handed to Chromium.
    """
    soup = BeautifulSoup(body_html, "html.parser")
    for tag in list(soup.find_all(True)):
        name = (tag.name or "").lower()
        if name in BLOCKED_RAW_HTML_TAGS:
            tag.decompose()
            continue
        if name not in SAFE_RAW_HTML_TAGS:
            tag.unwrap()
            continue

        allowed = GLOBAL_SAFE_ATTRS | TAG_SAFE_ATTRS.get(name, set())
        for attr in list(tag.attrs):
            lower_attr = attr.lower()
            if lower_attr.startswith("on") or lower_attr == "style" or lower_attr not in allowed:
                del tag.attrs[attr]
                continue
            value = tag.attrs.get(attr)
            if lower_attr in {"href", "src"}:
                values = value if isinstance(value, list) else [str(value)]
                if not values or any(not _is_safe_url(str(item)) for item in values):
                    del tag.attrs[attr]
            elif lower_attr in {"target", "rel"}:
                if name != "a":
                    del tag.attrs[attr]
        if name == "a" and tag.get("target") == "_blank":
            rel = set(str(tag.get("rel") or "").split())
            rel.update({"noopener", "noreferrer"})
            tag["rel"] = " ".join(sorted(rel))
    return str(soup)


def block_local_file_links(body_html: str) -> str:
    """Remove local filesystem-style links while preserving anchors and web URLs.

    Chromium resolves relative links against the page URL. Historically the
    renderer supplied an absolute ``file://`` base URL, which leaked the build
    machine path into PDF annotations. Local links are now kept visible but made
    inert; fragment links, web links, and mail links remain functional.
    """
    soup = BeautifulSoup(body_html, "html.parser")
    for link in soup.find_all("a", href=True):
        href = str(link.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        parsed = urlparse(href)
        if parsed.scheme.lower() in {"http", "https", "mailto"}:
            continue
        if parsed.scheme:
            continue
        del link["href"]
        classes = set(link.get("class", []))
        classes.add("md2pdf-local-link-blocked")
        link["class"] = sorted(classes)
        link["title"] = "Local file link omitted from portable PDF output"
        link["data-md2pdf-source"] = href
    return str(soup)


def _is_local_image_reference(src: str) -> bool:
    """Return whether an image source would ask Chromium to read local files."""
    parsed = urlparse(src.strip())
    if parsed.scheme.lower() in {"http", "https", "data", "mailto"}:
        return False
    return True


def _is_remote_image_reference(src: str) -> bool:
    return urlparse(src.strip()).scheme.lower() in {"http", "https"}


def _short_blocked_image_source(src: str, *, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", str(src or "").strip())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _block_image_reference(soup: BeautifulSoup, img: Tag, src: str, *, reason: str) -> None:
    """Prevent Chromium from resolving an image source outside the asset boundary."""
    label = "Remote image blocked" if reason == "remote" else "Image blocked or missing"
    detail = _short_blocked_image_source(src)

    placeholder = soup.new_tag("span")
    placeholder["class"] = "md2pdf-image-placeholder md2pdf-image--blocked"
    placeholder["role"] = "note"
    placeholder["data-md2pdf-blocked-src"] = src
    placeholder["data-md2pdf-blocked-reason"] = reason

    title = soup.new_tag("strong")
    title.string = label
    placeholder.append(title)
    if detail:
        body = soup.new_tag("span")
        body.string = detail
        placeholder.append(body)

    img.replace_with(placeholder)


def block_remote_images(body_html: str) -> str:
    """Replace remote image sources with visible placeholders.

    ``render_markdown_file`` resolves local files later because it knows the
    Markdown file location.  ``render_markdown`` has no filesystem boundary, but
    it still exposes the same privacy boundary for network images by default.
    """
    soup = BeautifulSoup(body_html, "html.parser")
    for img in soup.find_all("img"):
        src = str(img.get("src") or "").strip()
        if src and _is_remote_image_reference(src):
            _block_image_reference(soup, img, src, reason="remote")
    return str(soup)


def embed_local_images(
    body_html: str,
    base_dir: str | Path,
    *,
    document_root: str | Path | None = None,
    allow_remote_images: bool = False,
) -> str:
    """Inline document-local images and block unsafe unresolved image reads.

    Chromium can render relative image paths when every asset is present beside
    the Markdown file. In practice, reports are often copied without their
    ``images/`` directory, or generated from a temporary working directory. This
    pass resolves local ``<img src=...>`` values against the Markdown location and
    embeds the image bytes directly into the HTML, so the PDF no longer depends
    on external files during the print step.

    If a local image source cannot be embedded safely, it is replaced with a
    transparent placeholder. This keeps the renderer from falling back to the
    document ``<base>`` URL and reading parent-directory or absolute paths during
    Chromium's print step. Remote URLs are blocked by default for privacy and can
    be allowed explicitly by trusted callers. Existing data URIs are left unchanged.
    """
    soup = BeautifulSoup(body_html, "html.parser")
    root = Path(base_dir)
    for img in soup.find_all("img"):
        src = str(img.get("src") or "").strip()
        if not src:
            continue
        embedded = False
        for candidate in _local_image_candidates(
            src,
            root,
            document_root=Path(document_root) if document_root is not None else None,
        ):
            data_uri = _image_file_to_data_uri(candidate)
            if not data_uri:
                continue
            img["src"] = data_uri
            img["data-md2pdf-source"] = src
            img["class"] = list(set(img.get("class", []) + ["md2pdf-image"]))
            embedded = True
            break
        if not embedded and _is_local_image_reference(src):
            _block_image_reference(soup, img, src, reason="local")
        elif not allow_remote_images and _is_remote_image_reference(src):
            _block_image_reference(soup, img, src, reason="remote")
    return str(soup)


AUTOLINK_RE = re.compile(
    r"(?P<url>https?://[^\s<]+|www\.[^\s<]+)|(?P<email>[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})"
)
AUTOLINK_SKIP_PARENTS = {"a", "code", "pre", "script", "style", "kbd"}


def apply_literal_autolinks(soup: BeautifulSoup) -> None:
    """Link bare URLs, www-prefixed domains, and email addresses outside code."""
    for node in list(soup.find_all(string=True)):
        text = str(node)
        if not text or not AUTOLINK_RE.search(text):
            continue
        if any(parent.name in AUTOLINK_SKIP_PARENTS for parent in node.parents if isinstance(parent, Tag)):
            continue
        fragment = soup.new_tag("span")
        pos = 0
        for match in AUTOLINK_RE.finditer(text):
            if match.start() > pos:
                fragment.append(NavigableString(text[pos : match.start()]))
            label = match.group(0).rstrip('.,);:!?')
            trailing = match.group(0)[len(label):]
            href = label
            if match.group("email"):
                href = f"mailto:{label}"
            elif label.startswith("www."):
                href = f"https://{label}"
            link = soup.new_tag("a", href=href)
            link.string = label
            fragment.append(link)
            if trailing:
                fragment.append(NavigableString(trailing))
            pos = match.end()
        if pos < len(text):
            fragment.append(NavigableString(text[pos:]))
        node.replace_with(fragment)
        fragment.unwrap()


CAPTION_PREFIX_RE = re.compile(
    r"^(?:"
    r"fig(?:ure)?\.?(?:\s+[0-9۰-۹٠-٩]+)?|"
    r"image(?:\s+[0-9۰-۹٠-٩]+)?|"
    r"table(?:\s+[0-9۰-۹٠-٩]+)?|"
    r"listing(?:\s+[0-9۰-۹٠-٩]+)?|"
    r"code(?:\s+[0-9۰-۹٠-٩]+)?|"
    r"diagram(?:\s+[0-9۰-۹٠-٩]+)?|"
    r"شکل(?:\s+[0-9۰-۹٠-٩]+)?|"
    r"تصویر(?:\s+[0-9۰-۹٠-٩]+)?|"
    r"جدول(?:\s+[0-9۰-۹٠-٩]+)?|"
    r"کد(?:\s+[0-9۰-۹٠-٩]+)?|"
    r"نمودار(?:\s+[0-9۰-۹٠-٩]+)?"
    r")\b",
    re.I,
)
TABLE_CAPTION_RE = re.compile(r"^(?:table(?:\s+[0-9۰-۹٠-٩]+)?|جدول(?:\s+[0-9۰-۹٠-٩]+)?)[\s:：.\-–—]+", re.I)


def _caption_paragraph_html(paragraph: Tag, *, expected: str | None = None) -> str:
    """Return paragraph HTML when it is an unambiguous print caption."""
    text = paragraph.get_text(" ", strip=True)
    if not text:
        return ""
    if expected == "table" and not TABLE_CAPTION_RE.match(text):
        return ""
    if expected is None and not CAPTION_PREFIX_RE.match(text):
        return ""
    return "".join(str(child) for child in paragraph.contents).strip()


def _append_caption_from_html(soup: BeautifulSoup, parent: Tag, caption_html: str, *, kind: str) -> Tag:
    caption = soup.new_tag("figcaption" if parent.name == "figure" else "caption")
    caption["class"] = ["md2pdf-caption", f"md2pdf-caption--{kind}"]
    caption["dir"] = "auto"
    caption.append(BeautifulSoup(caption_html, "html.parser"))
    parent.append(caption)
    return caption


def _caption_profile_classes(caption: Tag) -> list[str]:
    text = caption.get_text(" ", strip=True)
    if not text:
        return []
    classes = text_quality_classes(text)
    profile = direction_profile(text)
    if profile == "rtl":
        classes.append("md2pdf-caption--rtl")
    elif profile == "ltr":
        classes.append("md2pdf-caption--ltr")
    elif profile == "mixed":
        classes.append("md2pdf-caption--mixed")
    if PERSIAN_CAPTION_PREFIX_RE.match(text) or has_persian(text):
        classes.append("md2pdf-caption--persian")
    number_profile = numeral_profile(text)
    if number_profile != "none":
        classes.append("md2pdf-caption--numbered")
        classes.append(f"md2pdf-caption--{number_profile}-number")
    classes.append("md2pdf-caption--profiled")
    return sorted(set(classes))


def _apply_caption_profile(caption: Tag) -> None:
    """Apply explicit direction and audit metadata to a semantic caption."""
    text = caption.get_text(" ", strip=True)
    caption_classes = set(caption.get("class", []))
    caption_classes.difference_update(
        {
            "md2pdf-caption--rtl",
            "md2pdf-caption--ltr",
            "md2pdf-caption--mixed",
            "md2pdf-caption--persian",
            "md2pdf-caption--numbered",
            "md2pdf-caption--persian-number",
            "md2pdf-caption--latin-number",
            "md2pdf-caption--mixed-number",
            "md2pdf-caption--profiled",
            "md2pdf-rtl-text",
            "md2pdf-ltr-text",
            "mixed-script",
            "persian-numeral",
            "latin-numeral",
            "mixed-numeral",
        }
    )
    caption_classes.update(_caption_profile_classes(caption))
    caption["class"] = sorted(caption_classes)
    profile = direction_profile(text)
    caption["dir"] = _dir_for_profile(profile)
    caption["data-md2pdf-direction-profile"] = profile
    caption["data-md2pdf-number-profile"] = numeral_profile(text)


def normalize_semantic_captions(soup: BeautifulSoup) -> None:
    """Apply consistent caption classes to figures, diagrams, code, and tables."""
    for figure in soup.find_all("figure"):
        classes = set(figure.get("class", []))
        kind = "figure"
        if "code-block" in classes:
            kind = "code"
        elif "mermaid-diagram" in classes:
            kind = "diagram"
        for caption in figure.find_all("figcaption", recursive=False):
            _add_classes(caption, "md2pdf-caption", f"md2pdf-caption--{kind}")
            _apply_caption_profile(caption)
    for table in soup.find_all("table"):
        for caption in table.find_all("caption", recursive=False):
            _add_classes(caption, "md2pdf-caption", "md2pdf-caption--table")
            _apply_caption_profile(caption)


def enhance_accessibility_semantics(soup: BeautifulSoup) -> None:
    """Add deterministic HTML associations used by browsers and source audits.

    Chromium does not currently emit a verified tagged PDF for this project, so
    these attributes are HTML-level improvements rather than a PDF/UA claim.
    """
    used_ids = {str(tag.get("id")) for tag in soup.find_all(id=True) if tag.get("id")}

    def allocate(prefix: str) -> str:
        index = 1
        while True:
            candidate = f"md2pdf-{prefix}-{index:03d}"
            if candidate not in used_ids:
                used_ids.add(candidate)
                return candidate
            index += 1

    for figure in soup.find_all("figure"):
        classes = set(figure.get("class", []))
        if classes.intersection({"code-block", "mermaid-diagram"}) or figure.find("img") is None:
            continue
        caption = figure.find("figcaption", recursive=False)
        if caption is not None:
            caption_id = str(caption.get("id") or allocate("figure-caption"))
            caption["id"] = caption_id
            figure["role"] = figure.get("role") or "group"
            figure["aria-labelledby"] = caption_id

    for table in soup.find_all("table"):
        caption = table.find("caption", recursive=False)
        if caption is not None:
            caption_id = str(caption.get("id") or allocate("table-caption"))
            caption["id"] = caption_id
            table["aria-describedby"] = caption_id

        thead = table.find("thead")
        if thead is not None:
            for header in thead.find_all("th"):
                header["scope"] = header.get("scope") or "col"

        for row in table.find_all("tr"):
            direct_cells = row.find_all(["th", "td"], recursive=False)
            if not direct_cells:
                continue
            for position, cell in enumerate(direct_cells):
                if cell.name != "th" or cell.get("scope"):
                    continue
                cell["scope"] = "row" if position == 0 and row.find_parent("tbody") else "col"


def promote_image_caption_pairs(soup: BeautifulSoup) -> None:
    """Turn common Markdown image-caption pairs into semantic figures.

    Markdown has no official caption syntax, but documentation often uses::

        ![Architecture](arch.png)
        *Figure 1. Architecture overview.*

    This pass preserves normal paragraphs while giving the PDF renderer a proper
    ``<figure>`` / ``<figcaption>`` structure when the pattern is unambiguous.
    """
    for paragraph in list(soup.find_all("p")):
        images = paragraph.find_all("img", recursive=False)
        if len(images) != 1:
            continue
        meaningful_text = paragraph.get_text("", strip=True)
        if meaningful_text:
            continue
        next_sibling = paragraph.find_next_sibling()
        caption_html = ""
        if isinstance(next_sibling, Tag) and next_sibling.name == "p":
            caption_html = _caption_paragraph_html(next_sibling)
            if caption_html:
                next_sibling.decompose()
        figure = soup.new_tag("figure")
        figure["class"] = "md2pdf-figure"
        figure["dir"] = "auto"
        paragraph.replace_with(figure)
        figure.append(images[0].extract())
        if caption_html:
            _append_caption_from_html(soup, figure, caption_html, kind="figure")


def promote_table_caption_pairs(soup: BeautifulSoup) -> None:
    """Attach adjacent table captions to tables before table wrapping."""
    for table in list(soup.find_all("table")):
        if table.find("caption", recursive=False):
            continue
        caption_source = table.find_next_sibling()
        placement = "append"
        caption_html = ""
        if isinstance(caption_source, Tag) and caption_source.name == "p":
            caption_html = _caption_paragraph_html(caption_source, expected="table")
        if not caption_html:
            caption_source = table.find_previous_sibling()
            placement = "insert"
            if isinstance(caption_source, Tag) and caption_source.name == "p":
                caption_html = _caption_paragraph_html(caption_source, expected="table")
        if not caption_html:
            continue
        caption = soup.new_tag("caption")
        caption["class"] = ["md2pdf-caption", "md2pdf-caption--table"]
        caption["dir"] = "auto"
        caption.append(BeautifulSoup(caption_html, "html.parser"))
        if placement == "insert":
            table.insert(0, caption)
        else:
            table.insert(0, caption)
        caption_source.decompose()


def _table_column_count(table: Tag) -> int:
    """Return the widest row width, honoring simple colspan values."""
    max_columns = 0
    for row in table.find_all("tr"):
        columns = 0
        for cell in row.find_all(["th", "td"], recursive=False):
            try:
                colspan = int(str(cell.get("colspan") or "1"))
            except ValueError:
                colspan = 1
            columns += max(1, colspan)
        max_columns = max(max_columns, columns)
    return max_columns


def _table_row_count(table: Tag) -> int:
    """Return the number of rendered rows for print-flow hints."""
    return len(table.find_all("tr"))

def postprocess_html(
    body_html: str,
    *,
    code_style: str = "github-dark",
    lang: str | None = None,
    references_enabled: bool = False,
    citations_enabled: bool = False,
    source_path: Path | None = None,
) -> tuple[str, tuple[Diagnostic, ...]]:
    soup = BeautifulSoup(body_html, "html.parser")
    reference_diagnostics: tuple[Diagnostic, ...] = ()
    citation_diagnostics: tuple[Diagnostic, ...] = ()

    promote_image_caption_pairs(soup)
    promote_table_caption_pairs(soup)
    render_mermaid_placeholders(soup)
    apply_literal_autolinks(soup)
    normalize_raw_code_blocks(soup, code_style=code_style)
    normalize_semantic_captions(soup)
    normalize_github_callouts(soup, lang=lang)
    if references_enabled:
        from .references import annotate_reference_markup

        annotated_html, reference_diagnostics = annotate_reference_markup(
            str(soup),
            path=source_path,
            lang=lang,
        )
        soup = BeautifulSoup(annotated_html, "html.parser")
        normalize_semantic_captions(soup)
    if citations_enabled:
        from .citations import annotate_citation_markup

        annotated_html, citation_diagnostics = annotate_citation_markup(
            str(soup),
            path=source_path,
        )
        soup = BeautifulSoup(annotated_html, "html.parser")
    isolate_ltr_runs_in_mixed_persian_text(soup)

    # Direction-aware blocks and inline content.
    for tag in soup.find_all(["p", "li", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "figcaption", "caption"]):
        if "footnote-item" in tag.get("class", []):
            continue
        text = tag.get_text(" ", strip=True)
        if not text:
            continue
        profile = direction_profile(text)
        if not tag.get("dir"):
            tag["dir"] = _dir_for_profile(profile)
        _add_classes(tag, *text_quality_classes(text))

    # Make code and pre blocks strictly LTR.
    for tag in soup.find_all(["pre", "code"]):
        tag["dir"] = "ltr"

    # Wrap tables for visual polish, safe overflow, and stable RTL/LTR behavior.
    for table in soup.find_all("table"):
        if table.parent and getattr(table.parent, "name", None) == "div" and "table-wrap" in table.parent.get("class", []):
            continue
        columns = _table_column_count(table)
        rows = _table_row_count(table)
        table_text = table.get_text(" ", strip=True)
        table_profile = direction_profile(table_text)
        table_number_profile = numeral_profile(table_text)
        classes = ["table-wrap", "table-wrap--profiled", f"table-wrap--{table_profile}"]
        classes.extend(text_quality_classes(table_text))
        if columns >= 6 or rows >= 12:
            classes.append("table-wrap--compact")
        if rows >= 10:
            classes.append("table-wrap--medium")
        if columns >= 8:
            classes.append("table-wrap--wide")
        if columns >= 12:
            classes.append("table-wrap--very-wide")
        if rows >= 18:
            classes.append("table-wrap--long")
        if table.find("caption", recursive=False):
            classes.append("table-wrap--captioned")

        rtl_cells = 0
        ltr_cells = 0
        mixed_cells = 0
        neutral_cells = 0
        rtl_direction_votes = 0
        ltr_direction_votes = 0
        numeric_cells = 0
        persian_numeric_cells = 0
        latin_numeric_cells = 0
        mixed_numeric_cells = 0
        for cell in table.find_all(["th", "td"]):
            cell_text = cell.get_text(" ", strip=True)
            cell_profile = direction_profile(cell_text)
            cell["data-md2pdf-direction-profile"] = cell_profile
            if cell_profile == "rtl":
                rtl_cells += 1
                rtl_direction_votes += 1
                _add_classes(cell, "table-cell--rtl")
                if not cell.get("dir"):
                    cell["dir"] = "rtl"
            elif cell_profile == "ltr":
                ltr_cells += 1
                ltr_direction_votes += 1
                _add_classes(cell, "table-cell--ltr")
                if not cell.get("dir"):
                    cell["dir"] = "ltr"
            elif cell_profile == "mixed":
                mixed_cells += 1
                concrete_direction = mixed_text_direction(cell_text, lang=lang)
                mixed_direction_class = (
                    f"table-cell--mixed-{concrete_direction}"
                    if concrete_direction in {"rtl", "ltr"}
                    else ""
                )
                _add_classes(cell, "table-cell--mixed", mixed_direction_class, "mixed-script")
                if concrete_direction == "rtl":
                    rtl_direction_votes += 1
                elif concrete_direction == "ltr":
                    ltr_direction_votes += 1
                if not cell.get("dir") or str(cell.get("dir")).lower() == "auto":
                    cell["dir"] = concrete_direction
            else:
                neutral_cells += 1
            cell_numeric_profile = numeral_profile(cell_text)
            cell["data-md2pdf-number-profile"] = cell_numeric_profile
            if cell_numeric_profile != "none":
                numeric_cells += 1
                if cell_numeric_profile == "mixed":
                    mixed_numeric_cells += 1
                    _add_classes(cell, "mixed-numeral")
                elif cell_numeric_profile == "persian":
                    persian_numeric_cells += 1
                    _add_classes(cell, "persian-numeral")
                elif cell_numeric_profile == "latin":
                    latin_numeric_cells += 1
                    _add_classes(cell, "latin-numeral")
            if has_persian_punctuation(cell_text):
                _add_classes(cell, "persian-punctuation")
            if has_ascii_rtl_punctuation(cell_text):
                _add_classes(cell, "rtl-ascii-punctuation")

        table_direction = "auto"
        if rtl_direction_votes > ltr_direction_votes:
            table_direction = "rtl"
        elif ltr_direction_votes > rtl_direction_votes:
            table_direction = "ltr"
        elif language_family(lang, table_text) == "fa" and has_persian(table_text):
            table_direction = "rtl"
        elif ltr_direction_votes or rtl_direction_votes:
            table_direction = "ltr"

        if table_direction == "rtl":
            classes.append("table-wrap--rtl")
            table["dir"] = table.get("dir") or "rtl"
        elif table_direction == "ltr":
            classes.append("table-wrap--ltr")
            table["dir"] = table.get("dir") or "ltr"
        else:
            table["dir"] = table.get("dir") or "auto"
        if mixed_cells or (rtl_cells and ltr_cells):
            classes.append("table-wrap--mixed-direction")
        if numeric_cells:
            classes.append("table-wrap--numeric")
        if table_number_profile == "mixed" or mixed_numeric_cells:
            classes.append("table-wrap--mixed-numerals")
            classes.append("table-wrap--mixed-number")
        elif table_number_profile == "persian" or persian_numeric_cells:
            classes.append("table-wrap--persian-numerals")
            classes.append("table-wrap--persian-number")
        elif table_number_profile == "latin" or latin_numeric_cells:
            classes.append("table-wrap--latin-numerals")
            classes.append("table-wrap--latin-number")

        caption = table.find("caption", recursive=False)
        if caption:
            caption_text = caption.get_text(" ", strip=True)
            caption_profile = direction_profile(caption_text)
            classes.append(f"table-wrap--caption-{caption_profile}")
            if has_persian(caption_text):
                classes.append("table-wrap--persian-caption")

        wrapper = soup.new_tag("div")
        wrapper["class"] = sorted(set(classes))
        wrapper["dir"] = table.get("dir") or "auto"
        wrapper["data-md2pdf-direction-profile"] = table_profile
        wrapper["data-md2pdf-number-profile"] = table_number_profile
        wrapper["data-md2pdf-rtl-cells"] = str(rtl_cells)
        wrapper["data-md2pdf-ltr-cells"] = str(ltr_cells)
        wrapper["data-md2pdf-mixed-cells"] = str(mixed_cells)
        wrapper["data-md2pdf-neutral-cells"] = str(neutral_cells)
        wrapper["data-md2pdf-rtl-direction-votes"] = str(rtl_direction_votes)
        wrapper["data-md2pdf-ltr-direction-votes"] = str(ltr_direction_votes)
        wrapper["data-md2pdf-numeric-cells"] = str(numeric_cells)
        if columns:
            wrapper["data-md2pdf-columns"] = str(columns)
        if rows:
            wrapper["data-md2pdf-rows"] = str(rows)
        table.wrap(wrapper)

    def _consume_task_list_marker(li: Tag) -> bool | None:
        children = list(li.contents)
        for idx, child in enumerate(children):
            if not isinstance(child, NavigableString):
                if str(child).strip():
                    return None
                continue
            text = str(child)
            if not text.strip():
                continue
            match = re.match(r"^(\s*)\[( |x|X)\]\s+", text)
            if match:
                child.replace_with(text[match.end() :])
                return match.group(2).lower() == "x"

            # Persian mixed-script isolation can wrap the `x` in `[x]` before task
            # list normalization runs, producing `[<span ...>x</span>] text`.
            # Consume that structured marker so RTL guide task lists render with
            # real disabled checkboxes instead of visible `[x]` text.
            if not re.match(r"^\s*\[\s*$", text):
                return None
            if idx + 2 >= len(children):
                return None
            marker = children[idx + 1]
            closer = children[idx + 2]
            marker_text = marker.get_text(strip=True) if isinstance(marker, Tag) else str(marker).strip()
            if marker_text not in {"x", "X", ""}:
                return None
            if not isinstance(closer, NavigableString):
                return None
            close_text = str(closer)
            close_match = re.match(r"^\]\s+", close_text)
            if not close_match:
                return None

            child.extract()
            marker.extract()
            closer.replace_with(close_text[close_match.end() :])
            return marker_text.lower() == "x"
        return None

    # GitHub-style task lists.
    for li in soup.find_all("li"):
        checked = _consume_task_list_marker(li)
        if checked is None:
            continue
        checkbox = soup.new_tag("input", type="checkbox")
        if checked:
            checkbox["checked"] = "checked"
        checkbox["disabled"] = "disabled"
        li.insert(0, checkbox)
        li["class"] = list(set(li.get("class", []) + ["task-list-item"]))
        if li.parent and li.parent.name in {"ul", "ol"}:
            li.parent["class"] = list(set(li.parent.get("class", []) + ["task-list"]))

    # Explicit page break marker: <div class="page-break"></div> or ---page---
    for div in soup.find_all("div", class_=lambda c: c and "page-break" in c):
        div["class"] = list(set(div.get("class", []) + ["md2pdf-page-break"]))

    # Render HTML details/summary as expanded PDF-friendly disclosure blocks.
    for details in soup.find_all("details"):
        details["open"] = "open"
        details["class"] = list(set(details.get("class", []) + ["md2pdf-details"]))
        summary = details.find("summary")
        if summary is not None:
            summary["class"] = list(set(summary.get("class", []) + ["md2pdf-summary"]))

    enhance_accessibility_semantics(soup)
    return str(soup), reference_diagnostics + citation_diagnostics


PAGEBREAK_COMMENT_RE = re.compile(r"<!--\s*(?:pagebreak|page-break|newpage)\s*-->", re.I)
PAGEBREAK_CONTAINER_LINE_RE = re.compile(r"^:::\s*(?:pagebreak|page-break|newpage)\s*$", re.I)
PAGEBREAK_CONTAINER_CLOSE_RE = re.compile(r"^:::\s*$")
PAGEBREAK_MARKER_LINE_RE = re.compile(r"^---page---$", re.I)


def _line_ending(line: str) -> str:
    return "\n" if line.endswith("\n") else ""


def preprocess_pdf_directives(markdown: str) -> str:
    """Normalize lightweight PDF layout directives outside Markdown code fences.

    Documentation often needs to show the directive syntax inside fenced code
    blocks. A line-aware pass keeps those examples literal while still allowing
    authors to place page breaks in the real document body.
    """
    output: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    lines = markdown.splitlines(keepends=True)
    i = 0

    while i < len(lines):
        line = lines[i]
        next_in_fence, next_fence_char, next_fence_len = _fence_transition(
            line, in_fence, fence_char, fence_len
        )
        fence_changed = (next_in_fence, next_fence_char, next_fence_len) != (
            in_fence,
            fence_char,
            fence_len,
        )

        if fence_changed:
            in_fence, fence_char, fence_len = next_in_fence, next_fence_char, next_fence_len
            output.append(line)
            i += 1
            continue

        if in_fence:
            output.append(line)
            i += 1
            continue

        stripped = line.strip()
        ending = _line_ending(line)

        if PAGEBREAK_MARKER_LINE_RE.match(stripped):
            output.append(f'<div class="md2pdf-page-break"></div>{ending}')
            i += 1
            continue

        if PAGEBREAK_COMMENT_RE.fullmatch(stripped):
            output.append(f'<div class="md2pdf-page-break"></div>{ending}')
            i += 1
            continue

        if PAGEBREAK_CONTAINER_LINE_RE.match(stripped):
            if i + 1 < len(lines) and PAGEBREAK_CONTAINER_CLOSE_RE.match(lines[i + 1].strip()):
                output.append(f'<div class="md2pdf-page-break"></div>{ending}')
                i += 2
                continue

        output.append(PAGEBREAK_COMMENT_RE.sub('<div class="md2pdf-page-break"></div>', line))
        i += 1

    return "".join(output)


def _heading_source_lines(markdown: str, *, line_offset: int = 0) -> tuple[int, ...]:
    """Return one-based source lines for Markdown headings in render order.

    The mapping is collected before preprocessing so editor navigation points to
    the user's original buffer. Raw HTML headings intentionally have no mapping,
    because they do not have a reliable Markdown token range.
    """

    parser = MarkdownIt(
        "gfm-like",
        {"html": True, "linkify": False, "typographer": True},
    )
    parser.enable(["table", "strikethrough"])
    lines: list[int] = []
    for token in parser.parse(markdown):
        if token.type != "heading_open" or not token.map:
            continue
        lines.append(int(token.map[0]) + 1 + max(0, int(line_offset)))
    return tuple(lines)


def _source_map_from_html(html_text: str) -> tuple[dict[str, object], ...]:
    soup = BeautifulSoup(html_text, "html.parser")
    items: list[dict[str, object]] = []
    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        raw_line = heading.get("data-source-line")
        heading_id = str(heading.get("id") or "")
        if not raw_line or not heading_id:
            continue
        try:
            source_line = int(str(raw_line))
        except ValueError:
            continue
        items.append(
            {
                "id": heading_id,
                "line": max(1, source_line),
                "level": int(heading.name[1]),
                "title": heading.get_text(" ", strip=True).removesuffix("#").strip(),
            }
        )
    return tuple(items)


def render_markdown(
    markdown: str,
    *,
    toc: bool = False,
    toc_depth: int = 6,
    code_style: str | None = None,
    appearance_style: str | None = None,
    appearance_mode: str | None = None,
    language: str | None = None,
    unsafe_html: bool = False,
    allow_remote_images: bool = False,
    references_enabled: bool | None = None,
    numbering_scope: str | None = None,
    list_of_figures: bool | None = None,
    list_of_tables: bool | None = None,
    list_of_equations: bool | None = None,
    list_of_listings: bool | None = None,
    defer_reference_resolution: bool = False,
    citations_enabled: bool | None = None,
    citation_style: str | None = None,
    bibliography_title: str | None = None,
    bibliography_include_uncited: bool | None = None,
    bibliography_library: BibliographyLibrary | None = None,
    defer_citation_resolution: bool = False,
    source_path: Path | None = None,
) -> MarkdownRenderResult:
    markdown = markdown.removeprefix("\ufeff")
    metadata, markdown_body = extract_frontmatter(markdown)
    source_prefix = markdown[: max(0, len(markdown) - len(markdown_body))]
    heading_source_lines = _heading_source_lines(
        markdown_body,
        line_offset=source_prefix.count("\n"),
    )
    if language is not None:
        metadata["lang"] = normalize_language(language, "auto")
    if code_style is None:
        metadata_appearance = appearance_from_metadata(metadata)
        appearance = resolve_appearance(
            style=appearance_style or metadata_appearance.style,
            mode=appearance_mode or metadata_appearance.mode,
        )
        code_style = code_style_for_appearance(appearance.style, appearance.mode)
    title = guess_title(markdown_body, metadata)
    lang = normalize_language(metadata.get("lang"), "auto")

    markdown_body = preprocess_pdf_directives(markdown_body)
    markdown_body, footnotes = extract_footnotes(markdown_body)
    footnote_entries = _normalize_footnotes(footnotes)
    markdown_body, protected_code = _protect_code_regions(markdown_body)
    markdown_body = replace_footnote_refs(
        markdown_body,
        footnotes=footnote_entries,
        lang=lang,
        text_hint=markdown_body,
    )
    markdown_body = protect_and_transform_math(markdown_body)
    markdown_body = _restore_code_regions(markdown_body, protected_code)

    md = MarkdownIt(
        "gfm-like",
        {
            "html": True,
            "linkify": False,
            "typographer": True,
        },
    )
    md.enable(["table", "strikethrough"])
    fence_reference_diagnostics: list[Diagnostic] = []

    def render_fence(tokens: list[Any], idx: int, options: dict[str, Any], env: dict[str, Any]) -> str:
        """Render fenced code blocks as complete figures, not nested inside <pre><code>.

        markdown-it wraps custom highlighter output unless it starts with <pre>. Our
        highlighter returns a semantic <figure> with a separate language caption, so
        using a renderer rule prevents invalid <pre><code><figure> nesting. That
        nesting used to be normalized later as raw text and could turn ```c into
        a literal leading "C" inside the code content.
        """
        token = tokens[idx]
        fence_info = parse_code_fence_info(token.info)
        reference_labels = list(fence_info.get("reference_labels") or [])
        if len(reference_labels) > 1:
            fence_reference_diagnostics.append(
                Diagnostic(
                    "MARDAS-E604",
                    "error",
                    f"Code listing has more than one reference label: {', '.join(reference_labels)}",
                    path=source_path,
                    hint="Keep exactly one semantic label on each fenced code block.",
                )
            )
        invalid_label = str(fence_info.get("invalid_reference_label") or "")
        if invalid_label:
            fence_reference_diagnostics.append(
                Diagnostic(
                    "MARDAS-E605",
                    "error",
                    f"Invalid reference label in code fence: {invalid_label}",
                    path=source_path,
                    hint=(
                        "Use a label such as {#lst:training-loop}; names may contain "
                        "letters, digits, dots, underscores, and hyphens and must end "
                        "with a letter or digit."
                    ),
                )
            )
        lang = fence_info["language"]
        if is_mermaid_language(lang):
            return mermaid_placeholder(
                token.content,
                fence_info["title"] or None,
                fence_info["reference_label"] or None,
            ) + "\n"
        return highlight_code(
            token.content,
            lang,
            fence_info["attrs"],
            code_style=code_style,
            caption=fence_info["title"] or None,
            linenos=bool(fence_info["linenos"]),
            highlight_lines=fence_info["highlight_lines"],
            line_start=int(fence_info.get("line_start") or 1),
            reference_label=fence_info["reference_label"] or None,
        ) + "\n"

    md.renderer.rules["fence"] = render_fence
    heading_line_iter = iter(heading_source_lines)

    def render_heading_open(
        tokens: list[Any],
        idx: int,
        options: dict[str, Any],
        env: dict[str, Any],
    ) -> str:
        source_line = next(heading_line_iter, None)
        if source_line is not None:
            tokens[idx].attrSet("data-source-line", str(max(1, int(source_line))))
        return md.renderer.renderToken(tokens, idx, options, env)

    md.renderer.rules["heading_open"] = render_heading_open

    body_html = md.render(markdown_body)
    body_html = append_footnotes(body_html, footnote_entries, md, lang=lang, text_hint=markdown_body)
    if not unsafe_html:
        body_html = sanitize_html(body_html)
    body_html = block_local_file_links(body_html)
    body_html, toc_entries = add_heading_ids(
        body_html,
        toc_depth=toc_depth,
    )
    text_hint = BeautifulSoup(body_html, "html.parser").get_text(" ", strip=True)
    toc_html = build_toc(toc_entries, toc, lang=lang, text_hint=text_hint)

    raw_reference_metadata = metadata.get("references")
    reference_metadata = raw_reference_metadata if isinstance(raw_reference_metadata, dict) else {}

    def metadata_bool(explicit: bool | None, key: str, fallback: bool = False) -> bool:
        if explicit is not None:
            return bool(explicit)
        value = reference_metadata.get(key, metadata.get(key, fallback))
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    if references_enabled is None:
        if isinstance(raw_reference_metadata, bool):
            resolved_references_enabled = raw_reference_metadata
        else:
            resolved_references_enabled = metadata_bool(None, "enabled", False)
    else:
        resolved_references_enabled = bool(references_enabled)

    raw_citation_metadata = metadata.get("citations")
    citation_metadata = raw_citation_metadata if isinstance(raw_citation_metadata, dict) else {}
    if citations_enabled is None:
        if isinstance(raw_citation_metadata, bool):
            resolved_citations_enabled = raw_citation_metadata
        else:
            citation_enabled_value = citation_metadata.get(
                "enabled", metadata.get("citations_enabled")
            )
            if citation_enabled_value is None:
                resolved_citations_enabled = bool(
                    bibliography_library and bibliography_library.entries
                )
            elif isinstance(citation_enabled_value, str):
                resolved_citations_enabled = citation_enabled_value.strip().lower() in {
                    "1", "true", "yes", "on"
                }
            else:
                resolved_citations_enabled = bool(citation_enabled_value)
    else:
        resolved_citations_enabled = bool(citations_enabled)

    body_html, reference_diagnostics = postprocess_html(
        body_html,
        code_style=code_style,
        lang=lang,
        references_enabled=resolved_references_enabled,
        citations_enabled=resolved_citations_enabled,
        source_path=source_path,
    )
    if resolved_references_enabled and fence_reference_diagnostics:
        reference_diagnostics = tuple(fence_reference_diagnostics) + reference_diagnostics
    if not allow_remote_images:
        body_html = block_remote_images(body_html)

    resolved_numbering_scope = str(
        numbering_scope
        or reference_metadata.get("numbering_scope")
        or reference_metadata.get("numbering")
        or metadata.get("numbering_scope")
        or "global"
    )
    reference_lists_html = ""
    reference_objects: tuple[dict[str, object], ...] = ()
    if resolved_references_enabled:
        from .references import ReferenceOptions, resolve_cross_references

        if not defer_reference_resolution:
            resolved = resolve_cross_references(
                body_html,
                options=ReferenceOptions(
                    enabled=True,
                    numbering_scope=resolved_numbering_scope,
                    list_of_figures=metadata_bool(list_of_figures, "list_of_figures"),
                    list_of_tables=metadata_bool(list_of_tables, "list_of_tables"),
                    list_of_equations=metadata_bool(list_of_equations, "list_of_equations"),
                    list_of_listings=metadata_bool(list_of_listings, "list_of_listings"),
                ),
                lang=lang,
                path=source_path,
            )
            body_html = resolved.body_html
            reference_lists_html = resolved.lists_html
            reference_objects = tuple(item.to_dict() for item in resolved.objects)
            reference_diagnostics = reference_diagnostics + resolved.diagnostics

    bibliography_html = ""
    citation_entries: tuple[dict[str, object], ...] = ()
    cited_keys: tuple[str, ...] = ()
    if resolved_citations_enabled:
        from .citations import BibliographyLibrary, CitationOptions, resolve_citations

        # An empty bibliography is only a problem for a document that actually
        # cites something, and resolution says so per key and per location.
        # Failing up front instead meant every preset that switches citations on
        # — "Academic paper" does — refused to render an ordinary Markdown file
        # that cites nothing, for a bibliography it never needed.
        if bibliography_library is None:
            bibliography_library = BibliographyLibrary({})
        if not defer_citation_resolution:
            citation_metadata_style = citation_metadata.get(
                "style", metadata.get("citation_style", "author-date")
            )
            resolved_citations = resolve_citations(
                body_html,
                library=bibliography_library,
                options=CitationOptions(
                    enabled=True,
                    style=str(citation_style or citation_metadata_style or "author-date"),
                    title=(
                        bibliography_title
                        if bibliography_title is not None
                        else citation_metadata.get(
                            "bibliography_title", metadata.get("bibliography_title")
                        )
                    ),
                    include_uncited=(
                        bool(bibliography_include_uncited)
                        if bibliography_include_uncited is not None
                        else bool(
                            citation_metadata.get(
                                "include_uncited", metadata.get("bibliography_include_uncited", False)
                            )
                        )
                    ),
                ),
                lang=lang,
                path=source_path,
            )
            body_html = resolved_citations.body_html
            bibliography_html = resolved_citations.bibliography_html
            cited_keys = resolved_citations.cited_keys
            citation_entries = tuple(item.to_dict() for item in resolved_citations.entries)
            reference_diagnostics = reference_diagnostics + resolved_citations.diagnostics

    formatter = CodeHtmlFormatter(code_style)
    pygments_css = formatter.get_style_defs(".codehilite")
    return MarkdownRenderResult(
        body_html=body_html,
        metadata=metadata,
        title=title,
        pygments_css=pygments_css,
        toc_html=toc_html,
        toc_entries=toc_entries,
        reference_lists_html=reference_lists_html,
        reference_objects=reference_objects,
        bibliography_html=bibliography_html,
        bibliography_sources=(
            bibliography_library.sources if bibliography_library is not None else ()
        ),
        citation_entries=citation_entries,
        cited_keys=cited_keys,
        diagnostics=reference_diagnostics,
        source_map=_source_map_from_html(body_html),
    )


def render_markdown_text(
    text: str,
    *,
    source_path: str | Path,
    toc: bool = False,
    toc_depth: int = 6,
    code_style: str | None = None,
    appearance_style: str | None = None,
    appearance_mode: str | None = None,
    language: str | None = None,
    unsafe_html: bool = False,
    allow_remote_images: bool = False,
    document_root: str | Path | None = None,
    references_enabled: bool | None = None,
    numbering_scope: str | None = None,
    list_of_figures: bool | None = None,
    list_of_tables: bool | None = None,
    list_of_equations: bool | None = None,
    list_of_listings: bool | None = None,
    defer_reference_resolution: bool = False,
    citations_enabled: bool | None = None,
    bibliography_sources: Sequence[Path] | None = None,
    bibliography_library: BibliographyLibrary | None = None,
    citation_style: str | None = None,
    bibliography_title: str | None = None,
    bibliography_include_uncited: bool | None = None,
    defer_citation_resolution: bool = False,
) -> MarkdownRenderResult:
    """Render unsaved Markdown while resolving assets relative to its intended path.

    Desktop editors must validate and preview dirty buffers without overwriting the
    user's file.  ``source_path`` supplies the same trust boundary and relative
    asset root used by :func:`render_markdown_file` while ``text`` remains purely
    in memory.
    """

    input_path = Path(source_path).expanduser().resolve(strict=False)
    source_diagnostics: tuple[Diagnostic, ...] = ()
    resolved_sources: list[Path] = []
    if bibliography_sources is not None:
        resolved_sources = [Path(item).expanduser().resolve(strict=False) for item in bibliography_sources]
    else:
        try:
            source_metadata, _body = extract_frontmatter(text)
        except MarkdownInputError:
            source_metadata = {}
        raw_sources = source_metadata.get("bibliography")
        citation_meta = source_metadata.get("citations")
        if raw_sources is None and isinstance(citation_meta, dict):
            raw_sources = citation_meta.get("sources")
        if isinstance(raw_sources, (str, Path)):
            raw_sources = [raw_sources]
        if isinstance(raw_sources, list):
            root = Path(document_root).resolve() if document_root is not None else input_path.parent
            for item in raw_sources:
                candidate = Path(str(item)).expanduser()
                if candidate.is_absolute():
                    source_diagnostics += (
                        Diagnostic(
                            "MARDAS-E701",
                            "error",
                            "Front-matter bibliography paths must be relative to the document root.",
                            path=input_path,
                        ),
                    )
                    continue
                candidate = (input_path.parent / candidate).resolve(strict=False)
                try:
                    candidate.relative_to(root)
                except ValueError:
                    source_diagnostics += (
                        Diagnostic(
                            "MARDAS-E701",
                            "error",
                            "Front-matter bibliography path escapes the document root.",
                            path=candidate,
                        ),
                    )
                    continue
                resolved_sources.append(candidate)
    if bibliography_library is None and resolved_sources:
        from .citations import load_bibliography

        bibliography_library, bibliography_diagnostics = load_bibliography(resolved_sources)
        source_diagnostics += bibliography_diagnostics

    result = render_markdown(
        text,
        toc=toc,
        toc_depth=toc_depth,
        code_style=code_style,
        appearance_style=appearance_style,
        appearance_mode=appearance_mode,
        language=language,
        unsafe_html=unsafe_html,
        allow_remote_images=allow_remote_images,
        references_enabled=references_enabled,
        numbering_scope=numbering_scope,
        list_of_figures=list_of_figures,
        list_of_tables=list_of_tables,
        list_of_equations=list_of_equations,
        list_of_listings=list_of_listings,
        defer_reference_resolution=defer_reference_resolution,
        citations_enabled=citations_enabled,
        citation_style=citation_style,
        bibliography_title=bibliography_title,
        bibliography_include_uncited=bibliography_include_uncited,
        bibliography_library=bibliography_library,
        defer_citation_resolution=defer_citation_resolution,
        source_path=input_path,
    )
    result.diagnostics = source_diagnostics + result.diagnostics
    result.body_html = embed_local_images(
        result.body_html,
        input_path.parent,
        document_root=document_root,
        allow_remote_images=allow_remote_images,
    )
    return result


def render_markdown_file(
    path: str | Path,
    *,
    toc: bool = False,
    toc_depth: int = 6,
    code_style: str | None = None,
    appearance_style: str | None = None,
    appearance_mode: str | None = None,
    language: str | None = None,
    unsafe_html: bool = False,
    allow_remote_images: bool = False,
    document_root: str | Path | None = None,
    references_enabled: bool | None = None,
    numbering_scope: str | None = None,
    list_of_figures: bool | None = None,
    list_of_tables: bool | None = None,
    list_of_equations: bool | None = None,
    list_of_listings: bool | None = None,
    defer_reference_resolution: bool = False,
    citations_enabled: bool | None = None,
    bibliography_sources: Sequence[Path] | None = None,
    bibliography_library: BibliographyLibrary | None = None,
    citation_style: str | None = None,
    bibliography_title: str | None = None,
    bibliography_include_uncited: bool | None = None,
    defer_citation_resolution: bool = False,
) -> MarkdownRenderResult:
    input_path = Path(path)
    text = input_path.read_text(encoding="utf-8-sig")
    return render_markdown_text(
        text,
        source_path=input_path,
        toc=toc,
        toc_depth=toc_depth,
        code_style=code_style,
        appearance_style=appearance_style,
        appearance_mode=appearance_mode,
        language=language,
        unsafe_html=unsafe_html,
        allow_remote_images=allow_remote_images,
        document_root=document_root,
        references_enabled=references_enabled,
        numbering_scope=numbering_scope,
        list_of_figures=list_of_figures,
        list_of_tables=list_of_tables,
        list_of_equations=list_of_equations,
        list_of_listings=list_of_listings,
        defer_reference_resolution=defer_reference_resolution,
        citations_enabled=citations_enabled,
        bibliography_sources=bibliography_sources,
        bibliography_library=bibliography_library,
        citation_style=citation_style,
        bibliography_title=bibliography_title,
        bibliography_include_uncited=bibliography_include_uncited,
        defer_citation_resolution=defer_citation_resolution,
    )

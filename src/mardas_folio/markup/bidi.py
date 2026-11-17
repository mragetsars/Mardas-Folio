"""Language labels, text direction, numeral localization, and script isolation."""
from __future__ import annotations

import re
import unicodedata
from typing import Any
from bs4 import BeautifulSoup, NavigableString, Tag

ARABIC_RANGES = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")
LATIN_RANGES = re.compile(r"[A-Za-z]")
RTL_LANG_PREFIXES = ("ar", "fa", "he", "iw", "ku", "ps", "sd", "ug", "ur", "yi")
ASCII_DIGIT_RE = re.compile(r"[0-9]")
ARABIC_DIGIT_RE = re.compile(r"[\u0660-\u0669\u06F0-\u06F9]")
PERSIAN_PUNCTUATION_RE = re.compile(r"[،؛؟]")
ASCII_RTL_PUNCTUATION_RE = re.compile(r"[?,;](?=\s|$)")
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
RTL_ISOLATE_RUN_RE = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]"
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF0-9\u200c\u200d]*"
    r"(?:[ \t]+[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF0-9]"
    r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF0-9\u200c\u200d]*)*"
)









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


def isolate_rtl_phrase_lists_in_ltr_prose(soup: BeautifulSoup) -> None:
    """Keep comma-separated Persian phrases in the source order of English prose."""
    contexts = {
        id(tag)
        for tag in soup.find_all(class_="md2pdf-mixed-prose")
        if tag.get("dir") == "ltr"
        and "," in tag.get_text()
        and sum(
            strong_direction_counts(phrase)[0] > 0
            for phrase in RTL_ISOLATE_RUN_RE.findall(tag.get_text())
        ) > 1
    }
    if not contexts:
        return
    for node in list(soup.find_all(string=True)):
        parent = node.parent if isinstance(node.parent, Tag) else None
        if (
            parent is None
            or _inside_tag(parent, LTR_ISOLATE_SKIP_TAGS)
            or _inside_class(parent, LTR_ISOLATE_SKIP_CLASSES | {"md2pdf-rtl-isolate"})
        ):
            continue
        context = next(
            (ancestor for ancestor in _parent_chain(parent) if ancestor.name in LTR_ISOLATE_CONTEXT_TAGS),
            None,
        )
        if context is None or id(context) not in contexts:
            continue
        text = str(node)
        position = 0
        fragments: list[str | Tag] = []
        for match in RTL_ISOLATE_RUN_RE.finditer(text):
            if strong_direction_counts(match.group())[0] == 0:
                continue
            if match.start() > position:
                fragments.append(text[position:match.start()])
            span = soup.new_tag("span")
            span["class"] = ["md2pdf-rtl-isolate"]
            span["dir"] = "rtl"
            span.string = match.group()
            fragments.append(span)
            position = match.end()
        if not fragments:
            continue
        if position < len(text):
            fragments.append(text[position:])
        for fragment in reversed(fragments):
            if isinstance(fragment, str):
                if fragment:
                    node.insert_after(NavigableString(fragment))
            else:
                node.insert_after(fragment)
        node.extract()


def _dir_for_profile(profile: str) -> str:
    return profile if profile in {"rtl", "ltr"} else "auto"

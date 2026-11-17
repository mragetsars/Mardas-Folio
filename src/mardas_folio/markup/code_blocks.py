"""Fenced-code parsing, highlighting, and code-block HTML normalization."""

from __future__ import annotations

import html
import re
from typing import Any

from bs4 import BeautifulSoup, Tag
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound

from .bidi import has_latin as has_latin
from .bidi import has_persian as has_persian

HIGHLIGHT_TRAILING_NEWLINE_RE = re.compile(
    r'(<span class="hll">.*?)(\r?\n)(</span>)',
    re.DOTALL,
)
CODE_FENCE_BRACE_RE = re.compile(r"\{(?P<spec>[^}]*)\}")
CODE_FENCE_KV_RE = re.compile(
    r"(?P<key>[A-Za-z][\w-]*)\s*=\s*"
    r"(?:(?P<quote>[\"'])(?P<quoted>.*?)(?P=quote)|(?P<bare>[^\s}]+))"
)
CODE_FENCE_ATTR_CLASS_RE = re.compile(r"(?<!\S)\.(?P<class>[A-Za-z_][\w.-]*)")
CODE_FENCE_LABEL_RE = re.compile(
    r"(?:^|[\s{])#(?P<label>(?:fig|tbl|eq|lst):[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?)(?=[\s}]|$)"
)
CODE_FENCE_LABEL_CANDIDATE_RE = re.compile(r"(?:^|[\s{])#(?P<label>(?:fig|tbl|eq|lst):[^\s}]*)")
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


def _parse_line_highlights(spec: str | None) -> list[int]:
    if not spec:
        return []
    values: set[int] = set()
    cleaned = str(spec).strip().strip("{}[]()\"'").replace(";", ",")
    for part in re.split(r"[,\s]+", cleaned):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = [chunk.strip() for chunk in part.split("-", 1)]
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
        lexer = (
            get_lexer_by_name(language, stripall=False) if language else TextLexer(stripall=False)
        )
    except ClassNotFound:
        lexer = TextLexer(stripall=False)
        label = language or "text"
    normalized_highlight_lines = highlight_lines or []
    if (
        line_start > 1
        and normalized_highlight_lines
        and all(line >= line_start for line in normalized_highlight_lines)
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
        f"{html.escape(caption_value)}"
        "</figcaption>"
        if caption_value
        else ""
    )
    line_count = max(1, len(code.rstrip("\n").splitlines()))
    extra_attrs = f' data-lang="{html.escape(language)}"' if language else ""
    if reference_label:
        extra_attrs += f' data-md2pdf-label="{html.escape(reference_label)}"'
    extra_attrs += f' data-lines="{line_count}"'
    if linenos and line_start > 1:
        extra_attrs += f' data-line-start="{line_start}"'
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
    return f'<figure class="{classes}" dir="ltr"{extra_attrs}>{caption_html}{highlighted}</figure>'


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
    if re.search(
        r"^\s*(make|gdb|qemu|cat|dice|ksort|usort|pidtest|ptest|makenums)(\s|$)", stripped, re.M
    ):
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
        if any(
            skip_parent_classes.intersection(set(parent.get("class", [])))
            for parent in parents
            if isinstance(parent, Tag)
        ):
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

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup

from .appearance import DARK_PALETTES, DARK_STYLE_SURFACES, PALETTES, Appearance
from .diagnostics import Diagnostic
from .markdown import MarkdownRenderResult, normalize_language

_GENERIC_LINK_TEXT = {
    "click here",
    "click",
    "here",
    "read more",
    "more",
    "link",
    "learn more",
    "اینجا",
    "کلیک",
    "کلیک کنید",
    "بیشتر",
    "ادامه",
    "لینک",
}
_GENERIC_ALT_TEXT = {
    "image",
    "picture",
    "photo",
    "figure",
    "diagram",
    "تصویر",
    "عکس",
    "شکل",
    "نمودار",
}
_URL_TEXT_RE = re.compile(r"^(?:https?://|www\.)", re.IGNORECASE)
_ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_RAW_IMAGE_RE = re.compile(r"<img\b([^>]*)>", re.IGNORECASE)
_ALT_ATTR_RE = re.compile(r"\balt\s*=\s*([\"'])(.*?)\1", re.IGNORECASE | re.DOTALL)
_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)")
_RAW_LINK_RE = re.compile(r"<a\b[^>]*>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_FILENAME_ALT_RE = re.compile(r"^[^\s]+\.(?:png|jpe?g|gif|webp|svg|bmp|avif)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class AccessibilityAudit:
    diagnostics: tuple[Diagnostic, ...]
    metrics: dict[str, object]


def _relative_luminance(color: str) -> float:
    value = color.strip().lstrip("#")
    if len(value) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", value):
        raise ValueError(f"Unsupported color value: {color}")
    channels = [int(value[index : index + 2], 16) / 255.0 for index in (0, 2, 4)]

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: str, background: str) -> float:
    first = _relative_luminance(foreground)
    second = _relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def appearance_contrast_metrics(appearance: Appearance) -> dict[str, object]:
    if appearance.mode == "dark":
        palette = DARK_PALETTES[appearance.palette]
        surface = DARK_STYLE_SURFACES[appearance.style]
        page = surface["page"]
        ink = surface["ink"]
        muted = surface["muted"]
    else:
        palette = PALETTES[appearance.palette]
        page = "#ffffff"
        ink = "#0f172a"
        muted = "#475569"
    return {
        "style": appearance.style,
        "palette": appearance.palette,
        "mode": appearance.mode,
        "page_color": page,
        "text_color": ink,
        "muted_color": muted,
        "accent_color": palette["accent"],
        "text_contrast": round(contrast_ratio(ink, page), 2),
        "muted_contrast": round(contrast_ratio(muted, page), 2),
        "accent_contrast": round(contrast_ratio(palette["accent"], page), 2),
    }


def _mask_inline_code(line: str) -> str:
    """Replace matched Markdown code spans with spaces while preserving columns."""
    output: list[str] = []
    index = 0
    while index < len(line):
        marker_match = re.search(r"`+", line[index:])
        if marker_match is None:
            output.append(line[index:])
            break
        start = index + marker_match.start()
        marker = marker_match.group(0)
        content_start = start + len(marker)
        close = line.find(marker, content_start)
        if close == -1:
            output.append(line[index:])
            break
        output.append(line[index:start])
        end = close + len(marker)
        output.append(" " * (end - start))
        index = end
    return "".join(output)


def _source_lines(markdown: str) -> list[tuple[int, str]]:
    """Return source lines outside code blocks with inline code masked."""
    lines = markdown.removeprefix("\ufeff").splitlines()
    output: list[tuple[int, str]] = []
    fence: str | None = None
    frontmatter = bool(lines and lines[0].strip() == "---")
    frontmatter_closed = not frontmatter

    for index, line in enumerate(lines, start=1):
        if not frontmatter_closed:
            if index > 1 and line.strip() == "---":
                frontmatter_closed = True
            continue
        match = _FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker[0]
            elif marker[0] == fence:
                fence = None
            continue
        if fence is not None:
            continue
        if line.startswith("    ") or line.startswith("\t"):
            continue
        output.append((index, _mask_inline_code(line)))
    return output


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub("", value)).strip()


def _heading_diagnostics(path: Path, source_lines: Iterable[tuple[int, str]]) -> tuple[list[Diagnostic], int]:
    diagnostics: list[Diagnostic] = []
    headings: list[tuple[int, int, str]] = []
    for line_number, line in source_lines:
        match = _ATX_HEADING_RE.match(line.strip())
        if not match:
            continue
        headings.append((len(match.group(1)), line_number, match.group(2).strip()))

    previous_level: int | None = None
    for level, line_number, title in headings:
        if previous_level is not None and level > previous_level + 1:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-A101",
                    "warning",
                    f"Heading hierarchy jumps from level {previous_level} to level {level}: {title}",
                    path=path,
                    line=line_number,
                    hint="Use consecutive heading levels so assistive navigation preserves document structure.",
                )
            )
        previous_level = level

    h1_count = sum(1 for level, _line, _title in headings if level == 1)
    if not headings:
        diagnostics.append(
            Diagnostic(
                "MARDAS-A102",
                "warning",
                "Document contains no headings.",
                path=path,
                hint="Add a descriptive level-one heading and a logical hierarchy for long documents.",
            )
        )
    elif h1_count == 0:
        diagnostics.append(
            Diagnostic(
                "MARDAS-A103",
                "warning",
                "Document has headings but no level-one heading.",
                path=path,
                hint="Use one level-one heading for the document or chapter title.",
            )
        )
    elif h1_count > 1:
        diagnostics.append(
            Diagnostic(
                "MARDAS-A104",
                "info",
                f"Document contains {h1_count} level-one headings.",
                path=path,
                hint="Multiple level-one headings are valid for some reports, but verify the intended outline.",
            )
        )
    return diagnostics, len(headings)


def _image_diagnostics(path: Path, source_lines: Iterable[tuple[int, str]]) -> tuple[list[Diagnostic], int]:
    diagnostics: list[Diagnostic] = []
    count = 0
    for line_number, line in source_lines:
        for match in _MARKDOWN_IMAGE_RE.finditer(line):
            count += 1
            alt = match.group(1).strip()
            if not alt:
                diagnostics.append(
                    Diagnostic(
                        "MARDAS-A201",
                        "warning",
                        "Image has empty alternative text.",
                        path=path,
                        line=line_number,
                        column=match.start() + 1,
                        hint="Describe informative images; keep empty alt text only for genuinely decorative images.",
                    )
                )
            elif alt.casefold() in _GENERIC_ALT_TEXT or _FILENAME_ALT_RE.match(alt):
                diagnostics.append(
                    Diagnostic(
                        "MARDAS-A202",
                        "warning",
                        f"Image alternative text is not descriptive: {alt}",
                        path=path,
                        line=line_number,
                        column=match.start() + 1,
                        hint="Describe the information or purpose conveyed by the image.",
                    )
                )
            elif len(alt) > 240:
                diagnostics.append(
                    Diagnostic(
                        "MARDAS-A203",
                        "info",
                        "Image alternative text is unusually long.",
                        path=path,
                        line=line_number,
                        column=match.start() + 1,
                        hint="Move detailed explanation into nearby prose or a caption when practical.",
                    )
                )

        for match in _RAW_IMAGE_RE.finditer(line):
            count += 1
            attrs = match.group(1)
            alt_match = _ALT_ATTR_RE.search(attrs)
            if alt_match is None:
                diagnostics.append(
                    Diagnostic(
                        "MARDAS-A204",
                        "error",
                        "Raw HTML image is missing an alt attribute.",
                        path=path,
                        line=line_number,
                        column=match.start() + 1,
                        hint='Add alt="description" or alt="" for a decorative image.',
                    )
                )
    return diagnostics, count


def _link_diagnostics(path: Path, source_lines: Iterable[tuple[int, str]]) -> tuple[list[Diagnostic], int]:
    diagnostics: list[Diagnostic] = []
    count = 0
    for line_number, line in source_lines:
        candidates = [(m.start(), m.group(1)) for m in _MARKDOWN_LINK_RE.finditer(line)]
        candidates.extend((m.start(), _clean_text(m.group(1))) for m in _RAW_LINK_RE.finditer(line))
        for column, raw_text in candidates:
            count += 1
            text = _clean_text(raw_text)
            folded = text.casefold()
            if not text:
                diagnostics.append(
                    Diagnostic(
                        "MARDAS-A301",
                        "error",
                        "Link has no accessible text.",
                        path=path,
                        line=line_number,
                        column=column + 1,
                        hint="Provide link text that describes the destination or action.",
                    )
                )
            elif folded in _GENERIC_LINK_TEXT:
                diagnostics.append(
                    Diagnostic(
                        "MARDAS-A302",
                        "warning",
                        f"Link text is ambiguous outside its surrounding sentence: {text}",
                        path=path,
                        line=line_number,
                        column=column + 1,
                        hint="Use destination-specific text instead of 'click here' or equivalent wording.",
                    )
                )
            elif _URL_TEXT_RE.match(text):
                diagnostics.append(
                    Diagnostic(
                        "MARDAS-A303",
                        "info",
                        "Link displays a raw URL as its accessible name.",
                        path=path,
                        line=line_number,
                        column=column + 1,
                        hint="Use a concise human-readable label when the exact URL is not required.",
                    )
                )
    return diagnostics, count


def _rendered_semantic_diagnostics(path: Path, result: MarkdownRenderResult) -> tuple[list[Diagnostic], dict[str, int]]:
    diagnostics: list[Diagnostic] = []
    soup = BeautifulSoup(result.body_html, "html.parser")
    figures = soup.find_all("figure")
    images = soup.find_all("img")
    tables = soup.find_all("table")

    for image in images:
        if image.get("alt") is None:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-A205",
                    "error",
                    "Rendered image has no alt attribute.",
                    path=path,
                )
            )

    for figure in figures:
        classes = set(figure.get("class", []))
        if classes.intersection({"code-block", "mermaid-diagram"}):
            continue
        if figure.find("img") is not None and figure.find("figcaption", recursive=False) is None:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-A206",
                    "info",
                    "Informative figure has no visible caption.",
                    path=path,
                    hint="Add a caption when readers need context beyond the image alternative text.",
                )
            )

    for table in tables:
        classes = set(table.get("class", []))
        if "codehilitetable" in classes or table.get("role") == "presentation":
            continue
        header_cells = table.find_all("th")
        if not header_cells:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-A401",
                    "error",
                    "Table has no header cells.",
                    path=path,
                    hint="Use a Markdown header row or semantic <th> cells.",
                )
            )
        if table.find("caption", recursive=False) is None:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-A402",
                    "warning",
                    "Table has no caption.",
                    path=path,
                    hint="Add a concise table caption to identify its purpose.",
                )
            )

    return diagnostics, {
        "rendered_images": len(images),
        "rendered_figures": len(figures),
        "rendered_tables": len(tables),
    }


def audit_markdown_result(
    *,
    path: Path,
    markdown: str,
    result: MarkdownRenderResult,
    appearance: Appearance,
    configured_language: str | None = None,
) -> AccessibilityAudit:
    source_lines = _source_lines(markdown)
    diagnostics: list[Diagnostic] = []

    language = normalize_language(configured_language or result.metadata.get("lang"), "auto")
    if language in {"", "auto", "und"}:
        diagnostics.append(
            Diagnostic(
                "MARDAS-A001",
                "warning",
                "Document language is not declared explicitly.",
                path=path,
                hint="Set project.language or front-matter lang to a BCP 47 language tag such as fa-IR or en-US.",
            )
        )

    heading_diagnostics, heading_count = _heading_diagnostics(path, source_lines)
    image_diagnostics, source_image_count = _image_diagnostics(path, source_lines)
    link_diagnostics, link_count = _link_diagnostics(path, source_lines)
    semantic_diagnostics, semantic_metrics = _rendered_semantic_diagnostics(path, result)
    diagnostics.extend(heading_diagnostics)
    diagnostics.extend(image_diagnostics)
    diagnostics.extend(link_diagnostics)
    diagnostics.extend(semantic_diagnostics)

    contrast = appearance_contrast_metrics(appearance)
    if float(contrast["accent_contrast"]) < 4.5:
        diagnostics.append(
            Diagnostic(
                "MARDAS-A501",
                "warning",
                (
                    f"Theme accent contrast is {contrast['accent_contrast']}:1 against the page "
                    "background, below the WCAG 4.5:1 target for ordinary link text."
                ),
                path=path,
                hint="Choose a higher-contrast palette/mode or customize link styling before publication.",
            )
        )

    metrics: dict[str, object] = {
        "language": language,
        "headings": heading_count,
        "source_images": source_image_count,
        "links": link_count,
        **semantic_metrics,
        "contrast": contrast,
    }
    return AccessibilityAudit(tuple(diagnostics), metrics)


def diagnostic_counts(diagnostics: Iterable[Diagnostic]) -> dict[str, int]:
    counts = {"error": 0, "warning": 0, "info": 0}
    for item in diagnostics:
        counts[item.severity] += 1
    return counts

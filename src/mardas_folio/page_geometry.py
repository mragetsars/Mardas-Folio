"""Physical page dimensions and CSS units shared by configuration, preview and PDF."""

from __future__ import annotations

import re
from typing import Any

from .appearance import page_background, resolve_appearance
from .render_contracts import PdfOptions

CSS_PAGE_SIZE_RE = re.compile(
    r"^(?:[A-Za-z][A-Za-z0-9-]*(?:\s+(?:portrait|landscape))?|\d+(?:\.\d+)?(?:mm|cm|in|px|pt)\s+\d+(?:\.\d+)?(?:mm|cm|in|px|pt))$",
    re.IGNORECASE,
)

PLAYWRIGHT_NAMED_PAGE_FORMATS = {
    "letter",
    "legal",
    "tabloid",
    "ledger",
    "a0",
    "a1",
    "a2",
    "a3",
    "a4",
    "a5",
    "a6",
}
NAMED_PAGE_DIMENSIONS: dict[str, tuple[str, str]] = {
    "letter": ("8.5in", "11in"),
    "legal": ("8.5in", "14in"),
    "tabloid": ("11in", "17in"),
    "ledger": ("17in", "11in"),
    "a0": ("841mm", "1189mm"),
    "a1": ("594mm", "841mm"),
    "a2": ("420mm", "594mm"),
    "a3": ("297mm", "420mm"),
    "a4": ("210mm", "297mm"),
    "a5": ("148mm", "210mm"),
    "a6": ("105mm", "148mm"),
    "b0": ("1000mm", "1414mm"),
    "b1": ("707mm", "1000mm"),
    "b2": ("500mm", "707mm"),
    "b3": ("353mm", "500mm"),
    "b4": ("250mm", "353mm"),
    "b5": ("176mm", "250mm"),
    "b6": ("125mm", "176mm"),
}
SUPPORTED_CSS_PAGE_NAMES = set(NAMED_PAGE_DIMENSIONS)
MIN_PAGE_DIMENSION_MM = 10.0
MAX_PAGE_DIMENSION_MM = 5000.0
PAGE_SIZE_NAME_RE = re.compile(
    r"^(?P<name>[A-Za-z][A-Za-z0-9-]*)(?:\s+(?P<orientation>portrait|landscape))?$",
    re.IGNORECASE,
)

CUSTOM_PAGE_DIMENSIONS_RE = re.compile(
    r"^(?P<width>\d+(?:\.\d+)?(?:mm|cm|in|px|pt))\s+"
    r"(?P<height>\d+(?:\.\d+)?(?:mm|cm|in|px|pt))$",
    re.IGNORECASE,
)

CSS_LENGTH_RE = re.compile(r"^(?P<number>\d+(?:\.\d+)?)(?P<unit>mm|cm|in|px|pt)$", re.IGNORECASE)


def _css_length_mm(value: str) -> float:
    match = CSS_LENGTH_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"invalid CSS length: {value}")
    number = float(match.group("number"))
    unit = match.group("unit").lower()
    factors = {"mm": 1.0, "cm": 10.0, "in": 25.4, "px": 25.4 / 96.0, "pt": 25.4 / 72.0}
    return number * factors[unit]


def _validate_page_dimension(value: str) -> None:
    size_mm = _css_length_mm(value)
    if not MIN_PAGE_DIMENSION_MM <= size_mm <= MAX_PAGE_DIMENSION_MM:
        raise ValueError(
            f"page dimensions must be between {MIN_PAGE_DIMENSION_MM:g}mm and "
            f"{MAX_PAGE_DIMENSION_MM:g}mm"
        )


def _named_page_dimensions(value: str) -> tuple[str, str] | None:
    match = PAGE_SIZE_NAME_RE.fullmatch(value.strip())
    if not match:
        return None
    dimensions = NAMED_PAGE_DIMENSIONS.get(match.group("name").lower())
    if not dimensions:
        return None
    width, height = dimensions
    if (match.group("orientation") or "").lower() == "landscape":
        width, height = height, width
    return width, height


def validate_page_size(value: str | None) -> str:
    """Return a safe PDF page-size expression or raise ``ValueError``.

    Chromium accepts a broad CSS ``@page size`` grammar, but treating arbitrary
    words as valid page sizes makes typos such as ``not-a-size`` silently fall
    back to A4. Keep explicit dimensions flexible, while named sizes are limited
    to the documented built-in families.
    """
    text = (value or "A4").strip()
    if not text:
        return "A4"

    dimension_match = CUSTOM_PAGE_DIMENSIONS_RE.fullmatch(text)
    if dimension_match:
        _validate_page_dimension(dimension_match.group("width"))
        _validate_page_dimension(dimension_match.group("height"))
        return text

    name_match = PAGE_SIZE_NAME_RE.fullmatch(text)
    if name_match:
        name = name_match.group("name")
        orientation = name_match.group("orientation")
        if name.lower() in SUPPORTED_CSS_PAGE_NAMES:
            return f"{name} {orientation.lower()}" if orientation else name

    raise ValueError(
        "page size must be a supported named size such as A4 or Letter, "
        'an optional orientation such as "A4 landscape", or explicit dimensions such as "210mm 297mm"'
    )


def _playwright_page_size_kwargs(value: str | None) -> dict[str, str]:
    """Return Playwright-compatible page size arguments.

    Playwright's ``format`` parameter accepts named formats such as A4 and
    Letter, but it rejects CSS size expressions like ``210mm 297mm`` or
    ``A4 landscape``. Those values are already emitted in a late ``@page`` CSS
    rule and honored through ``prefer_css_page_size=True``. For explicit
    width/height pairs we also pass the dimensions directly for renderer
    compatibility.
    """
    text = _css_page_size(value)
    dimension_match = CUSTOM_PAGE_DIMENSIONS_RE.match(text)
    if dimension_match:
        return {
            "width": dimension_match.group("width"),
            "height": dimension_match.group("height"),
        }
    named_dimensions = _named_page_dimensions(validate_page_size(value))
    if named_dimensions:
        return {"width": named_dimensions[0], "height": named_dimensions[1]}
    return {}


def _css_page_size(value: str | None) -> str:
    """Return a safe CSS @page size value.

    Playwright is asked to prefer CSS page size so the style can control print
    margins. Therefore the selected CLI/GUI page size must also be emitted as a
    late CSS override; otherwise the style-level ``@page { size: A4; }`` wins.
    """
    try:
        validated = validate_page_size(value)
        named_dimensions = _named_page_dimensions(validated)
        if named_dimensions:
            return f"{named_dimensions[0]} {named_dimensions[1]}"
        return validated
    except ValueError:
        return "210mm 297mm"


def page_geometry(options: PdfOptions) -> dict[str, Any]:
    """The physical sheet the PDF will be printed on, in millimetres.

    Everything a paginated on-screen preview needs to be the same shape as the
    file: the trimmed page, the margin box the text sits in, and therefore how
    much content one page can hold. Values are millimetres because that is the
    unit both the page sizes and the margin options are expressed in, and it is
    the only unit that survives the trip to a browser at an arbitrary zoom.
    """

    css_size = _css_page_size(options.page_size)
    match = CUSTOM_PAGE_DIMENSIONS_RE.fullmatch(css_size)
    if match:
        width_mm = _css_length_mm(match.group("width"))
        height_mm = _css_length_mm(match.group("height"))
    else:  # pragma: no cover - _css_page_size always returns explicit dimensions
        width_mm, height_mm = 210.0, 297.0

    def margin(value: str, fallback: float) -> float:
        try:
            return _css_length_mm(value)
        except ValueError:
            return fallback

    top = margin(options.margin_top, 18.0)
    bottom = margin(options.margin_bottom, 20.0)
    side = margin(options.margin_x, 16.0)
    # A margin box has to leave something to print in; a document configured
    # with margins wider than the paper is a configuration error, not a page.
    content_width = max(width_mm - (side * 2), 10.0)
    content_height = max(height_mm - top - bottom, 10.0)
    return {
        "size": css_size,
        "width_mm": round(width_mm, 3),
        "height_mm": round(height_mm, 3),
        "margin_top_mm": round(top, 3),
        "margin_bottom_mm": round(bottom, 3),
        "margin_x_mm": round(side, 3),
        "content_width_mm": round(content_width, 3),
        "content_height_mm": round(content_height, 3),
        "orientation": "landscape" if width_mm > height_mm else "portrait",
        # The sheet's own colour. A preview draws paper that extends past the
        # text area, so without this it has to guess, and a guess that is close
        # but wrong reads as a coloured border around every page.
        "background": page_background(
            resolve_appearance(
                style=options.style,
                palette=options.palette,
                mode=options.mode,
            )
        ),
    }

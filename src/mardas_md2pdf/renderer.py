from __future__ import annotations

import base64
from contextlib import contextmanager
from functools import lru_cache
import hashlib
import html
import logging
import mimetypes
import os
import re
import secrets
import shutil
import stat
import tempfile
import threading
import unicodedata
import warnings
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any, Callable, Iterator

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    BooleanObject,
    DictionaryObject,
    NameObject,
    TextStringObject,
)

from .appearance import (
    Appearance,
    appearance_body_classes,
    appearance_from_metadata,
    footer_kind,
    math_scale_vars,
    palette_css,
    resolve_appearance,
    style_css_file,
)
from .brand_assets import product_logo_path
from .diagnostics import format_diagnostic, has_errors
from .markdown import MarkdownInputError, MarkdownRenderResult, render_markdown_file
from .pdf_navigation import (
    NamedDestinationMap,
    NavigationTracker,
    OutlineSourceEntry,
    add_pdf_outline as _add_pdf_outline,
    add_pdf_page_labels as _navigation_add_pdf_page_labels,
    copy_pdf_named_destinations as _copy_pdf_named_destinations,
    enforce_navigation_quality,
    heading_destination_names as _heading_destination_names,  # noqa: F401 - compatibility
    locate_outline_pages as _locate_outline_pages,
    pdf_page_texts as _pdf_page_texts,
    rewrite_pdf_link_annotation_destinations as _rewrite_pdf_link_annotation_destinations,
)
from .quality import (
    FontValidationError,
    MathJaxRenderError,
    RenderQualityError,
    RenderQualityLog,
    handle_quality_issue,
    profile_policy,
    validate_quality_profile,
)
from .runtime import resolved_chromium_path


LOGGER = logging.getLogger(__name__)


MAX_EMBED_ASSET_BYTES = 20 * 1024 * 1024
ALLOWED_EMBED_ASSET_MIME_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "image/bmp",
    "image/avif",
    "image/svg+xml",
}
ProgressCallback = Callable[[str, float], None]
CancellationCallback = Callable[[], bool]
BRANDING_MODES = ("off", "subtle", "full")
PRODUCT_BRAND_NAME = "Mardas MD2PDF"
PRODUCT_BRAND_FOOTER = "Markdown to PDF Engine"


class DocumentAssetError(ValueError):
    """Raised when document metadata references an unsafe local asset."""


class OutputPathError(ValueError):
    """Raised when conversion paths overlap or target invalid filesystem objects."""


class RenderCancelledError(RuntimeError):
    """Raised when a caller cancels rendering at a safe checkpoint."""


def validate_branding_mode(value: str | None) -> str:
    """Validate and normalize cover branding mode names."""
    normalized = str(value or "off").strip().lower()
    if normalized not in BRANDING_MODES:
        allowed = ", ".join(BRANDING_MODES)
        raise ValueError(f"must be one of: {allowed}")
    return normalized


def _check_cancel(options: "PdfOptions") -> None:
    callback = options.cancelled
    if callback is not None and callback():
        raise RenderCancelledError("PDF rendering was cancelled.")


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


@dataclass(slots=True)
class PdfOptions:
    input_path: Path
    output_path: Path
    title: str | None = None
    author: str | None = None
    description: str | None = None
    toc: bool = False
    toc_depth: int = 6
    toc_page_break: bool = False
    h1_page_break: bool = False
    debug_html: Path | None = None
    page_size: str = "A4"
    document_language: str | None = None
    document_direction: str | None = None
    margin_top: str = "18mm"
    margin_bottom: str = "20mm"
    margin_x: str = "16mm"
    font_dir: Path | None = None
    chromium_path: str | None = None
    chromium_sandbox: str = "auto"
    no_header_footer: bool = False
    no_mathjax: bool = False
    timeout_ms: int = 120_000
    style: str | None = None
    palette: str | None = None
    mode: str | None = None
    cover: bool = True
    cover_logo: Path | None = None
    cover_logo_enabled: bool = True
    branding: str | None = None
    brand_name: str | None = None
    brand_logo: Path | None = None
    brand_footer: str | None = None
    watermark_text: str | None = None
    watermark_image: Path | None = None
    watermark_opacity: float = 0.065
    watermark_width: str = "105mm"
    unsafe_html: bool = False
    allow_remote_assets: bool = False
    references_enabled: bool | None = None
    numbering_scope: str | None = None
    list_of_figures: bool | None = None
    list_of_tables: bool | None = None
    list_of_equations: bool | None = None
    list_of_listings: bool | None = None
    citations_enabled: bool | None = None
    bibliography_sources: tuple[Path, ...] = ()
    citation_style: str | None = None
    bibliography_title: str | None = None
    bibliography_include_uncited: bool | None = None
    quality_profile: str = "standard"
    math_error_policy: str | None = None
    font_error_policy: str | None = None
    navigation_error_policy: str | None = None
    required_fonts: tuple[str, ...] = ()
    quality_report: Path | None = None
    quality_log: RenderQualityLog = field(default_factory=RenderQualityLog, repr=False)
    progress: ProgressCallback | None = None
    cancelled: CancellationCallback | None = None


@lru_cache(maxsize=16)
def _asset_text(relative_path: str) -> str:
    return (resources.files("mardas_md2pdf") / "assets" / relative_path).read_text(encoding="utf-8")


def _asset_path(relative_path: str) -> Path:
    return Path(str(resources.files("mardas_md2pdf") / "assets" / relative_path))


def _font_faces(font_dir: Path | None) -> str:
    if not font_dir:
        return ""
    font_dir = font_dir.resolve()
    if not font_dir.exists() or not font_dir.is_dir():
        warnings.warn(
            f"Font directory not found; falling back to system fonts: {font_dir}",
            RuntimeWarning,
            stacklevel=2,
        )
        return ""
    candidates = {
        "Vazirmatn": [
            "Vazirmatn-Regular.woff2",
            "Vazirmatn[wght].woff2",
            "Vazirmatn-Regular.ttf",
            "Vazirmatn.ttf",
        ],
        "Vazirmatn Bold": [
            "Vazirmatn-Bold.woff2",
            "Vazirmatn-Bold.ttf",
        ],
    }
    chunks: list[str] = []
    for family, filenames in candidates.items():
        for filename in filenames:
            path = font_dir / filename
            if path.exists():
                url = path.as_uri()
                weight = "100 900" if "[wght]" in filename else ("800" if "Bold" in family else "400")
                family_name = "Vazirmatn"
                font_format = "truetype" if filename.lower().endswith(".ttf") else "woff2"
                chunks.append(
                    "@font-face {"
                    f"font-family: '{family_name}'; src: url('{url}') format('{font_format}'); "
                    f"font-weight: {weight}; font-style: normal; font-display: swap;"
                    "}"
                )
                break
    if not chunks:
        warnings.warn(
            f"No Vazirmatn font files found in {font_dir}; falling back to system fonts.",
            RuntimeWarning,
            stacklevel=2,
        )
    return "\n".join(chunks)


@lru_cache(maxsize=1)
def _mathjax_script() -> str:
    path = _asset_path("mathjax/tex-svg-full.js")
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _resolve_quality_options(options: PdfOptions) -> None:
    profile = validate_quality_profile(options.quality_profile)
    options.quality_profile = profile
    options.math_error_policy = profile_policy(profile, options.math_error_policy)
    options.font_error_policy = profile_policy(profile, options.font_error_policy)
    options.navigation_error_policy = profile_policy(profile, options.navigation_error_policy)
    required = tuple(dict.fromkeys(name.strip() for name in options.required_fonts if name.strip()))
    if profile == "strict-publication" and not required:
        required = ("Vazirmatn",)
    options.required_fonts = required
    options.quality_log.profile = profile


def _write_quality_report(options: PdfOptions) -> None:
    if options.quality_report is not None:
        options.quality_log.write(Path(options.quality_report))


def _enforce_quality_issue(
    options: PdfOptions,
    *,
    category: str,
    policy: str,
    message: str,
    details: dict[str, Any] | None = None,
    error_type: type[RenderQualityError] = RenderQualityError,
) -> None:
    try:
        handle_quality_issue(
            options.quality_log,
            category=category,
            policy=policy,
            message=message,
            details=details,
            error_type=error_type,
        )
    finally:
        _write_quality_report(options)


def _font_directory_manifest(font_dir: Path | None) -> list[dict[str, Any]]:
    if not font_dir or not Path(font_dir).is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(Path(font_dir).iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or path.suffix.lower() not in {".ttf", ".otf", ".woff", ".woff2"}:
            continue
        records.append(
            {
                "name": path.name,
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return records



def _resolved_appearance(metadata: dict[str, Any], options: PdfOptions) -> Appearance:
    metadata_appearance = appearance_from_metadata(metadata)
    return resolve_appearance(
        style=options.style or metadata_appearance.style,
        palette=options.palette or metadata_appearance.palette,
        mode=options.mode or metadata_appearance.mode,
    )




def _apply_resolved_appearance(metadata: dict[str, Any], options: PdfOptions) -> Appearance:
    """Resolve CLI/config/front-matter appearance once and persist it on options."""
    appearance = _resolved_appearance(metadata, options)
    options.style = appearance.style
    options.palette = appearance.palette
    options.mode = appearance.mode
    return appearance

def _style_css(appearance: Appearance) -> str:
    return _asset_text(style_css_file(appearance.style, appearance.mode))


def _path_uri(path: Path | None) -> str | None:
    if not path:
        return None
    return path.resolve().as_uri()


@lru_cache(maxsize=16)
def _cached_small_image_data_uri(
    path_text: str, mtime_ns: int, size: int, mime_type: str
) -> str:
    del mtime_ns, size
    encoded = base64.b64encode(Path(path_text).read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _image_data_uri(path: Path | None) -> str | None:
    """Embed local images as data URIs so Chromium PDF can render them reliably."""
    if not path:
        return None
    path = path.resolve()
    if not path.exists() or not path.is_file():
        return None
    try:
        mode = path.stat().st_mode
    except OSError:
        return None
    if not stat.S_ISREG(mode):
        return None
    size = path.stat().st_size
    if size > MAX_EMBED_ASSET_BYTES:
        warnings.warn(
            f"Skipping asset larger than {MAX_EMBED_ASSET_BYTES} bytes: {path}",
            RuntimeWarning,
            stacklevel=2,
        )
        return None
    mime_type = mimetypes.guess_type(str(path))[0] or ""
    if mime_type.lower() not in ALLOWED_EMBED_ASSET_MIME_TYPES:
        warnings.warn(
            f"Skipping non-image or unsupported embedded asset: {path}",
            RuntimeWarning,
            stacklevel=2,
        )
        return None
    stat_result = path.stat()
    if size <= 2 * 1024 * 1024:
        return _cached_small_image_data_uri(
            str(path), stat_result.st_mtime_ns, stat_result.st_size, mime_type
        )
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _default_logo_path(*, variant: str = "default") -> Path | None:
    """Return the packaged Mardas MD2PDF product logo for built-in branding."""
    return product_logo_path(variant=variant)


def _cover_logo_uri(options: PdfOptions) -> str | None:
    if not options.cover_logo_enabled:
        return None
    return _image_data_uri(options.cover_logo or options.brand_logo or _default_logo_path(variant="cover-label"))


def _metadata_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _metadata_nested_value(metadata: dict[str, Any], section: str, *keys: str) -> Any:
    nested = _metadata_dict(metadata.get(section))
    for key in keys:
        value = nested.get(key)
        if value not in (None, ""):
            return value
    return ""


@dataclass(slots=True)
class CoverBranding:
    mode: str
    name: str
    footer: str
    logo: Path | None
    product: bool = False


@dataclass(slots=True)
class FooterContext:
    title: str
    metadata: str = ""
    lang: str = "en"
    document_direction: str = "ltr"


def _resolve_cover_branding(metadata: dict[str, Any], options: PdfOptions, base_dir: Path) -> CoverBranding:
    branding_meta = _metadata_dict(metadata.get("branding"))
    explicit_mode = (
        options.branding
        or branding_meta.get("mode")
        or _first_metadata_value(metadata, "branding_mode", "brand_mode")
    )

    brand_name = (
        options.brand_name
        or _metadata_nested_value(metadata, "brand", "name", "title", "label")
        or branding_meta.get("name")
        or _first_metadata_value(metadata, "brand_name")
    )
    brand_footer = (
        options.brand_footer
        or _metadata_nested_value(metadata, "brand", "footer", "tagline", "subtitle")
        or branding_meta.get("footer")
        or branding_meta.get("tagline")
        or _first_metadata_value(metadata, "brand_footer", "brand_tagline")
    )

    logo_value = (
        _metadata_nested_value(metadata, "brand", "logo", "image")
        or branding_meta.get("logo")
        or branding_meta.get("image")
        or _first_metadata_value(metadata, "brand_logo")
    )
    metadata_brand_logo = _metadata_path(logo_value, base_dir)
    logo = options.brand_logo or metadata_brand_logo or options.cover_logo

    has_user_brand = bool(_stringify_metadata_value(brand_name) or _stringify_metadata_value(brand_footer) or logo)
    mode = validate_branding_mode(explicit_mode or ("full" if has_user_brand else "off"))

    product_brand = not has_user_brand
    name = _stringify_metadata_value(brand_name) or PRODUCT_BRAND_NAME
    footer = _stringify_metadata_value(brand_footer) or (PRODUCT_BRAND_FOOTER if product_brand else "")

    if not options.cover_logo_enabled:
        logo = None
    if product_brand and mode == "full" and logo is None:
        logo = _default_logo_path(variant="cover-label")

    return CoverBranding(mode=mode, name=name, footer=footer, logo=logo, product=product_brand)


def _brand_logo_html(branding: CoverBranding) -> str:
    logo_uri = _image_data_uri(branding.logo) if branding.logo else None
    if logo_uri:
        return f'<img class="md2pdf-cover__logo" src="{html.escape(logo_uri)}" alt="{html.escape(branding.name)} logo">'
    initial = (branding.name.strip()[:1] or "M").upper()
    return f'<span class="md2pdf-cover__logo md2pdf-cover__logo--fallback">{html.escape(initial)}</span>'


def _cover_brand_html(branding: CoverBranding) -> str:
    if branding.mode == "off":
        return ""
    if branding.mode == "subtle" and branding.product:
        return (
            '<div class="md2pdf-cover__brand md2pdf-cover__brand--subtle" dir="ltr">'
            '<span class="md2pdf-cover__brand-copy">'
            f'<strong>Generated with {html.escape(PRODUCT_BRAND_NAME)}</strong>'
            '</span>'
            '</div>'
        )
    mark_html = '' if branding.mode == "subtle" else f'<span class="md2pdf-cover__mark">{_brand_logo_html(branding)}</span>'
    footer_html = f'<em>{html.escape(branding.footer)}</em>' if branding.footer else ""
    brand_kind = "product" if branding.product else "custom"
    brand_classes = (
        f"md2pdf-cover__brand md2pdf-cover__brand--{html.escape(branding.mode)} "
        f"md2pdf-cover__brand--{brand_kind}"
    )
    return (
        f'<div class="{brand_classes}" dir="ltr">'
        f'{mark_html}'
        '<span class="md2pdf-cover__brand-copy">'
        f'<strong>{html.escape(branding.name)}</strong>'
        f'{footer_html}'
        '</span>'
        '</div>'
    )


def _watermark_html(options: PdfOptions) -> str:
    if options.watermark_image:
        image_uri = _image_data_uri(options.watermark_image)
        if image_uri:
            return (
                '<div class="md2pdf-watermark md2pdf-watermark--image" aria-hidden="true" '
                f'style="--watermark-opacity: {options.watermark_opacity}; --watermark-width: {html.escape(options.watermark_width)};">'
                f'<img src="{html.escape(image_uri)}" alt="">'
                '</div>'
            )
    if options.watermark_text:
        return (
            '<div class="md2pdf-watermark md2pdf-watermark--text" aria-hidden="true" '
            f'style="--watermark-opacity: {options.watermark_opacity};">'
            f'{html.escape(options.watermark_text)}'
            '</div>'
        )
    return ""


def _first_metadata_value(metadata: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = metadata.get(key)
        if value not in (None, ""):
            return value
    return ""


def _stringify_metadata_value(value: Any, *, item_separator: str = "، ") -> str:
    """Convert front-matter values into readable cover text.

    YAML front matter may contain strings, numbers, block strings, lists, or
    small dictionaries such as author records. The cover renderer should handle
    all of them without leaking Python list/dict syntax into the PDF.
    """
    active: set[int] = set()
    node_budget = 2048

    def stringify(item: Any, depth: int) -> str:
        nonlocal node_budget
        node_budget -= 1
        if node_budget < 0:
            raise ValueError("Front-matter value exceeds the supported complexity limit.")
        if depth > 16:
            raise ValueError("Front-matter value exceeds the supported nesting depth.")
        if item in (None, ""):
            return ""
        if isinstance(item, (list, tuple, set)):
            identity = id(item)
            if identity in active:
                raise ValueError("Front-matter value contains a recursive alias.")
            active.add(identity)
            try:
                return item_separator.join(
                    part for part in (stringify(child, depth + 1) for child in item) if part
                )
            finally:
                active.remove(identity)
        if isinstance(item, dict):
            identity = id(item)
            if identity in active:
                raise ValueError("Front-matter value contains a recursive alias.")
            active.add(identity)
            try:
                name = item.get("name") or item.get("title") or item.get("label") or ""
                details = []
                for key in ("email", "affiliation", "role"):
                    if item.get(key):
                        details.append(stringify(item[key], depth + 1))
                if name and details:
                    return f"{stringify(name, depth + 1)} ({' - '.join(details)})"
                if name:
                    return stringify(name, depth + 1)
                parts = []
                for key, child in item.items():
                    if child in (None, ""):
                        continue
                    parts.append(f"{stringify(key, depth + 1)}: {stringify(child, depth + 1)}")
                return item_separator.join(parts)
            finally:
                active.remove(identity)
        return str(item)

    return stringify(value, 0)


CSS_PAGE_SIZE_RE = re.compile(
    r"^(?:[A-Za-z][A-Za-z0-9-]*(?:\s+(?:portrait|landscape))?|\d+(?:\.\d+)?(?:mm|cm|in|px|pt)\s+\d+(?:\.\d+)?(?:mm|cm|in|px|pt))$",
    re.IGNORECASE,
)

RTL_LANG_PREFIXES = ("ar", "fa", "he", "iw", "ku", "ps", "sd", "ug", "ur", "yi")

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


def normalize_language(value: Any, fallback: str = "") -> str:
    text = _stringify_metadata_value(value).strip().replace("_", "-").lower()
    return text or fallback


def _language_direction(lang: str | None) -> str:
    normalized = normalize_language(lang)
    if not normalized:
        return "auto"
    if normalized.startswith(RTL_LANG_PREFIXES):
        return "rtl"
    return "ltr"


def _localized_labels(lang: str | None) -> dict[str, str]:
    normalized = normalize_language(lang, "fa")
    family = "fa" if normalized.startswith(RTL_LANG_PREFIXES) else "en"
    labels = {
        "fa": {
            "generated_document": "سند تولیدشده",
            "pdf_report": "گزارش PDF",
            "author": "نویسنده",
            "authors": "نویسندگان",
            "date": "تاریخ",
            "institution": "مؤسسه",
            "course": "درس / دوره",
            "department": "دپارتمان",
            "supervisor": "راهنما / استاد",
            "student_id": "شماره دانشجویی",
            "group": "گروه",
            "version": "نسخه",
            "status": "وضعیت",
            "keywords": "کلیدواژه‌ها",
        },
        "en": {
            "generated_document": "Generated Document",
            "pdf_report": "PDF Report",
            "author": "Author",
            "authors": "Authors",
            "date": "Date",
            "institution": "Institution",
            "course": "Course",
            "department": "Department",
            "supervisor": "Supervisor",
            "student_id": "Student ID",
            "group": "Group",
            "version": "Version",
            "status": "Status",
            "keywords": "Keywords",
        },
    }
    return labels[family]


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


def normalize_document_direction(value: Any, *, default: str = "auto") -> str:
    text = _stringify_metadata_value(value).strip().lower()
    if text in {"rtl", "right-to-left", "right_to_left"}:
        return "rtl"
    if text in {"ltr", "left-to-right", "left_to_right"}:
        return "ltr"
    if text in {"auto", "automatic", "detect", "detected", ""}:
        return default if default in {"rtl", "ltr", "auto"} else "auto"
    return default if default in {"rtl", "ltr", "auto"} else "auto"


def _plain_html_text(html_text: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", html_text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def _detect_document_direction(text: str, lang: str | None = None) -> str:
    """Choose a stable document-level direction for the root and layout.

    Individual paragraphs still use ``dir=auto``. This function only controls
    the page shell, TOC/list indentation direction, and default alignment.
    """
    rtl = 0
    ltr = 0
    for char in text:
        direction = unicodedata.bidirectional(char)
        if direction in {"R", "AL"}:
            rtl += 1
        elif direction == "L":
            ltr += 1
    if rtl or ltr:
        return "rtl" if rtl >= ltr else "ltr"

    lang_value = (lang or "").strip().lower()
    if lang_value.startswith(RTL_LANG_PREFIXES):
        return "rtl"
    return "ltr"


def _resolved_document_direction(result: MarkdownRenderResult, options: PdfOptions, lang: str) -> str:
    metadata = result.metadata
    requested = normalize_document_direction(
        options.document_direction
        if options.document_direction not in (None, "")
        else _first_metadata_value(metadata, "dir", "direction", "text_direction", "document_direction"),
        default="auto",
    )
    if requested in {"rtl", "ltr"}:
        return requested
    lang_direction = _language_direction(lang)
    if lang_direction in {"rtl", "ltr"}:
        return lang_direction
    sample = " ".join(
        part
        for part in [
            _stringify_metadata_value(metadata.get("title")),
            _stringify_metadata_value(metadata.get("subtitle")),
            _plain_html_text(result.toc_html),
            _plain_html_text(result.reference_lists_html),
            _plain_html_text(result.body_html),
            _plain_html_text(result.bibliography_html),
        ]
        if part
    )
    return _detect_document_direction(sample, lang)


def _metadata_items(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for item in value:
            items.extend(_metadata_items(item))
        return [item for item in items if item]
    text = _stringify_metadata_value(value)
    return [text] if text else []


def _footer_context(result: MarkdownRenderResult, options: PdfOptions, title: str) -> FooterContext:
    """Build the small running metadata line used in page footers."""
    metadata = result.metadata
    raw_lang = _stringify_metadata_value(options.document_language or metadata.get("lang"))
    document_direction = _resolved_document_direction(result, options, raw_lang)
    lang = raw_lang or ("fa" if document_direction == "rtl" else "en")

    pieces: list[str] = []
    for key in ("version", "status", "date"):
        value = _stringify_metadata_value(metadata.get(key)).strip()
        if value and value not in pieces:
            pieces.append(value)
    course = _stringify_metadata_value(_first_metadata_value(metadata, "course", "institution")).strip()
    if course and course not in pieces:
        pieces.insert(0, course)
    metadata_line = " · ".join(pieces[:3])
    return FooterContext(
        title=str(title or result.title or "Document"),
        metadata=metadata_line,
        lang=lang,
        document_direction=document_direction,
    )


def _footer_page_label(lang: str | None) -> str:
    return "صفحه" if normalize_language(lang).startswith(RTL_LANG_PREFIXES) else "Page"


def _paragraph_block_html(value: Any, class_name: str) -> str:
    text = _stringify_metadata_value(value, item_separator="\n")
    if not text.strip():
        return ""
    paragraphs = [
        paragraph.strip() for paragraph in re.split(r"\n\s*\n", text.strip()) if paragraph.strip()
    ]
    if not paragraphs:
        return ""
    rendered = []
    for paragraph in paragraphs:
        escaped = html.escape(paragraph).replace("\n", "<br>")
        rendered.append(f'<p dir="auto">{escaped}</p>')
    return f'<div class="{html.escape(class_name)}" dir="auto">{"".join(rendered)}</div>'


def _cover_detail(label: str, value: Any, *, multiline: bool = False) -> str:
    if multiline:
        items = _metadata_items(value)
        if not items:
            return ""
        value_html = "".join(
            f'<span class="md2pdf-cover__detail-line" dir="auto">{html.escape(item)}</span>'
            for item in items
        )
    else:
        text = _stringify_metadata_value(value)
        if not text.strip():
            return ""
        value_html = html.escape(text).replace("\n", "<br>")
    return (
        '<div class="md2pdf-cover__detail" dir="auto">'
        f'<span>{html.escape(label)}</span>'
        f'<strong>{value_html}</strong>'
        '</div>'
    )


def _metadata_path(value: Any, base_dir: Path) -> Path | None:
    text = _stringify_metadata_value(value)
    if not text.strip():
        return None
    root = base_dir.resolve(strict=True)
    raw_path = Path(text).expanduser()
    if raw_path.is_absolute():
        raise DocumentAssetError(
            "Front-matter image paths must be relative to the Markdown document directory."
        )
    try:
        path = (root / raw_path).resolve(strict=True)
        path.relative_to(root)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise DocumentAssetError(
            f'Front-matter image path "{text}" is missing or outside the Markdown document directory.'
        ) from exc
    if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise DocumentAssetError(
            f'Front-matter image path "{text}" must reference a regular file.'
        )
    mime_type = (mimetypes.guess_type(str(path))[0] or "").lower()
    if mime_type not in ALLOWED_EMBED_ASSET_MIME_TYPES:
        raise DocumentAssetError(
            f'Front-matter image path "{text}" must reference a supported image file.'
        )
    if path.stat().st_size > MAX_EMBED_ASSET_BYTES:
        raise DocumentAssetError(
            f'Front-matter image path "{text}" exceeds the {MAX_EMBED_ASSET_BYTES}-byte limit.'
        )
    return path


def _layout_css(options: PdfOptions, *, cover_full_bleed: bool = False, document_direction: str = "rtl") -> str:
    classes: list[str] = []
    doc_dir = normalize_document_direction(document_direction, default="rtl")
    appearance = resolve_appearance(style=options.style, palette=options.palette, mode=options.mode)
    inline_math_scale, display_math_scale = math_scale_vars(appearance.style)
    css_chunks = [
        f"""
      @page {{
        size: {_css_page_size(options.page_size)};
        margin: {"0" if cover_full_bleed else f"var(--page-margin-top, {options.margin_top}) var(--page-margin-x, {options.margin_x}) var(--page-margin-bottom, {options.margin_bottom})"};
      }}
      :root {{
        --page-margin-top: {"0" if cover_full_bleed else options.margin_top};
        --page-margin-bottom: {"0" if cover_full_bleed else options.margin_bottom};
        --page-margin-x: {"0" if cover_full_bleed else options.margin_x};
        --md2pdf-document-direction: {doc_dir};
        --md2pdf-inline-math-scale: {inline_math_scale};
        --md2pdf-display-math-scale: {display_math_scale};
        --md2pdf-code-highlight-bg: color-mix(in srgb, var(--accent, #2563eb) 24%, var(--code-bg, #0f172a));
        --md2pdf-code-highlight-border: color-mix(in srgb, var(--accent, #2563eb) 52%, transparent);
      }}
      body.md2pdf-dir-rtl .md2pdf-document,
      body.md2pdf-dir-rtl .md2pdf-article {{ direction: rtl; }}
      body.md2pdf-dir-ltr .md2pdf-document,
      body.md2pdf-dir-ltr .md2pdf-article {{ direction: ltr; }}
      body.md2pdf-dir-ltr .md2pdf-cover {{ direction: ltr; }}
      body.md2pdf-dir-rtl .md2pdf-cover {{ direction: rtl; }}
      body .md2pdf-cover__top {{
        direction: ltr;
        justify-content: flex-start;
      }}
      body.md2pdf-dir-ltr .md2pdf-cover__content {{
        margin-left: 0;
        margin-right: auto;
        text-align: left;
      }}
      body.md2pdf-dir-rtl .md2pdf-cover__content {{
        margin-left: auto;
        margin-right: 0;
        text-align: right;
      }}
      body.md2pdf-dir-ltr .md2pdf-cover h1,
      body.md2pdf-dir-ltr .md2pdf-cover__subtitle,
      body.md2pdf-dir-ltr .md2pdf-cover__summary,
      body.md2pdf-dir-ltr .md2pdf-cover__detail {{ text-align: left; }}
      body.md2pdf-dir-rtl .md2pdf-cover h1,
      body.md2pdf-dir-rtl .md2pdf-cover__subtitle,
      body.md2pdf-dir-rtl .md2pdf-cover__summary,
      body.md2pdf-dir-rtl .md2pdf-cover__detail {{ text-align: right; }}
      body.md2pdf-dir-ltr .md2pdf-cover__subtitle {{ margin: -4mm auto 4mm 0; }}
      body.md2pdf-dir-rtl .md2pdf-cover__subtitle {{ margin: -4mm 0 4mm auto; }}
      body.md2pdf-dir-ltr .md2pdf-cover__summary {{ margin: 5mm auto 0 0; }}
      body.md2pdf-dir-rtl .md2pdf-cover__summary {{ margin: 5mm 0 0 auto; }}
      body.md2pdf-dir-ltr .md2pdf-cover__details {{ direction: ltr; }}
      body.md2pdf-dir-rtl .md2pdf-cover__details {{ direction: rtl; }}
      body.md2pdf-dir-ltr .md2pdf-cover__detail {{ direction: ltr; }}
      body.md2pdf-dir-rtl .md2pdf-cover__detail {{ direction: rtl; }}
      body.md2pdf-dir-ltr .md2pdf-cover__detail > span {{
        font-family: var(--font-en), var(--font-fa);
      }}
      body.md2pdf-dir-rtl .md2pdf-cover__detail > span {{
        font-family: var(--font-fa), var(--font-en);
        font-weight: 800;
        letter-spacing: 0;
        text-transform: none;
      }}
      body.md2pdf-dir-ltr .md2pdf-cover__detail > strong {{ font-family: var(--font-en), var(--font-fa); }}
      body.md2pdf-dir-rtl .md2pdf-cover__detail > strong {{ font-family: var(--font-fa), var(--font-en); }}
      .md2pdf-cover--branding-off .md2pdf-cover__top {{ min-height: 14mm; }}
      .md2pdf-cover__brand--subtle {{
        padding: 0 !important;
        border: 0 !important;
        background: transparent !important;
        box-shadow: none !important;
        opacity: 0.72;
      }}
      .md2pdf-cover__brand--subtle .md2pdf-cover__brand-copy strong {{
        color: var(--muted, #64748b) !important;
        font-size: 6.4pt !important;
        letter-spacing: 0.12em !important;
        text-transform: uppercase !important;
      }}
      .md2pdf-cover__brand--subtle .md2pdf-cover__brand-copy em {{
        display: none !important;
      }}
      .md2pdf-cover__brand--product {{
        border-color: color-mix(in srgb, var(--accent) 22%, rgba(15, 23, 42, 0.12)) !important;
        background: color-mix(in srgb, #ffffff 92%, var(--accent-soft) 8%) !important;
        box-shadow: none !important;
      }}
      .md2pdf-cover__brand--product .md2pdf-cover__mark {{
        background: linear-gradient(135deg, var(--accent), var(--accent-2)) !important;
      }}
      .md2pdf-cover__brand--product .md2pdf-cover__brand-copy em {{
        color: color-mix(in srgb, var(--accent) 54%, #64748b) !important;
      }}
      .md2pdf-document {{
        position: relative;
        z-index: 1;
      }}
      .md2pdf-watermark {{
        z-index: 2 !important;
        mix-blend-mode: multiply;
      }}
      body.md2pdf-style-textbook.md2pdf-mode-dark .md2pdf-watermark {{
        mix-blend-mode: screen;
      }}
      body.md2pdf-style-textbook.md2pdf-mode-dark .md2pdf-watermark--text {{
        color: #f8fafc;
      }}
      body.md2pdf-style-textbook.md2pdf-mode-dark .md2pdf-watermark--image img {{
        filter: invert(1) grayscale(1);
      }}
      body.md2pdf-dir-ltr .callout {{ direction: ltr; text-align: left; }}
      body.md2pdf-dir-rtl .callout {{ direction: rtl; text-align: right; }}
      body.md2pdf-dir-ltr .callout-title,
      body.md2pdf-dir-ltr .callout p {{ text-align: left; }}
      body.md2pdf-dir-rtl .callout-title,
      body.md2pdf-dir-rtl .callout p {{ text-align: right; }}
      .md2pdf-rtl-text {{
        direction: rtl;
        text-align: start;
        unicode-bidi: plaintext;
      }}
      .md2pdf-ltr-text {{
        direction: ltr;
        text-align: start;
        unicode-bidi: plaintext;
      }}
      .mixed-script {{
        unicode-bidi: plaintext;
      }}
      .md2pdf-ltr-isolate {{
        direction: ltr;
        unicode-bidi: isolate;
        display: inline;
        font-family: var(--font-en), var(--font-fa), sans-serif;
      }}
      .md2pdf-ltr-isolate--punct {{
        white-space: nowrap;
      }}
      .md2pdf-ltr-isolate-group {{
        direction: ltr;
        unicode-bidi: isolate;
        display: inline;
        white-space: nowrap;
      }}
      .md2pdf-ltr-isolate-group .footnote-ref {{
        direction: rtl;
        unicode-bidi: isolate;
      }}
      body.md2pdf-dir-rtl .md2pdf-article a[href^="http"],
      body.md2pdf-dir-rtl .md2pdf-article a[href^="mailto"],
      body.md2pdf-dir-rtl .md2pdf-article a[href^="www."] {{
        direction: ltr;
        unicode-bidi: isolate;
      }}
      .mixed-numeral,
      .persian-numeral,
      .latin-numeral {{
        font-variant-numeric: tabular-nums;
        unicode-bidi: plaintext;
      }}
      .persian-punctuation,
      .rtl-ascii-punctuation {{
        unicode-bidi: plaintext;
      }}
      body.md2pdf-dir-rtl .persian-punctuation,
      body.md2pdf-dir-rtl .rtl-ascii-punctuation {{
        direction: rtl;
      }}
      .table-wrap--profiled {{
        isolation: isolate;
      }}
      .table-wrap--rtl table {{ direction: rtl; }}
      .table-wrap--ltr table {{ direction: ltr; }}
      .table-wrap--mixed-direction table,
      .table-wrap--mixed table {{ unicode-bidi: plaintext; }}
      .table-wrap--rtl th,
      .table-wrap--rtl td,
      .table-cell--rtl {{
        direction: rtl;
        text-align: right;
        unicode-bidi: plaintext;
      }}
      .table-wrap--ltr th,
      .table-wrap--ltr td,
      .table-cell--ltr {{
        direction: ltr;
        text-align: left;
        unicode-bidi: plaintext;
      }}
      .table-cell--mixed {{
        direction: auto;
        unicode-bidi: plaintext;
      }}
      .table-cell--mixed-rtl {{
        direction: rtl;
        text-align: right;
        unicode-bidi: plaintext;
      }}
      .table-cell--mixed-ltr {{
        direction: ltr;
        text-align: left;
        unicode-bidi: plaintext;
      }}
      .table-wrap--rtl .table-cell--mixed:not(.table-cell--mixed-ltr) {{
        direction: rtl;
        text-align: right;
      }}
      .table-wrap--numeric,
      .table-wrap--persian-number,
      .table-wrap--latin-number,
      .table-wrap--mixed-number {{
        font-variant-numeric: tabular-nums;
      }}
      .table-wrap--persian-caption caption,
      .table-wrap--caption-rtl caption {{
        direction: rtl;
        text-align: right;
        unicode-bidi: plaintext;
      }}
      .table-wrap--caption-ltr caption {{
        direction: ltr;
        text-align: left;
        unicode-bidi: plaintext;
      }}
      .table-wrap--caption-mixed caption {{
        direction: auto;
        unicode-bidi: plaintext;
      }}
      body.md2pdf-dir-rtl .md2pdf-caption,
      body.md2pdf-dir-rtl figcaption,
      body.md2pdf-dir-rtl caption {{
        unicode-bidi: plaintext;
      }}
      .md2pdf-caption--rtl,
      .md2pdf-caption--persian {{
        direction: rtl;
        unicode-bidi: plaintext;
      }}
      .md2pdf-caption--ltr {{
        direction: ltr;
        unicode-bidi: plaintext;
      }}
      .md2pdf-caption--mixed {{
        direction: auto;
        unicode-bidi: plaintext;
      }}
      .md2pdf-caption--numbered,
      .toc-number,
      .footnote-ref,
      .footnote-marker {{
        font-variant-numeric: tabular-nums;
      }}
      .persian-generated-number,
      .toc-number--persian,
      .footnote-marker.persian-generated-number {{
        font-family: var(--font-fa), var(--font-en), sans-serif;
        direction: rtl;
        unicode-bidi: isolate;
      }}
      .latin-generated-number {{
        font-family: var(--font-en), var(--font-fa), sans-serif;
        direction: ltr;
        unicode-bidi: isolate;
      }}
      .md2pdf-caption--persian-number {{
        direction: rtl;
        unicode-bidi: plaintext;
      }}
      .md2pdf-caption--latin-number {{
        direction: ltr;
        unicode-bidi: plaintext;
      }}
      .md2pdf-caption--mixed-number {{
        direction: auto;
        unicode-bidi: plaintext;
      }}
      .md2pdf-caption--profiled {{
        isolation: isolate;
      }}
      .md2pdf-caption--persian.md2pdf-caption--figure,
      .md2pdf-caption--persian.md2pdf-caption--diagram {{
        text-align: center;
      }}
      .md2pdf-toc--profiled {{
        isolation: isolate;
      }}
      .md2pdf-toc .toc-list {{
        list-style: none;
        margin-block: 0;
      }}
      .md2pdf-toc .toc-item > a {{
        display: grid;
        align-items: baseline;
        column-gap: 0.75em;
        text-decoration: none;
      }}
      .md2pdf-toc .toc-list--nested {{
        margin-block-start: 1.15mm;
      }}
      .md2pdf-toc--rtl {{
        direction: rtl;
        text-align: right;
      }}
      .md2pdf-toc--rtl .toc-list {{
        padding-inline-start: 0;
        padding-inline-end: 0;
      }}
      .md2pdf-toc--rtl .toc-list--nested {{
        margin-inline-start: 1.35em;
        margin-inline-end: 0;
        padding-inline-start: 0.8em;
        padding-inline-end: 0;
        border-inline-start: 1px solid color-mix(in srgb, var(--line, #dbe3ef) 76%, transparent);
        border-inline-end: 0;
      }}
      .md2pdf-toc--rtl .toc-item {{
        text-align: right;
      }}
      .md2pdf-toc--rtl .toc-item > a {{
        display: inline-flex;
        flex-direction: row;
        align-items: baseline;
        justify-content: flex-start;
        max-width: 100%;
        direction: rtl;
      }}
      .md2pdf-toc--rtl .toc-number {{
        min-width: 2.4em;
        flex: 0 0 auto;
        text-align: left;
        direction: ltr;
        unicode-bidi: isolate;
      }}
      .md2pdf-toc--rtl .toc-title {{
        min-width: 0;
        flex: 0 1 auto;
        direction: auto;
        unicode-bidi: plaintext;
      }}
      .md2pdf-toc--ltr .toc-list {{
        padding-inline-start: 0;
        padding-inline-end: 0;
      }}
      .md2pdf-toc--ltr .toc-list--nested {{
        margin-inline-start: 1.35em;
        margin-inline-end: 0;
        padding-inline-start: 0.8em;
        padding-inline-end: 0;
        border-inline-start: 1px solid color-mix(in srgb, var(--line, #dbe3ef) 76%, transparent);
        border-inline-end: 0;
      }}
      .md2pdf-toc--ltr .toc-item > a {{
        grid-template-columns: max-content minmax(0, 1fr);
        direction: ltr;
      }}
      .md2pdf-toc--ltr .toc-number {{
        grid-column: 1;
      }}
      .md2pdf-toc--ltr .toc-title {{
        grid-column: 2;
      }}
      .toc-item--rtl .toc-title {{
        direction: rtl;
        text-align: right;
      }}
      .toc-item--ltr .toc-title {{
        direction: ltr;
        text-align: left;
      }}
      .toc-item--mixed .toc-title,
      .toc-item--mixed-script .toc-title {{
        direction: auto;
        unicode-bidi: plaintext;
      }}
      .md2pdf-toc--ltr {{
        direction: ltr;
        text-align: left;
      }}
      .footnotes--local {{
        margin-block: 0.55em 1.15em !important;
        padding-block-start: 2mm !important;
        border-block-start: 1px solid var(--line, #dbe3ef);
        color: var(--muted, #64748b);
        font-size: 8.5pt;
        line-height: 1.48;
        break-inside: avoid;
        page-break-inside: avoid;
        break-before: avoid;
        page-break-before: avoid;
      }}
      .footnotes--local .footnote-item {{
        margin-block: 0.32em;
      }}
      .footnotes--local .footnote-body {{
        line-height: 1.48;
      }}
      .footnotes--local + .footnotes--local {{
        margin-block-start: -0.35em !important;
      }}
      .footnotes--rtl {{
        direction: rtl;
        text-align: right;
      }}
      .footnotes--rtl .footnote-item {{
        direction: rtl;
      }}
      .footnotes--rtl .footnote-body {{
        unicode-bidi: plaintext;
      }}
      .footnote-body--rtl {{
        direction: rtl;
        text-align: right;
        unicode-bidi: plaintext;
      }}
      .footnote-body--ltr {{
        direction: ltr;
        text-align: left;
        unicode-bidi: plaintext;
      }}
      .footnote-body--mixed {{
        direction: auto;
        unicode-bidi: plaintext;
      }}
      .footnote-item--persian .footnote-backrefs {{
        direction: ltr;
        unicode-bidi: isolate;
      }}
      .footnote-ref--rtl {{
        direction: rtl;
        unicode-bidi: isolate;
      }}
      body.md2pdf-dir-ltr .md2pdf-details {{ direction: ltr; text-align: left; }}
      body.md2pdf-dir-rtl .md2pdf-details {{ direction: rtl; text-align: right; }}
      .math,
      .md2pdf-article mjx-container {{
        direction: ltr;
        unicode-bidi: isolate;
      }}
      .math.inline {{
        display: inline;
        white-space: nowrap;
        font-size: 1em;
      }}
      .math.inline mjx-container,
      .md2pdf-article mjx-container:not([display="true"]) {{
        display: inline-block !important;
        font-size: var(--md2pdf-inline-math-scale) !important;
        line-height: 0 !important;
        margin: 0 0.06em !important;
        max-width: 100%;
        vertical-align: -0.12em !important;
      }}
      .math.display {{
        display: block;
        margin: 1.25em auto;
        padding: 3mm 2mm;
        overflow: hidden;
        max-width: 100%;
        text-align: center !important;
        page-break-inside: avoid;
        break-inside: avoid;
        font-size: 1em;
      }}
      .math.display mjx-container,
      .md2pdf-article mjx-container[display="true"] {{
        display: block !important;
        font-size: var(--md2pdf-display-math-scale) !important;
        line-height: 1.25 !important;
        margin: 0 auto !important;
        max-width: 100%;
        text-align: center !important;
      }}
      .md2pdf-article mjx-container svg {{ max-width: 100%; }}
      .md2pdf-image-placeholder {{
        display: block;
        margin: 1em 0;
        padding: 3mm 4mm;
        border: 1px dashed var(--line-strong, var(--line, #cbd5e1));
        border-radius: var(--radius, 10px);
        background: color-mix(in srgb, var(--soft, #f8fafc) 82%, transparent);
        color: var(--muted, #64748b);
        font: 600 8.5pt/1.55 var(--font-fa), var(--font-en), sans-serif;
        overflow-wrap: anywhere;
        page-break-inside: avoid;
        break-inside: avoid;
      }}
      .md2pdf-image-placeholder strong {{
        display: block;
        margin-bottom: 1mm;
        color: var(--ink, #172033);
        font-weight: 850;
      }}
      .md2pdf-image-placeholder span {{
        display: block;
      }}
      .table-wrap--compact {{
        margin-block: 0.95em 1.05em;
      }}
      .table-wrap--compact table {{
        font-size: min(9pt, 0.9em);
        line-height: 1.48;
      }}
      .table-wrap--compact th,
      .table-wrap--compact td {{
        padding: 1.9mm 2.2mm;
      }}
      .table-wrap--medium {{
        margin-block: 0.85em 1em;
      }}
      .table-wrap--wide table {{
        table-layout: fixed;
        width: 100%;
        font-size: min(8.2pt, 0.82em);
        line-height: 1.42;
      }}
      .table-wrap--wide th,
      .table-wrap--wide td {{
        padding: 1.4mm 1.6mm;
        overflow-wrap: anywhere;
        word-break: normal;
        hyphens: auto;
      }}
      .table-wrap--long {{
        margin-block: 0.75em 0.9em;
      }}
      .table-wrap--long table {{
        font-size: min(8.4pt, 0.84em);
        line-height: 1.38;
      }}
      .table-wrap--long th,
      .table-wrap--long td {{
        padding-block: 1.25mm;
      }}
      .table-wrap--very-wide table {{
        font-size: min(6.8pt, 0.68em);
        line-height: 1.32;
      }}
      .table-wrap--very-wide th,
      .table-wrap--very-wide td {{
        padding: 1mm 1.1mm;
      }}
      .code-block--medium {{
        margin-block: 1em 1.1em;
      }}
      .code-block--medium .codehilite pre,
      .code-block--medium .highlight pre,
      .code-block--medium pre {{
        padding-block: 3.4mm;
        line-height: 1.55;
      }}
      .code-block--long {{
        margin-block: 0.85em 1em;
      }}
      .code-block--long .codehilite pre,
      .code-block--long .highlight pre,
      .code-block--long pre {{
        padding-block: 3mm;
        line-height: 1.48;
      }}
      .code-block--very-long .codehilite pre,
      .code-block--very-long .highlight pre,
      .code-block--very-long pre {{
        padding-block: 2.6mm;
        line-height: 1.42;
      }}
      .code-block--long figcaption,
      .code-block--very-long figcaption {{
        padding-block: 1.6mm;
      }}
      .mermaid-diagram {{
        margin: 1.35em auto;
        padding: 4mm;
        border: 1px solid var(--md2pdf-mermaid-figure-border, var(--line, #dbe3ef));
        border-radius: var(--radius, 12px);
        background: var(--md2pdf-mermaid-figure-bg, color-mix(in srgb, var(--softer, #f8fafc) 86%, #ffffff));
        color: var(--md2pdf-mermaid-figure-ink, inherit);
        page-break-inside: avoid;
        break-inside: avoid;
        overflow: hidden;
      }}
      .mermaid-diagram figcaption {{
        margin: 0 0 3mm;
        color: var(--md2pdf-mermaid-caption-ink, var(--muted, #64748b));
        font: 700 8pt/1.4 var(--font-en), var(--font-fa);
        letter-spacing: 0.08em;
        text-transform: uppercase;
        text-align: left;
      }}
      .md2pdf-mermaid-svg {{
        display: block;
        width: 100%;
        max-width: 100%;
        max-height: var(--md2pdf-mermaid-max-height, 185mm);
        height: auto;
        margin-inline: auto;
        object-fit: contain;
        font-family: var(--font-en), var(--font-fa), sans-serif;
        shape-rendering: geometricPrecision;
        text-rendering: geometricPrecision;
      }}
      .mermaid-diagram--tall,
      .mermaid-diagram--wide {{
        margin-block: 1em 1.1em;
        padding: 3mm;
      }}
      .mermaid-diagram--tall figcaption,
      .mermaid-diagram--wide figcaption {{
        margin-bottom: 2.2mm;
      }}
      .mermaid-diagram--tall .md2pdf-mermaid-svg {{
        width: auto;
        max-width: 100%;
        max-height: var(--md2pdf-mermaid-tall-max-height, 165mm);
      }}
      .mermaid-diagram--wide .md2pdf-mermaid-svg {{
        width: 100%;
        max-height: var(--md2pdf-mermaid-wide-max-height, 108mm);
      }}
      .md2pdf-mermaid-bg {{
        fill: var(--md2pdf-mermaid-bg, color-mix(in srgb, var(--soft, #f4f7fb) 74%, #ffffff));
        stroke: var(--md2pdf-mermaid-border, var(--line, #dbe3ef));
        stroke-width: 1;
      }}
      .md2pdf-mermaid-node-shape {{
        fill: var(--md2pdf-mermaid-node-bg, #ffffff);
        stroke: var(--md2pdf-mermaid-stroke, var(--accent, var(--blue, #2563eb)));
        stroke-width: 1.5;
      }}
      .md2pdf-mermaid-node-detail {{
        fill: none;
        opacity: .66;
        pointer-events: none;
      }}
      .md2pdf-mermaid-node-label {{
        fill: var(--md2pdf-mermaid-node-ink, var(--ink, #172033));
        font-size: 12px;
        font-weight: 700;
        dominant-baseline: middle;
        unicode-bidi: plaintext;
      }}
      .md2pdf-mermaid-edge path {{
        fill: none;
        stroke: var(--md2pdf-mermaid-stroke, var(--accent, var(--blue, var(--line-strong, #2563eb))));
        stroke-width: 1.8;
      }}
      .md2pdf-mermaid-edge-dotted path {{
        stroke-dasharray: 5 4;
      }}
      .md2pdf-mermaid-edge-thick path {{
        stroke-width: 2.8;
      }}
      .md2pdf-mermaid-arrow-head {{
        fill: var(--md2pdf-mermaid-stroke, var(--accent, var(--blue, var(--line-strong, #2563eb))));
      }}
      .md2pdf-mermaid-edge-label-group {{
        pointer-events: none;
      }}
      .md2pdf-mermaid-edge-label-bg {{
        fill: var(--md2pdf-mermaid-label-bg, var(--md2pdf-mermaid-label-halo, color-mix(in srgb, var(--paper, #ffffff) 92%, transparent)));
        stroke: var(--md2pdf-mermaid-label-border, color-mix(in srgb, var(--md2pdf-mermaid-stroke, var(--accent, #2563eb)) 22%, transparent));
        stroke-width: 0.8;
      }}
      .md2pdf-mermaid-edge-label {{
        fill: var(--md2pdf-mermaid-edge-ink, var(--muted, #64748b));
        font: 750 11px/1 var(--font-en), var(--font-fa), sans-serif;
        unicode-bidi: plaintext;
      }}
      .md2pdf-page-break {{
        display: block;
        height: 0;
        margin: 0;
        padding: 0;
        border: 0;
        overflow: hidden;
        clear: both;
        break-before: auto;
        page-break-before: auto;
        break-after: page;
        page-break-after: always;
      }}

      code,
      pre,
      kbd,
      samp,
      .code-block,
      .code-caption,
      .code-table,
      .highlight,
      .md2pdf-caption--code {{
        unicode-bidi: isolate;
      }}
      body.md2pdf-dir-rtl code,
      body.md2pdf-dir-rtl pre,
      body.md2pdf-dir-rtl kbd,
      body.md2pdf-dir-rtl samp,
      body.md2pdf-dir-rtl .code-block,
      body.md2pdf-dir-rtl .code-caption,
      body.md2pdf-dir-rtl .code-table,
      body.md2pdf-dir-rtl .highlight,
      body.md2pdf-dir-rtl .md2pdf-caption--code {{
        direction: ltr;
        text-align: left;
      }}
      .code-block--rtl-script pre,
      .code-block--rtl-script code,
      .code-block--rtl-script .codehilite,
      .code-block--rtl-script .highlight {{
        font-family: var(--font-fa), var(--font-code);
        letter-spacing: 0;
      }}
      .code-block--rtl-script .codehilite span,
      .code-block--rtl-script .highlight span {{
        font-family: inherit;
      }}

      .md2pdf-numbered-object {{
        scroll-margin-top: 12mm;
      }}
      .md2pdf-caption-label {{
        font-weight: 750;
        white-space: nowrap;
      }}
      .md2pdf-xref {{
        font-weight: 650;
        text-decoration-thickness: 0.08em;
        text-underline-offset: 0.13em;
        white-space: nowrap;
      }}
      .md2pdf-xref--unresolved {{
        color: #b91c1c;
        font-weight: 750;
      }}
      .md2pdf-equation {{
        position: relative;
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        align-items: center;
        column-gap: 4mm;
        margin: 1em 0;
        break-inside: avoid;
        page-break-inside: avoid;
      }}
      .md2pdf-equation > .math.display {{
        grid-column: 1;
        margin: 0;
        min-width: 0;
      }}
      .md2pdf-equation-number {{
        grid-column: 2;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
        color: var(--muted, #64748b);
      }}
      .md2pdf-reference-lists {{
        break-after: page;
        page-break-after: always;
      }}
      .md2pdf-reference-list {{
        margin: 1.2em 0 1.8em;
        break-inside: avoid;
        page-break-inside: avoid;
      }}
      .md2pdf-reference-list-heading {{
        margin: 0 0 0.7em;
      }}
      .md2pdf-reference-list-items {{
        list-style: none;
        margin: 0;
        padding: 0;
      }}
      .md2pdf-reference-list-item > a {{
        display: grid;
        grid-template-columns: max-content minmax(0, 1fr);
        gap: 0.8em;
        align-items: baseline;
        padding: 0.28em 0;
        text-decoration: none;
      }}
      .md2pdf-reference-list-number {{
        font-weight: 750;
        white-space: nowrap;
      }}
      .md2pdf-reference-list-title {{
        overflow-wrap: anywhere;
      }}
      body.md2pdf-dir-rtl .md2pdf-reference-list-item > a {{
        grid-template-columns: max-content minmax(0, 1fr);
      }}
      .md2pdf-citation {{
        unicode-bidi: isolate;
        white-space: normal;
      }}
      .md2pdf-citation-item {{
        color: var(--link, #2563eb);
        font-weight: 650;
        text-decoration: none;
        text-underline-offset: 0.13em;
      }}
      .md2pdf-citation-item--unresolved {{
        color: #b91c1c;
        font-weight: 750;
      }}
      .md2pdf-bibliography {{
        margin-top: 2.4em;
        break-before: page;
        page-break-before: always;
      }}
      .md2pdf-bibliography-heading {{
        margin-bottom: 1em;
      }}
      .md2pdf-bibliography-items {{
        margin: 0;
        padding: 0;
      }}
      .md2pdf-bibliography-items--numeric {{
        list-style: none;
        counter-reset: none;
      }}
      .md2pdf-bibliography-entry {{
        margin: 0 0 0.85em;
        padding-inline-start: 1.7em;
        text-indent: -1.7em;
        overflow-wrap: anywhere;
        break-inside: avoid;
        page-break-inside: avoid;
      }}
      .md2pdf-bib-number {{
        display: inline-block;
        min-width: 1.5em;
        font-weight: 750;
        text-indent: 0;
      }}
      .md2pdf-bib-title {{
        font-weight: 600;
      }}
      .md2pdf-bib-link {{
        direction: ltr;
        unicode-bidi: isolate;
        overflow-wrap: anywhere;
      }}
      .md2pdf-bib-backref {{
        margin-inline-start: 0.35em;
        text-decoration: none;
      }}
      .heading-anchor {{
        opacity: 0.34;
        margin-inline-start: 0.35em;
        border: 0;
        color: var(--muted, #64748b);
        font-size: 0.78em;
        text-decoration: none;
      }}
      .heading-anchor:hover {{ opacity: 0.72; }}
      @media print {{
        .heading-anchor {{ display: none !important; }}
      }}
      .md2pdf-figure {{
        margin: 1.35em auto;
        text-align: center;
        page-break-inside: avoid;
        break-inside: avoid;
      }}
      .md2pdf-figure > img {{
        display: block;
        margin: 0 auto;
        max-width: 100%;
        height: auto;
      }}
      .md2pdf-figure > figcaption {{
        margin-top: 2mm;
        color: var(--muted, #64748b);
        font-size: 8.8pt;
        line-height: 1.55;
        text-align: center;
      }}
      .md2pdf-caption {{
        color: var(--md2pdf-caption-ink, var(--muted, #64748b));
        font-size: var(--md2pdf-caption-size, 8.7pt);
        line-height: 1.48;
        font-weight: 650;
        break-inside: avoid;
        page-break-inside: avoid;
      }}
      .md2pdf-caption--figure,
      .md2pdf-caption--diagram {{
        text-align: center;
      }}
      .md2pdf-caption--code {{
        text-align: start;
      }}
      table > caption.md2pdf-caption--table {{
        caption-side: top;
        padding: 2.2mm 3mm;
        border-bottom: 1px solid var(--line, #dbe3ef);
        background: var(--md2pdf-table-caption-bg, color-mix(in srgb, var(--soft, #f4f7fb) 82%, #ffffff));
        color: var(--md2pdf-table-caption-ink, var(--ink, #172033));
        font: 750 8.6pt/1.45 var(--font-fa), var(--font-en), sans-serif;
        text-align: start;
      }}
      .md2pdf-details {{
        margin: 1.2em 0;
        padding: 4mm 4.5mm;
        border: 1px solid var(--md2pdf-details-border, var(--line, #dbe3ef));
        border-radius: var(--radius, 12px);
        background: var(--md2pdf-details-bg, var(--softer, #f8fafc));
        color: var(--md2pdf-details-ink, inherit);
        page-break-inside: avoid;
        break-inside: avoid;
      }}
      .md2pdf-summary {{
        margin-bottom: 2mm;
        font-weight: 850;
        color: var(--md2pdf-details-title, var(--accent, var(--blue, #2563eb)));
      }}
      @media print {{
        .md2pdf-article {{
          orphans: 3;
          widows: 3;
        }}
        h1, h2, h3, h4, h5, h6 {{
          break-after: avoid-page;
          break-inside: avoid;
          page-break-after: avoid;
          page-break-inside: avoid;
          orphans: 3;
          widows: 3;
        }}
        h1 + *, h2 + *, h3 + *, h4 + *, h5 + *, h6 + * {{
          break-before: avoid-page;
          page-break-before: avoid;
        }}
        p, li, blockquote, .callout, .md2pdf-details {{
          orphans: 3;
          widows: 3;
        }}
        blockquote, .callout, .md2pdf-details, .md2pdf-image-placeholder,
        .math.display, .md2pdf-figure, .mermaid-diagram {{
          break-inside: avoid;
          page-break-inside: avoid;
        }}
        .code-block {{
          break-inside: avoid;
          page-break-inside: avoid;
        }}
        .code-block--medium {{
          break-inside: avoid-page;
          page-break-inside: avoid;
        }}
        .code-block--long, .code-block--very-long {{
          break-inside: auto;
          page-break-inside: auto;
        }}
        .code-block figcaption, .mermaid-diagram figcaption, .md2pdf-figure > figcaption,
        table > caption.md2pdf-caption--table, .md2pdf-caption {{
          break-after: avoid;
          page-break-after: avoid;
          break-inside: avoid;
          page-break-inside: avoid;
        }}
        .code-block pre {{
          white-space: pre-wrap;
          overflow-wrap: anywhere;
          word-break: normal;
        }}
        .code-block--numbered .code pre {{
          white-space: pre-wrap;
          overflow-wrap: anywhere;
        }}
        .table-wrap {{
          break-inside: avoid;
          page-break-inside: avoid;
        }}
        .table-wrap table caption {{
          break-after: avoid-page;
          page-break-after: avoid;
        }}
        .table-wrap--medium, .table-wrap--long, .table-wrap--wide, .table-wrap--very-wide {{
          break-inside: auto;
          page-break-inside: auto;
        }}
        .table-wrap--medium table, .table-wrap--long table,
        .table-wrap--wide table, .table-wrap--very-wide table {{
          break-inside: auto;
          page-break-inside: auto;
        }}
        .mermaid-diagram--wide, .mermaid-diagram--tall {{
          padding: 2.8mm;
          margin-block: 0.85em 1em;
        }}
        thead {{
          display: table-header-group;
        }}
        tr {{
          break-inside: avoid;
          page-break-inside: avoid;
        }}
      }}
      .code-block--numbered .codehilite > .table-wrap {{
        margin: 0;
        border: 0;
        border-radius: 0;
        overflow: hidden;
      }}
      .code-block--numbered .codehilitetable {{
        width: 100%;
        border-collapse: collapse;
        margin: 0;
        background: var(--code-bg, #0f172a) !important;
      }}
      .code-block--numbered .codehilitetable td {{
        border: 0;
        padding: 0 !important;
        background: transparent !important;
        vertical-align: top;
      }}
      .code-block--numbered .linenos {{
        width: auto;
        min-width: calc(2ch + var(--md2pdf-code-gutter-padding-inline-start, 4mm) + var(--md2pdf-code-gutter-padding-inline-end, 2.2mm));
        color: color-mix(in srgb, var(--code-ink, #e2e8f0) 46%, transparent) !important;
        text-align: right;
        user-select: none;
        font-family: var(--font-code);
        white-space: nowrap;
      }}
      .code-block--numbered .linenos pre,
      .code-block--numbered .code pre {{
        font-size: var(--md2pdf-code-font-size, 8.8pt) !important;
        line-height: var(--md2pdf-code-line-height, 1.65) !important;
      }}
      .code-block--numbered .linenos pre {{
        margin: 0 !important;
        padding: var(--md2pdf-code-pre-padding-block, 4.2mm) var(--md2pdf-code-gutter-padding-inline-end, 2.2mm) var(--md2pdf-code-pre-padding-block, 4.2mm) var(--md2pdf-code-gutter-padding-inline-start, 4mm) !important;
        background: transparent !important;
        color: inherit !important;
        text-align: right;
        font-variant-numeric: tabular-nums;
        white-space: pre !important;
        overflow-wrap: normal !important;
        word-break: normal !important;
      }}
      .code-block--numbered .linenodiv,
      .code-block--numbered td.linenos .normal,
      .code-block--numbered td.linenos .special,
      .code-block--numbered span.linenos,
      .code-block--numbered span.linenos.special {{
        margin: 0 !important;
        padding: 0 !important;
        background: transparent !important;
        border: 0 !important;
        border-radius: 0 !important;
        box-shadow: none !important;
      }}
      .code-block--numbered td.linenos .normal,
      .code-block--numbered td.linenos .special,
      .code-block--numbered span.linenos,
      .code-block--numbered span.linenos.special {{
        display: inline !important;
        line-height: inherit;
      }}
      .code-block--numbered .code {{
        padding: 0 !important;
      }}
      .code-block--numbered .code pre {{
        margin: 0 !important;
      }}
      .codehilite .hll,
      .highlight .hll {{
        display: inline-block;
        min-width: 100%;
        box-sizing: border-box;
        margin-inline-start: 0;
        padding-inline-start: 0;
        line-height: inherit;
        vertical-align: baseline;
        background-color: var(--md2pdf-code-highlight-bg) !important;
        box-shadow: inset 3px 0 0 var(--md2pdf-code-highlight-border);
      }}
      .code-block--numbered .codehilite .hll,
      .code-block--numbered .highlight .hll {{
        font-size: inherit;
        line-height: inherit;
      }}
    """
    ]
    if cover_full_bleed:
        classes.append("md2pdf-cover-full-bleed")
    classes.append(f"md2pdf-dir-{doc_dir}")
    if options.toc_page_break:
        classes.append("md2pdf-toc-break")
    if options.h1_page_break:
        classes.append("md2pdf-h1-break")
    return "\n".join(css_chunks), " ".join(classes)


def _cover_html(
    title: str,
    author: Any,
    date: Any,
    description: Any,
    options: PdfOptions,
    *,
    subtitle: Any = "",
    extra_details: list[tuple[str, Any]] | None = None,
    eyebrow: Any = "Generated Document",
    lang: str = "fa",
    document_direction: str = "rtl",
    labels: dict[str, str] | None = None,
    branding: CoverBranding | None = None,
) -> str:
    labels = labels or _localized_labels(lang)
    detail_cards: list[str] = []
    author_items = _metadata_items(author)
    if author_items:
        label = labels["authors"] if len(author_items) > 1 else labels["author"]
        detail_cards.append(_cover_detail(label, author_items, multiline=True))
    if date:
        detail_cards.append(_cover_detail(labels["date"], date))
    for label, value in extra_details or []:
        card = _cover_detail(label, value, multiline=isinstance(value, (list, tuple, set)))
        if card:
            detail_cards.append(card)
    subtitle_text = _stringify_metadata_value(subtitle)
    subtitle_html = (
        f'<p class="md2pdf-cover__subtitle" dir="auto">{html.escape(subtitle_text)}</p>' if subtitle_text else ""
    )
    summary_html = _paragraph_block_html(description, "md2pdf-cover__summary")
    details_html = ''.join(detail_cards)
    branding = branding or CoverBranding(mode="off", name=PRODUCT_BRAND_NAME, footer=PRODUCT_BRAND_FOOTER, logo=None, product=True)
    brand_html = _cover_brand_html(branding)
    cover_classes = f"md2pdf-cover md2pdf-cover--branding-{branding.mode}"
    if branding.mode == "off":
        cover_classes += " md2pdf-cover--unbranded"

    return f"""
      <header class="{cover_classes}" lang="{html.escape(str(lang))}" dir="{html.escape(document_direction)}">
        <div class="md2pdf-cover__decor md2pdf-cover__decor--one" aria-hidden="true"></div>
        <div class="md2pdf-cover__decor md2pdf-cover__decor--two" aria-hidden="true"></div>
        <section class="md2pdf-cover__top" dir="ltr">
          {brand_html}
        </section>
        <section class="md2pdf-cover__content">
          <span class="md2pdf-cover__eyebrow">{html.escape(_stringify_metadata_value(eyebrow) or labels["generated_document"])}</span>
          <h1 dir="auto">{html.escape(str(title))}</h1>
          {subtitle_html}
          {summary_html}
        </section>
        {'<section class="md2pdf-cover__details">' + details_html + '</section>' if details_html else '<div></div>'}
      </header>
    """


def _mathjax_block(options: PdfOptions) -> str:
    if options.no_mathjax:
        return ""
    mathjax_config = """
      <script>
        window.MathJax = {
          tex: {
            inlineMath: [['\\\\(', '\\\\)'], ['$', '$']],
            displayMath: [['\\\\[', '\\\\]'], ['$$', '$$']],
            processEscapes: true,
            packages: {'[+]': ['ams', 'noerrors', 'noundefined']}
          },
          svg: { fontCache: 'global' },
          options: { enableMenu: false }
        };
      </script>
    """
    mathjax_js = _mathjax_script()
    if mathjax_js:
        return f"{mathjax_config}<script>{mathjax_js}</script>"
    message = "Bundled MathJax asset missing; equations will remain in TeX form."
    _enforce_quality_issue(
        options,
        category="mathjax",
        policy=options.math_error_policy or "warn",
        message=message,
        details={"asset": "assets/mathjax/tex-svg-full.js"},
        error_type=MathJaxRenderError,
    )
    return "<!-- MathJax asset missing: equations will remain in TeX form. -->"


def build_html(
    result: MarkdownRenderResult,
    options: PdfOptions,
    *,
    include_cover: bool = True,
    include_content: bool = True,
    include_watermark: bool = True,
    cover_full_bleed: bool = False,
    include_mathjax: bool | None = None,
) -> str:
    if include_mathjax is not None:
        options = replace(options, no_mathjax=not include_mathjax)
    appearance = _resolved_appearance(result.metadata, options)
    options = replace(options, style=appearance.style, palette=appearance.palette, mode=appearance.mode)
    style_css = _style_css(appearance)
    appearance_css = palette_css(appearance.palette, appearance.mode, appearance.style)
    font_faces = _font_faces(options.font_dir)
    metadata = result.metadata
    title = options.title or _stringify_metadata_value(metadata.get("title")) or result.title
    author = options.author if options.author is not None else _first_metadata_value(metadata, "authors", "author")
    description = (
        options.description
        if options.description is not None
        else _first_metadata_value(metadata, "description", "summary")
    )
    raw_lang = _stringify_metadata_value(options.document_language or metadata.get("lang"))
    document_direction = _resolved_document_direction(result, options, raw_lang)
    lang = raw_lang or ("fa" if document_direction == "rtl" else "en")
    labels = _localized_labels(lang)
    date = _first_metadata_value(metadata, "date")
    subtitle = _first_metadata_value(metadata, "subtitle", "subject")
    eyebrow = (
        _first_metadata_value(
            metadata,
            "cover_label",
            "cover_eyebrow",
            "document_label",
            "eyebrow",
            "document_type",
            "type",
        )
        or labels["generated_document"]
    )
    css_variables, body_classes = _layout_css(
        options,
        cover_full_bleed=cover_full_bleed,
        document_direction=document_direction,
    )

    cover_options = options
    base_dir = options.input_path.resolve().parent
    metadata_logo = _metadata_path(_first_metadata_value(metadata, "cover_logo", "logo"), base_dir)
    if metadata_logo and not options.cover_logo:
        cover_options = replace(options, cover_logo=metadata_logo)
    branding = _resolve_cover_branding(metadata, cover_options, base_dir)

    extra_details: list[tuple[str, Any]] = []
    detail_fields = [
        (labels["institution"], "institution", "university", "organization"),
        (labels["course"], "course", "lesson"),
        (labels["department"], "department"),
        (labels["supervisor"], "supervisor", "teacher", "advisor"),
        (labels["student_id"], "student_id", "student_number"),
        (labels["group"], "group", "team"),
        (labels["version"], "version"),
        (labels["status"], "status"),
        (labels["keywords"], "keywords", "tags"),
    ]
    for label, *keys in detail_fields:
        value = _first_metadata_value(metadata, *keys)
        if value not in (None, ""):
            extra_details.append((label, value))

    cover = (
        _cover_html(
            str(title),
            author,
            date,
            description,
            cover_options,
            subtitle=subtitle,
            extra_details=extra_details,
            eyebrow=eyebrow,
            lang=str(lang),
            document_direction=document_direction,
            labels=labels,
            branding=branding,
        )
        if include_cover and options.cover
        else ""
    )
    content = ""
    if include_content:
        content = f"{result.toc_html}{result.reference_lists_html}{result.body_html}{result.bibliography_html}"
    watermark = _watermark_html(options) if include_content and include_watermark else ""

    appearance_classes = appearance_body_classes(appearance)

    return f"""<!doctype html>
<html lang="{html.escape(str(lang))}" dir="{html.escape(document_direction)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(str(title))}</title>
  <style>{font_faces}</style>
  <style>{result.pygments_css}</style>
  <style>{style_css}</style>
  <style>{appearance_css}</style>
  <style>{css_variables}</style>
  {_mathjax_block(options)}
</head>
<body class="{html.escape(appearance_classes)} {html.escape(body_classes)}" dir="{html.escape(document_direction)}">
  {watermark}
  <main class="md2pdf-document">
    <article class="md2pdf-article">
      {cover}
      {content}
    </article>
  </main>
</body>
</html>"""



def _footer_template(
    context: FooterContext | str,
    style: str = "modern",
    mode: str = "light",
) -> str:
    if isinstance(context, FooterContext):
        title = context.title
        metadata = context.metadata
        lang = context.lang
        document_direction = context.document_direction
    else:
        title = str(context)
        metadata = ""
        lang = "en"
        document_direction = "ltr"

    kind = footer_kind(style, mode)
    color = "#64748b"
    rule_color = "#dbe3ef"
    font_family = "Vazirmatn, 'Noto Sans Arabic', Tahoma, Arial, sans-serif"
    title_weight = "650"
    page_weight = "700"
    if mode == "dark":
        color = "#cbd5e1"
        rule_color = "#475569"
        title_weight = "700"
        page_weight = "800"
    if kind == "textbook-light":
        color = "#374151"
        rule_color = "#d1d5db"
    elif kind == "textbook-dark":
        color = "#dbeafe"
        rule_color = "#64748b"
    elif kind == "academic":
        if mode == "dark":
            color = "#d1d5db"
            rule_color = "#6b7280"
        else:
            color = "#4b5563"
            rule_color = "#9ca3af"
        font_family = "Georgia, 'Times New Roman', Vazirmatn, serif"
        title_weight = "600"
        page_weight = "650"

    safe_title = html.escape(title)
    safe_meta = html.escape(metadata)
    page_label = html.escape(_footer_page_label(lang))
    title_align = "right" if document_direction == "rtl" else "left"
    center_style = (
        "position:absolute; left:50%; transform:translateX(-50%); "
        "max-width:35%; min-width:0; overflow:hidden; text-overflow:ellipsis; "
        "white-space:nowrap; text-align:center; opacity:.82; font-weight:600;"
    )
    meta_html = (
        f'<span dir="auto" style="{center_style}">{safe_meta}</span>'
        if safe_meta
        else '<span aria-hidden="true" style="position:absolute; left:50%; transform:translateX(-50%);"></span>'
    )
    if normalize_language(lang).startswith(RTL_LANG_PREFIXES):
        page_html = (
            f'<span dir="rtl" style="display:block; white-space:nowrap; text-align:left; direction:rtl; unicode-bidi:plaintext; font-weight:{page_weight}; font-family:Vazirmatn, Arial, sans-serif;">'
            f'{page_label} <span class="pageNumber"></span> از <span class="totalPages"></span></span>'
        )
    else:
        page_html = (
            f'<span dir="ltr" style="display:block; white-space:nowrap; text-align:right; direction:ltr; unicode-bidi:isolate; font-weight:{page_weight}; font-family:Arial, sans-serif;">'
            f'{page_label} <span class="pageNumber"></span>/<span class="totalPages"></span></span>'
        )
    title_html = (
        f'<span dir="auto" style="display:block; min-width:0; direction:{html.escape(document_direction)}; unicode-bidi:plaintext; '
        f'text-align:{title_align}; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; font-weight:{title_weight};">{safe_title}</span>'
    )
    if document_direction == "rtl":
        left_html = page_html
        right_html = title_html
    else:
        left_html = title_html
        right_html = page_html
    return f"""
    <div style="width:100%; font-size:8px; color:{color}; padding:0 16mm; font-family:{font_family};">
      <div style="position:relative; min-height:11px; border-top:1px solid {rule_color}; padding-top:4.5px; display:flex; align-items:center; justify-content:space-between; gap:5mm; direction:ltr;">
        <span style="display:block; width:35%; min-width:0;">{left_html}</span>
        {meta_html}
        <span style="display:block; width:35%; min-width:0;">{right_html}</span>
      </div>
    </div>
    """


_FONT_REPORT_SCRIPT = r"""
(requiredFonts) => {
  const normalize = value => String(value || '').replace(/["']/g, '').trim().toLowerCase();
  const loadedFaces = Array.from(document.fonts || []).map(face => ({
    family: String(face.family || '').replace(/["']/g, ''),
    status: String(face.status || ''),
    weight: String(face.weight || ''),
    style: String(face.style || ''),
  }));
  const canvas = document.createElement('canvas');
  const context = canvas.getContext('2d');
  const sample = 'mmmmmmmmmmlliWW00۱۲۳۴۵۶۷۸۹';
  const width = font => {
    context.font = `72px ${font}`;
    return context.measureText(sample).width;
  };
  const fontAvailable = family => {
    const target = normalize(family);
    if (loadedFaces.some(face => normalize(face.family) === target && face.status === 'loaded')) {
      return true;
    }
    return ['monospace', 'serif', 'sans-serif'].some(fallback => {
      const baseline = width(fallback);
      const candidate = width(`"${family}",${fallback}`);
      return Math.abs(candidate - baseline) > 0.01;
    });
  };
  const computed = selector => {
    const node = document.querySelector(selector);
    return node ? getComputedStyle(node).fontFamily : '';
  };
  const required = Array.from(requiredFonts || []);
  const availability = Object.fromEntries(required.map(name => [name, fontAvailable(name)]));
  return {
    status: document.fonts ? document.fonts.status : 'unsupported',
    required: availability,
    missing: required.filter(name => !availability[name]),
    computed: {
      body: computed('body'),
      article: computed('.md2pdf-article'),
      persian: computed('[lang^="fa"], [dir="rtl"]'),
      code: computed('code, pre'),
    },
    loaded_faces: loadedFaces,
  };
}
"""


_MATHJAX_REPORT_SCRIPT = r"""
async () => {
  const nodes = Array.from(document.querySelectorAll('.math'));
  const report = {
    detected: nodes.length,
    rendered: 0,
    unresolved: 0,
    available: Boolean(window.MathJax && window.MathJax.typesetPromise),
    errors: [],
    unresolved_samples: [],
    exception: '',
  };
  try {
    if (window.MathJax && window.MathJax.startup && window.MathJax.startup.promise) {
      await window.MathJax.startup.promise;
    }
    if (window.MathJax && window.MathJax.typesetPromise) {
      await window.MathJax.typesetPromise();
    }
  } catch (error) {
    report.exception = String(error && (error.stack || error.message) || error);
  }
  for (const node of nodes) {
    if (node.querySelector('mjx-container')) {
      report.rendered += 1;
    } else {
      report.unresolved += 1;
      if (report.unresolved_samples.length < 5) {
        report.unresolved_samples.push(String(node.textContent || '').trim().slice(0, 160));
      }
    }
  }
  report.errors = Array.from(document.querySelectorAll('mjx-merror, [data-mjx-error]'))
    .slice(0, 10)
    .map(node => String(node.textContent || node.getAttribute('data-mjx-error') || '').trim().slice(0, 240));
  return report;
}
"""


def _validate_browser_fonts(page: Page, options: PdfOptions, *, artifact: Path) -> None:
    if not options.required_fonts and options.quality_report is None:
        return
    try:
        report = page.evaluate(_FONT_REPORT_SCRIPT, list(options.required_fonts))
    except Exception as exc:
        _enforce_quality_issue(
            options,
            category="fonts",
            policy=options.font_error_policy or "warn",
            message=f"Browser font validation failed: {exc}",
            details={"artifact": artifact.name, "required_fonts": list(options.required_fonts)},
            error_type=FontValidationError,
        )
        return
    details = dict(report or {})
    details["artifact"] = artifact.name
    details["font_directory"] = str(options.font_dir) if options.font_dir else None
    details["font_files"] = _font_directory_manifest(options.font_dir)
    missing = [str(name) for name in details.get("missing") or []]
    if missing:
        _enforce_quality_issue(
            options,
            category="fonts",
            policy=options.font_error_policy or "warn",
            message=f"Required publication fonts are unavailable: {', '.join(missing)}",
            details=details,
            error_type=FontValidationError,
        )
        return
    options.quality_log.record(
        "fonts",
        "passed",
        "Required publication fonts are available." if options.required_fonts else "Browser font evidence collected.",
        details=details,
    )


def _typeset_and_validate_mathjax(page: Page, options: PdfOptions, *, artifact: Path) -> None:
    try:
        report = page.evaluate(_MATHJAX_REPORT_SCRIPT)
    except Exception as exc:
        _enforce_quality_issue(
            options,
            category="mathjax",
            policy=options.math_error_policy or "warn",
            message=f"MathJax rendering failed; equations may remain in TeX form: {exc}",
            details={"artifact": artifact.name, "exception": str(exc)},
            error_type=MathJaxRenderError,
        )
        return
    details = dict(report or {})
    details["artifact"] = artifact.name
    detected = int(details.get("detected") or 0)
    rendered = int(details.get("rendered") or 0)
    unresolved = int(details.get("unresolved") or 0)
    errors = list(details.get("errors") or [])
    exception = str(details.get("exception") or "")
    available = bool(details.get("available"))
    failed = bool(exception or errors or unresolved or (detected and not available) or rendered != detected)
    if failed:
        _enforce_quality_issue(
            options,
            category="mathjax",
            policy=options.math_error_policy or "warn",
            message=(
                "MathJax did not render every detected expression "
                f"(detected={detected}, rendered={rendered}, unresolved={unresolved})."
            ),
            details=details,
            error_type=MathJaxRenderError,
        )
        return
    options.quality_log.record(
        "mathjax",
        "passed",
        f"MathJax rendered {rendered} of {detected} detected expressions.",
        details=details,
    )


def _render_pdf(
    page: Page,
    html_text: str,
    options: PdfOptions,
    path: Path,
    *,
    display_footer: bool,
    footer_context: FooterContext | str,
) -> None:
    _resolve_quality_options(options)
    page.set_content(html_text, wait_until="load")
    page.evaluate("() => document.fonts && document.fonts.ready")
    _validate_browser_fonts(page, options, artifact=path)
    if not options.no_mathjax:
        _typeset_and_validate_mathjax(page, options, artifact=path)
    page.emulate_media(media="print")
    pdf_kwargs: dict[str, Any] = {
        "path": str(path),
        "print_background": True,
        "prefer_css_page_size": True,
        "margin": {"top": "0", "right": "0", "bottom": "0", "left": "0"},
    }
    pdf_kwargs.update(_playwright_page_size_kwargs(options.page_size))
    if display_footer and not options.no_header_footer:
        pdf_kwargs.update(
            {
                "display_header_footer": True,
                "header_template": "<div></div>",
                "footer_template": _footer_template(footer_context, options.style, options.mode),
            }
        )
    page.pdf(**pdf_kwargs)


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
    creator = html.escape(str(metadata.get("/Creator") or "Mardas MD2PDF"))
    producer = html.escape(str(metadata.get("/Producer") or "Mardas MD2PDF"))
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
    if hasattr(preferences, "get_object"):
        preferences = preferences.get_object()
    if not isinstance(preferences, DictionaryObject):
        preferences = DictionaryObject()
        writer.root_object[NameObject("/ViewerPreferences")] = preferences
    preferences[NameObject("/DisplayDocTitle")] = BooleanObject(True)
    writer.xmp_metadata = _xmp_packet(metadata, lang=language)
    metadata_stream = writer.root_object[NameObject("/Metadata")].get_object()
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
        "/Creator": "Mardas MD2PDF",
        "/Producer": "Mardas MD2PDF + Playwright/Chromium + pypdf",
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


def _should_disable_chromium_sandbox(mode: str) -> bool:
    normalized = (mode or "auto").strip().lower()
    if normalized == "off":
        return True
    if normalized == "on":
        return False
    if normalized != "auto":
        raise ValueError("chromium_sandbox must be one of: auto, on, off")
    geteuid = getattr(os, "geteuid", None)
    return bool(geteuid and geteuid() == 0)


def _chromium_launch_args(options: PdfOptions) -> list[str]:
    args = [
        "--font-render-hinting=medium",
        "--disable-dev-shm-usage",
    ]
    if _should_disable_chromium_sandbox(options.chromium_sandbox):
        args.append("--no-sandbox")
    return args


def _resolve_pdf_chromium_path(options: PdfOptions) -> None:
    """Attach the lazily discovered browser only at the PDF rendering boundary."""

    if options.chromium_path:
        return
    resolved = resolved_chromium_path()
    if resolved is not None:
        options.chromium_path = str(resolved)


class RenderSession:
    """Thread-affine reusable Chromium session for repeated PDF exports.

    A fresh browser context is created for every conversion, so cookies, page
    state, and temporary object URLs never leak between documents.  Only the
    expensive Playwright and Chromium process lifecycle is reused.
    """

    def __init__(self) -> None:
        self._owner_thread: int | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._browser_key: tuple[str | None, tuple[str, ...]] | None = None
        self.launch_count = 0
        self.page_count = 0
        self.last_page_reused_browser = False

    def __enter__(self) -> "RenderSession":
        self._claim_thread()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _claim_thread(self) -> None:
        current = threading.get_ident()
        if self._owner_thread is None:
            self._owner_thread = current
        elif self._owner_thread != current:
            raise RuntimeError("RenderSession must only be used from its owning thread.")

    def _close_browser(self) -> None:
        browser, self._browser = self._browser, None
        self._browser_key = None
        if browser is not None:
            try:
                browser.close()
            except Exception:
                LOGGER.debug("Failed to close reusable Chromium browser", exc_info=True)

    def close(self) -> None:
        self._claim_thread()
        self._close_browser()
        playwright, self._playwright = self._playwright, None
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                LOGGER.debug("Failed to stop reusable Playwright session", exc_info=True)

    def restart(self) -> None:
        """Discard the current browser so the next conversion launches cleanly."""
        self._claim_thread()
        self._close_browser()

    def _ensure_browser(self, options: PdfOptions) -> tuple[Browser, bool]:
        self._claim_thread()
        _resolve_pdf_chromium_path(options)
        executable = options.chromium_path or shutil.which("chromium") or shutil.which("google-chrome")
        key = (executable, tuple(_chromium_launch_args(options)))
        reusable = bool(
            self._browser is not None
            and self._browser_key == key
            and self._browser.is_connected()
        )
        if reusable:
            return self._browser, True

        self._close_browser()
        if self._playwright is None:
            self._playwright = sync_playwright().start()
        launch_kwargs: dict[str, Any] = {"headless": True, "args": list(key[1])}
        if executable:
            launch_kwargs["executable_path"] = executable
        self._browser = self._playwright.chromium.launch(**launch_kwargs)
        self._browser_key = key
        self.launch_count += 1
        return self._browser, False

    @contextmanager
    def page(self, options: PdfOptions) -> Iterator[Page]:
        browser, reused = self._ensure_browser(options)
        self.last_page_reused_browser = reused
        context: BrowserContext | None = None
        try:
            context = browser.new_context(device_scale_factor=1)
            page = context.new_page()
            page.set_default_timeout(options.timeout_ms)
            self.page_count += 1
            yield page
        except Exception:
            if self._browser is not None and not self._browser.is_connected():
                self.restart()
            raise
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    self.restart()


@contextmanager
def _render_page(
    options: PdfOptions, session: RenderSession | None
) -> Iterator[tuple[Page, bool]]:
    if session is not None:
        with session.page(options) as page:
            yield page, session.last_page_reused_browser
        return
    with RenderSession() as owned_session:
        with owned_session.page(options) as page:
            yield page, False


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
    for left_label, left, right_label, right in pairs:
        if _paths_refer_to_same_file(left, right):
            raise OutputPathError(
                f"The {left_label} and {right_label} paths must reference different files."
            )


def _open_atomic_output(path: Path) -> tuple[int, Path]:
    """Create a collision-safe sibling temporary file while honoring the process umask."""
    path = Path(path)
    existing_mode: int | None = None
    try:
        existing_mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        pass

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    for _attempt in range(100):
        temporary_path = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
        try:
            fd = os.open(temporary_path, flags, 0o666)
        except FileExistsError:
            continue
        try:
            if existing_mode is not None:
                if hasattr(os, "fchmod"):
                    os.fchmod(fd, existing_mode)
                else:  # pragma: no cover - Windows fallback.
                    os.chmod(temporary_path, existing_mode)
        except Exception:
            os.close(fd)
            temporary_path.unlink(missing_ok=True)
            raise
        return fd, temporary_path
    raise FileExistsError(f"Could not allocate an atomic temporary file for: {path}")


def _atomic_write_pdf(writer: PdfWriter, output_path: Path) -> None:
    """Commit a complete PDF with an atomic same-directory replacement."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_path = _open_atomic_output(output_path)
    try:
        with os.fdopen(fd, "wb") as fh:
            writer.write(fh)
            fh.flush()
            os.fsync(fh.fileno())
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
        _atomic_write_pdf(writer, output_path)
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
        _atomic_write_pdf(writer, output_path)
    finally:
        writer.close()


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
    _resolve_quality_options(options)
    _validate_conversion_paths(options)
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

    with tempfile.TemporaryDirectory(prefix="mardas-md2pdf-") as tmpdir:
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
    _check_cancel(options)
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

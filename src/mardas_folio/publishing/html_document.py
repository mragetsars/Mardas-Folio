"""Publication HTML, cover composition, embedded assets, and appearance payloads."""

from __future__ import annotations

import base64
import html
import mimetypes
import re
import stat
import unicodedata
import warnings
from dataclasses import dataclass, replace
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from ..appearance import (
    Appearance,
    appearance_body_classes,
    appearance_from_metadata,
    footer_kind,
    palette_css,
    resolve_appearance,
    style_css_file,
)
from ..brand_assets import product_logo_path
from ..markdown import MarkdownRenderResult
from ..page_geometry import page_geometry
from ..print_layout import layout_css as _build_layout_css
from ..quality import MathJaxRenderError
from ..render_contracts import DocumentAssetError, PdfOptions, validate_branding_mode
from .quality import _enforce_quality_issue

RTL_LANG_PREFIXES = ("ar", "fa", "he", "iw", "ku", "ps", "sd", "ug", "ur", "yi")
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
PRODUCT_BRAND_NAME = "Mardas Folio"
PRODUCT_BRAND_FOOTER = "Markdown to PDF Engine"
_MATH_SPAN_RE = re.compile(r'<(?:span|div)[^>]*\bclass="[^"]*\bmath\b', re.IGNORECASE)


def _layout_css(
    options: PdfOptions, *, cover_full_bleed: bool = False, document_direction: str = "rtl"
) -> tuple[str, str]:
    return _build_layout_css(
        options,
        cover_full_bleed=cover_full_bleed,
        document_direction=normalize_document_direction(document_direction, default="rtl"),
    )


@lru_cache(maxsize=16)
def _asset_text(relative_path: str) -> str:
    return (resources.files("mardas_folio") / "assets" / relative_path).read_text(encoding="utf-8")


def _asset_path(relative_path: str) -> Path:
    return Path(str(resources.files("mardas_folio") / "assets" / relative_path))


@lru_cache(maxsize=8)
def _cached_font_data_uri(path_text: str, mtime_ns: int, size: int, font_format: str) -> str:
    del mtime_ns, size
    mime = "font/woff2" if font_format == "woff2" else "font/ttf"
    encoded = base64.b64encode(Path(path_text).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _font_source_url(path: Path, font_format: str, *, embed: bool) -> str:
    """A URL the consumer can actually load the font from.

    Chromium is handed the page over ``set_content`` and reads ``file://``
    happily. The desktop preview runs inside a webview whose content-security
    policy forbids it, so the same font has to arrive as a data URI there.
    """
    if not embed:
        return path.as_uri()
    stats = path.stat()
    return _cached_font_data_uri(str(path), stats.st_mtime_ns, stats.st_size, font_format)


def _font_faces(font_dir: Path | None, *, embed: bool = False) -> str:
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
                weight = (
                    "100 900" if "[wght]" in filename else ("800" if "Bold" in family else "400")
                )
                family_name = "Vazirmatn"
                font_format = "truetype" if filename.lower().endswith(".ttf") else "woff2"
                url = _font_source_url(path, font_format, embed=embed)
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


def preview_appearance_payload(metadata: dict[str, Any], options: PdfOptions) -> dict[str, Any]:
    """The stylesheets and body classes the PDF would be built with.

    The authoring preview otherwise shows generic Markdown, which cannot answer
    the question the export screen exists to answer: what will the published
    document look like. Returning the same style sheet, palette and body classes
    the renderer uses lets the preview be the real appearance rather than an
    approximation of it.
    """
    appearance = _resolved_appearance(metadata, options)
    return {
        "style": appearance.style,
        "palette": appearance.palette,
        "mode": appearance.mode,
        "style_css": _style_css(appearance),
        "palette_css": palette_css(appearance.palette, appearance.mode, appearance.style),
        "body_classes": appearance_body_classes(appearance),
    }


def preview_page_payload(
    result: MarkdownRenderResult,
    options: PdfOptions,
) -> dict[str, Any]:
    """The published page, in the pieces a paginated preview has to draw.

    The exporter prints a full-bleed cover as its own PDF and the content with
    the running footer as a second one, then merges them. A preview that wants
    to be believable has to reproduce that structure — including the fact that
    the cover has no margins and no page number — so both compositions are
    returned rather than one flattened article.

    MathJax is deliberately absent: it is a two-megabyte script the exporter
    runs inside Chromium, and the preview reports how many expressions are
    waiting for it instead of pretending to typeset them.
    """

    content = compose_document(
        result,
        options,
        include_cover=False,
        include_content=True,
        include_watermark=True,
        embed_fonts=True,
    )
    cover = (
        compose_document(
            result,
            options,
            include_cover=True,
            include_content=False,
            include_watermark=False,
            cover_full_bleed=True,
            embed_fonts=True,
        )
        if options.cover
        else None
    )
    footer_context = _footer_context(result, options, content.title)
    return {
        "title": content.title,
        "lang": content.lang,
        "direction": content.document_direction,
        "page": page_geometry(options),
        "css": {
            "fonts": content.font_faces_css,
            "pygments": content.pygments_css,
            "style": content.style_css,
            "palette": content.palette_css,
            "layout": content.layout_css,
        },
        "body_classes": f"{content.appearance_classes} {content.body_classes}".strip(),
        "content_html": content.content_html,
        "watermark_html": content.watermark_html,
        "cover": None
        if cover is None
        else {
            "html": cover.cover_html,
            "layout_css": cover.layout_css,
            "body_classes": f"{cover.appearance_classes} {cover.body_classes}".strip(),
        },
        "footer": {
            "enabled": not options.no_header_footer,
            "html": _footer_template(footer_context, options.style, options.mode),
            "page_label": _footer_page_label(footer_context.lang),
        },
        "math": {
            "typeset_at_export": not options.no_mathjax,
            "expressions": _count_math_expressions(content.content_html),
        },
    }


def _count_math_expressions(html_text: str) -> int:
    return len(_MATH_SPAN_RE.findall(html_text or ""))


def _path_uri(path: Path | None) -> str | None:
    if not path:
        return None
    return path.resolve().as_uri()


@lru_cache(maxsize=16)
def _cached_small_image_data_uri(path_text: str, mtime_ns: int, size: int, mime_type: str) -> str:
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
    """Return the packaged Mardas Folio product logo for built-in branding."""
    return product_logo_path(variant=variant)


def _cover_logo_uri(options: PdfOptions) -> str | None:
    if not options.cover_logo_enabled:
        return None
    return _image_data_uri(
        options.cover_logo or options.brand_logo or _default_logo_path(variant="cover-label")
    )


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


def _resolve_cover_branding(
    metadata: dict[str, Any], options: PdfOptions, base_dir: Path
) -> CoverBranding:
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

    has_user_brand = bool(
        _stringify_metadata_value(brand_name) or _stringify_metadata_value(brand_footer) or logo
    )
    mode = validate_branding_mode(explicit_mode or ("full" if has_user_brand else "off"))

    product_brand = not has_user_brand
    name = _stringify_metadata_value(brand_name) or PRODUCT_BRAND_NAME
    footer = _stringify_metadata_value(brand_footer) or (
        PRODUCT_BRAND_FOOTER if product_brand else ""
    )

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
            f"<strong>Generated with {html.escape(PRODUCT_BRAND_NAME)}</strong>"
            "</span>"
            "</div>"
        )
    mark_html = (
        ""
        if branding.mode == "subtle"
        else f'<span class="md2pdf-cover__mark">{_brand_logo_html(branding)}</span>'
    )
    footer_html = f"<em>{html.escape(branding.footer)}</em>" if branding.footer else ""
    brand_kind = "product" if branding.product else "custom"
    brand_classes = (
        f"md2pdf-cover__brand md2pdf-cover__brand--{html.escape(branding.mode)} "
        f"md2pdf-cover__brand--{brand_kind}"
    )
    return (
        f'<div class="{brand_classes}" dir="ltr">'
        f"{mark_html}"
        '<span class="md2pdf-cover__brand-copy">'
        f"<strong>{html.escape(branding.name)}</strong>"
        f"{footer_html}"
        "</span>"
        "</div>"
    )


def _watermark_html(options: PdfOptions) -> str:
    if options.watermark_image:
        image_uri = _image_data_uri(options.watermark_image)
        if image_uri:
            return (
                '<div class="md2pdf-watermark md2pdf-watermark--image" aria-hidden="true" '
                f'style="--watermark-opacity: {options.watermark_opacity}; --watermark-width: {html.escape(options.watermark_width)};">'
                f'<img src="{html.escape(image_uri)}" alt="">'
                "</div>"
            )
    if options.watermark_text:
        return (
            '<div class="md2pdf-watermark md2pdf-watermark--text" aria-hidden="true" '
            f'style="--watermark-opacity: {options.watermark_opacity};">'
            f"{html.escape(options.watermark_text)}"
            "</div>"
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


def _resolved_document_direction(
    result: MarkdownRenderResult, options: PdfOptions, lang: str
) -> str:
    metadata = result.metadata
    requested = normalize_document_direction(
        options.document_direction
        if options.document_direction not in (None, "")
        else _first_metadata_value(
            metadata, "dir", "direction", "text_direction", "document_direction"
        ),
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
    course = _stringify_metadata_value(
        _first_metadata_value(metadata, "course", "institution")
    ).strip()
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
        f"<span>{html.escape(label)}</span>"
        f"<strong>{value_html}</strong>"
        "</div>"
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
        raise DocumentAssetError(f'Front-matter image path "{text}" must reference a regular file.')
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
        f'<p class="md2pdf-cover__subtitle" dir="auto">{html.escape(subtitle_text)}</p>'
        if subtitle_text
        else ""
    )
    summary_html = _paragraph_block_html(description, "md2pdf-cover__summary")
    details_html = "".join(detail_cards)
    branding = branding or CoverBranding(
        mode="off", name=PRODUCT_BRAND_NAME, footer=PRODUCT_BRAND_FOOTER, logo=None, product=True
    )
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
        {'<section class="md2pdf-cover__details">' + details_html + "</section>" if details_html else "<div></div>"}
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


@dataclass(frozen=True)
class DocumentComposition:
    """The finished page, kept as parts rather than as one HTML string.

    ``build_html`` used to be the only way to obtain any of this, which meant the
    only consumer that could see the real published page was the PDF renderer
    itself. Splitting composition from serialisation lets the desktop preview
    draw the same cover, contents, watermark and stylesheets the exporter uses,
    instead of approximating them.
    """

    lang: str
    document_direction: str
    title: str
    body_classes: str
    appearance_classes: str
    font_faces_css: str
    pygments_css: str
    style_css: str
    palette_css: str
    layout_css: str
    cover_html: str
    content_html: str
    watermark_html: str
    mathjax_block: str


def compose_document(
    result: MarkdownRenderResult,
    options: PdfOptions,
    *,
    include_cover: bool = True,
    include_content: bool = True,
    include_watermark: bool = True,
    cover_full_bleed: bool = False,
    include_mathjax: bool | None = None,
    embed_fonts: bool = False,
) -> DocumentComposition:
    """Assemble every part of the published page for one document."""

    if include_mathjax is not None:
        options = replace(options, no_mathjax=not include_mathjax)
    appearance = _resolved_appearance(result.metadata, options)
    options = replace(
        options, style=appearance.style, palette=appearance.palette, mode=appearance.mode
    )
    style_css = _style_css(appearance)
    appearance_css = palette_css(appearance.palette, appearance.mode, appearance.style)
    font_faces = _font_faces(options.font_dir, embed=embed_fonts)
    metadata = result.metadata
    title = options.title or _stringify_metadata_value(metadata.get("title")) or result.title
    author = (
        options.author
        if options.author is not None
        else _first_metadata_value(metadata, "authors", "author")
    )
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

    return DocumentComposition(
        lang=str(lang),
        document_direction=document_direction,
        title=str(title),
        body_classes=body_classes,
        appearance_classes=appearance_body_classes(appearance),
        font_faces_css=font_faces,
        pygments_css=result.pygments_css,
        style_css=style_css,
        palette_css=appearance_css,
        layout_css=css_variables,
        cover_html=cover,
        content_html=content,
        watermark_html=watermark,
        mathjax_block=_mathjax_block(options),
    )


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
    composed = compose_document(
        result,
        options,
        include_cover=include_cover,
        include_content=include_content,
        include_watermark=include_watermark,
        cover_full_bleed=cover_full_bleed,
        include_mathjax=include_mathjax,
    )

    return f"""<!doctype html>
<html lang="{html.escape(composed.lang)}" dir="{html.escape(composed.document_direction)}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(composed.title)}</title>
  <style>{composed.font_faces_css}</style>
  <style>{composed.pygments_css}</style>
  <style>{composed.style_css}</style>
  <style>{composed.palette_css}</style>
  <style>{composed.layout_css}</style>
  {composed.mathjax_block}
</head>
<body class="{html.escape(composed.appearance_classes)} {html.escape(composed.body_classes)}" dir="{html.escape(composed.document_direction)}">
  {composed.watermark_html}
  <main class="md2pdf-document">
    <article class="md2pdf-article">
      {composed.cover_html}
      {composed.content_html}
    </article>
  </main>
</body>
</html>"""


def _footer_template(
    context: FooterContext | str,
    style: str | None = "modern",
    mode: str | None = "light",
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

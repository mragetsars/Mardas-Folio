"""Publication options, callbacks, and exceptions independent of the browser runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .quality import RenderQualityLog

ProgressCallback = Callable[[str, float], None]
CancellationCallback = Callable[[], bool]
BRANDING_MODES = ("off", "subtle", "full")
BODY_TYPOGRAPHY_FIELDS = ("body_font", "body_size_pt", "body_leading", "paragraph_align")


class DocumentAssetError(ValueError):
    """Raised when document metadata references an unsafe local asset."""


class OutputPathError(ValueError):
    """Raised when conversion paths overlap or target invalid filesystem objects."""


class OutputExistsError(OutputPathError):
    """A create-only output could not be committed without overwriting a file."""


class OutputSidecarUnsupportedError(OutputPathError):
    """A create-only export includes an auxiliary output without safe commit support."""


class RenderCancelledError(RuntimeError):
    """Raised when a caller cancels rendering at a safe checkpoint."""


def validate_branding_mode(value: str | None) -> str:
    """Validate and normalize cover branding mode names."""
    normalized = str(value or "off").strip().lower()
    if normalized not in BRANDING_MODES:
        allowed = ", ".join(BRANDING_MODES)
        raise ValueError(f"must be one of: {allowed}")
    return normalized


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
    body_font: str = "theme"
    body_size_pt: float = 11.0
    body_leading: float = 1.6
    paragraph_align: str = "justify"
    project_typography: frozenset[str] = frozenset()
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
    protected_inputs: tuple[tuple[str, Path], ...] = field(default_factory=tuple, repr=False)
    output_create_only: bool = False

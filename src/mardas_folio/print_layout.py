"""Compose dynamic print variables with the bundled, static publication stylesheet."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources

from .appearance import math_scale_vars, resolve_appearance
from .page_geometry import _css_page_size
from .render_contracts import PdfOptions


@lru_cache(maxsize=1)
def _base_css() -> str:
    return (resources.files("mardas_folio") / "assets" / "print-layout.css").read_text(
        encoding="utf-8"
    )


def layout_css(
    options: PdfOptions, *, cover_full_bleed: bool = False, document_direction: str = "rtl"
) -> tuple[str, str]:
    """Return publication CSS and root classes; direction is normalized by the renderer."""
    appearance = resolve_appearance(style=options.style, palette=options.palette, mode=options.mode)
    inline_math_scale, display_math_scale = math_scale_vars(appearance.style)
    margins = (
        "0"
        if cover_full_bleed
        else (
            f"var(--page-margin-top, {options.margin_top}) "
            f"var(--page-margin-x, {options.margin_x}) "
            f"var(--page-margin-bottom, {options.margin_bottom})"
        )
    )
    variables = f"""
      @page {{
        size: {_css_page_size(options.page_size)};
        margin: {margins};
      }}
      :root {{
        --page-margin-top: {"0" if cover_full_bleed else options.margin_top};
        --page-margin-bottom: {"0" if cover_full_bleed else options.margin_bottom};
        --page-margin-x: {"0" if cover_full_bleed else options.margin_x};
        --md2pdf-document-direction: {document_direction};
        --md2pdf-inline-math-scale: {inline_math_scale};
        --md2pdf-display-math-scale: {display_math_scale};
        --md2pdf-code-highlight-bg: color-mix(in srgb, var(--accent, #2563eb) 24%, var(--code-bg, #0f172a));
        --md2pdf-code-highlight-border: color-mix(in srgb, var(--accent, #2563eb) 52%, transparent);
      }}
"""
    # Apply the same composed CSS to the page-preview payload and the print document.
    families = {
        "sans": 'Arial, "Vazirmatn", "Noto Sans Arabic", sans-serif',
        "serif": 'Georgia, "Noto Naskh Arabic", "Times New Roman", serif',
        "vazirmatn": '"Vazirmatn", "Noto Sans Arabic", Tahoma, sans-serif',
    }
    size, leading = float(options.body_size_pt), float(options.body_leading)
    if not 7 <= size <= 30 or not 1 <= leading <= 2.5:
        raise ValueError("Invalid body typography")
    if options.paragraph_align not in {"justify", "start", "center", "end"}:
        raise ValueError("Invalid paragraph alignment")
    if options.body_font != "theme" and options.body_font not in families:
        raise ValueError("Invalid body font")
    family = families.get(options.body_font)
    font_rule = f"font-family: {family};" if family else ""
    prose = """
      body .md2pdf-document .md2pdf-article :is(p, li):not(:where(
        .md2pdf-cover *, nav *, .toc *, .md2pdf-toc *, table *, figure *,
        .highlight *, .callout *, .footnote *, .md2pdf-list-of *, .md2pdf-bibliography *
      ))"""
    typography = f"""{prose} {{
        font-size: {size:g}pt; line-height: {leading:g}; {font_rule}
        text-align: {options.paragraph_align}; text-align-last: auto; orphans: 2; widows: 2;
      }}"""
    classes = []
    if cover_full_bleed:
        classes.append("md2pdf-cover-full-bleed")
    classes.append(f"md2pdf-dir-{document_direction}")
    if options.toc_page_break:
        classes.append("md2pdf-toc-break")
    if options.h1_page_break:
        classes.append("md2pdf-h1-break")
    # Preserve the existing serializer's trailing indent for deterministic HTML.
    return variables + _base_css() + typography + "    ", " ".join(classes)

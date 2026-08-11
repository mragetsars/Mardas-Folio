from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_STYLE = "modern"
DEFAULT_PALETTE = "blue"
DEFAULT_MODE = "light"

STYLE_FILES = {
    "modern": {"light": "style-modern.css", "dark": "style-modern.css"},
    "github": {"light": "style-github.css", "dark": "style-github.css"},
    "textbook": {"light": "style-textbook.css", "dark": "style-textbook.css"},
    "academic": {"light": "style-academic.css", "dark": "style-academic.css"},
}
STYLES = tuple(STYLE_FILES)
STYLE_DESCRIPTIONS = {
    "modern": "Clean rounded document layout for reports and guides.",
    "github": "README-friendly layout for technical documentation.",
    "textbook": "Compact print-first layout for course notes and long documents.",
    "academic": "Formal serif-leaning layout for papers and academic reports.",
}
MODES = ("light", "dark")
MODE_DESCRIPTIONS = {
    "light": "Light paper-like output for ordinary print and sharing.",
    "dark": "Dark output for screen-first documents and high-contrast previews.",
}

PALETTES: dict[str, dict[str, str]] = {
    "blue": {
        "accent": "#2563eb",
        "accent_2": "#7c3aed",
        "accent_soft": "#eef4ff",
        "accent_line": "#5aa6e8",
        "quote": "#eff6ff",
    },
    "emerald": {
        "accent": "#047857",
        "accent_2": "#0f766e",
        "accent_soft": "#ecfdf5",
        "accent_line": "#34d399",
        "quote": "#ecfdf5",
    },
    "violet": {
        "accent": "#7c3aed",
        "accent_2": "#db2777",
        "accent_soft": "#f5f3ff",
        "accent_line": "#a78bfa",
        "quote": "#f5f3ff",
    },
    "amber": {
        "accent": "#b45309",
        "accent_2": "#92400e",
        "accent_soft": "#fffbeb",
        "accent_line": "#f59e0b",
        "quote": "#fffbeb",
    },
    "rose": {
        "accent": "#e11d48",
        "accent_2": "#be123c",
        "accent_soft": "#fff1f2",
        "accent_line": "#fb7185",
        "quote": "#fff1f2",
    },
    "slate": {
        "accent": "#475569",
        "accent_2": "#0f172a",
        "accent_soft": "#f1f5f9",
        "accent_line": "#94a3b8",
        "quote": "#f8fafc",
    },
    "neutral": {
        "accent": "#404040",
        "accent_2": "#171717",
        "accent_soft": "#f5f5f5",
        "accent_line": "#a3a3a3",
        "quote": "#fafafa",
    },
}

DARK_PALETTES: dict[str, dict[str, str]] = {
    "blue": {
        "accent": "#60a5fa",
        "accent_2": "#a78bfa",
        "accent_soft": "#172554",
        "accent_line": "#3b82f6",
        "quote": "#111827",
    },
    "emerald": {
        "accent": "#34d399",
        "accent_2": "#2dd4bf",
        "accent_soft": "#064e3b",
        "accent_line": "#10b981",
        "quote": "#0f172a",
    },
    "violet": {
        "accent": "#a78bfa",
        "accent_2": "#f0abfc",
        "accent_soft": "#2e1065",
        "accent_line": "#8b5cf6",
        "quote": "#111827",
    },
    "amber": {
        "accent": "#fbbf24",
        "accent_2": "#f97316",
        "accent_soft": "#451a03",
        "accent_line": "#f59e0b",
        "quote": "#171717",
    },
    "rose": {
        "accent": "#fb7185",
        "accent_2": "#f472b6",
        "accent_soft": "#4c0519",
        "accent_line": "#f43f5e",
        "quote": "#111827",
    },
    "slate": {
        "accent": "#cbd5e1",
        "accent_2": "#94a3b8",
        "accent_soft": "#1e293b",
        "accent_line": "#94a3b8",
        "quote": "#171717",
    },
    "neutral": {
        "accent": "#d4d4d4",
        "accent_2": "#a3a3a3",
        "accent_soft": "#262626",
        "accent_line": "#a3a3a3",
        "quote": "#171717",
    },
}

PALETTES_ORDER = tuple(PALETTES)
PALETTE_DESCRIPTIONS = {
    "blue": "Default professional blue accents.",
    "emerald": "Green accents for calm reports and dashboards.",
    "violet": "Purple accents for creative and product documents.",
    "amber": "Warm amber accents for teaching and review documents.",
    "rose": "Rose accents for editorial or highlighted reports.",
    "slate": "Cool neutral accents for understated technical documents.",
    "neutral": "Minimal grayscale accents for formal output.",
}


@dataclass(frozen=True, slots=True)
class Appearance:
    """Resolved visual system for a PDF output.

    ``style`` controls layout/shape choices, ``palette`` controls accent colors,
    and ``mode`` controls light/dark contrast.  These are intentionally separate
    so users can reason about document shape, color, and contrast independently.
    """

    style: str = DEFAULT_STYLE
    palette: str = DEFAULT_PALETTE
    mode: str = DEFAULT_MODE


def _clean(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_style_name(value: Any) -> str:
    candidate = _clean(value) or DEFAULT_STYLE
    return candidate if candidate in STYLES else DEFAULT_STYLE


def normalize_palette_name(value: Any) -> str:
    candidate = _clean(value) or DEFAULT_PALETTE
    return candidate if candidate in PALETTES else DEFAULT_PALETTE


def normalize_mode_name(value: Any) -> str:
    candidate = _clean(value) or DEFAULT_MODE
    return candidate if candidate in MODES else DEFAULT_MODE


def validate_style_name(value: Any) -> str:
    candidate = _clean(value) or DEFAULT_STYLE
    if candidate not in STYLES:
        choices = ", ".join(STYLES)
        raise ValueError(f"style must be one of: {choices}")
    return candidate


def validate_palette_name(value: Any) -> str:
    candidate = _clean(value) or DEFAULT_PALETTE
    if candidate not in PALETTES:
        choices = ", ".join(PALETTES_ORDER)
        raise ValueError(f"palette must be one of: {choices}")
    return candidate


def validate_mode_name(value: Any) -> str:
    candidate = _clean(value) or DEFAULT_MODE
    if candidate not in MODES:
        choices = ", ".join(MODES)
        raise ValueError(f"mode must be one of: {choices}")
    return candidate


def resolve_appearance(*, style: Any = None, palette: Any = None, mode: Any = None) -> Appearance:
    return Appearance(
        style=normalize_style_name(style),
        palette=normalize_palette_name(palette),
        mode=normalize_mode_name(mode),
    )


def appearance_from_metadata(metadata: dict[str, Any]) -> Appearance:
    raw = metadata.get("appearance")
    if isinstance(raw, dict):
        return resolve_appearance(
            style=raw.get("style"),
            palette=raw.get("palette"),
            mode=raw.get("mode"),
        )
    return resolve_appearance(
        style=metadata.get("style"),
        palette=metadata.get("palette"),
        mode=metadata.get("mode"),
    )


def style_css_file(style: str, mode: str) -> str:
    resolved = resolve_appearance(style=style, mode=mode)
    return STYLE_FILES[resolved.style][resolved.mode]


def code_style_for_appearance(style: str, mode: str) -> str:
    appearance = resolve_appearance(style=style, mode=mode)
    if appearance.mode == "dark":
        return "bw"
    if appearance.style in {"github", "textbook", "academic"}:
        return "friendly"
    return "github-dark"


def math_scale_vars(style: str) -> tuple[str, str]:
    resolved_style = normalize_style_name(style)
    if resolved_style == "academic":
        return "70%", "105%"
    if resolved_style == "textbook":
        return "78%", "115%"
    return "100%", "130%"


def footer_kind(style: str, mode: str) -> str:
    appearance = resolve_appearance(style=style, mode=mode)
    if appearance.style == "textbook":
        return "textbook-dark" if appearance.mode == "dark" else "textbook-light"
    return appearance.style


def appearance_body_classes(appearance: Appearance) -> str:
    return " ".join(
        [
            f"md2pdf-style-{appearance.style}",
            f"md2pdf-palette-{appearance.palette}",
            f"md2pdf-mode-{appearance.mode}",
        ]
    )


DARK_STYLE_SURFACES: dict[str, dict[str, str]] = {
    "modern": {
        "page": "#0b1020",
        "surface": "#0b1020",
        "panel": "#111827",
        "panel_alt": "#0f172a",
        "panel_soft": "#182235",
        "code": "#020617",
        "line": "#334155",
        "line_strong": "#475569",
        "ink": "#e5e7eb",
        "heading": "#f8fafc",
        "muted": "#a1a1aa",
        "cover_end": "#111827",
    },
    "github": {
        "page": "#0d1117",
        "surface": "#0d1117",
        "panel": "#161b22",
        "panel_alt": "#111827",
        "panel_soft": "#1f2937",
        "code": "#0d1117",
        "line": "#30363d",
        "line_strong": "#484f58",
        "ink": "#c9d1d9",
        "heading": "#f0f6fc",
        "muted": "#8b949e",
        "cover_end": "#161b22",
    },
    "textbook": {
        "page": "#050505",
        "surface": "#050505",
        "panel": "#101010",
        "panel_alt": "#0a0a0a",
        "panel_soft": "#171717",
        "code": "#0a0a0a",
        "line": "#343434",
        "line_strong": "#5a5a5a",
        "ink": "#e5e5e5",
        "heading": "#ffffff",
        "muted": "#a3a3a3",
        "cover_end": "#101010",
    },
    "academic": {
        "page": "#111111",
        "surface": "#111111",
        "panel": "#1f1f1f",
        "panel_alt": "#171717",
        "panel_soft": "#262626",
        "code": "#0a0a0a",
        "line": "#404040",
        "line_strong": "#666666",
        "ink": "#e5e5e5",
        "heading": "#fafafa",
        "muted": "#a3a3a3",
        "cover_end": "#1f1f1f",
    },
}


def _dark_mode_css(appearance: Appearance) -> str:
    surface = DARK_STYLE_SURFACES.get(appearance.style, DARK_STYLE_SURFACES[DEFAULT_STYLE])
    return f"""
@page {{ background: {surface['page']}; }}
html {{
  background: {surface['page']} !important;
  color: {surface['ink']} !important;
}}
body.md2pdf-mode-dark {{
  --ink: {surface['ink']};
  --muted: {surface['muted']};
  --soft: {surface['panel']};
  --softer: {surface['panel_alt']};
  --line: {surface['line']};
  --line-strong: {surface['line_strong']};
  --accent-soft: color-mix(in srgb, var(--accent) 18%, {surface['code']});
  --quote: {surface['panel']};
  --code-bg: {surface['code']};
  --code-ink: {surface['ink']};
  --md2pdf-code-highlight-bg: color-mix(in srgb, var(--accent) 30%, {surface['code']});
  --md2pdf-code-highlight-border: color-mix(in srgb, var(--accent) 68%, {surface['line']});
  --md2pdf-details-bg: {surface['panel']};
  --md2pdf-details-ink: {surface['ink']};
  --md2pdf-mermaid-figure-bg: color-mix(in srgb, {surface['panel_alt']} 90%, var(--accent) 4%);
  --md2pdf-mermaid-figure-border: color-mix(in srgb, var(--accent) 28%, {surface['line']});
  --md2pdf-mermaid-figure-ink: {surface['ink']};
  --md2pdf-mermaid-bg: color-mix(in srgb, {surface['panel_alt']} 94%, {surface['page']} 6%);
  --md2pdf-mermaid-border: color-mix(in srgb, var(--accent) 24%, {surface['line']});
  --md2pdf-mermaid-node-bg: color-mix(in srgb, {surface['panel_soft']} 88%, var(--accent) 8%);
  --md2pdf-mermaid-node-ink: {surface['heading']};
  --md2pdf-mermaid-stroke: color-mix(in srgb, var(--accent) 76%, {surface['heading']} 24%);
  --md2pdf-mermaid-edge-ink: {surface['heading']};
  --md2pdf-mermaid-label-bg: color-mix(in srgb, {surface['panel_alt']} 84%, {surface['page']} 16%);
  --md2pdf-mermaid-label-border: color-mix(in srgb, var(--accent) 38%, {surface['line']});
  --md2pdf-mermaid-label-halo: {surface['panel_alt']};
  --md2pdf-mermaid-caption-ink: color-mix(in srgb, var(--accent) 68%, {surface['heading']} 32%);
  background: {surface['page']} !important;
  color: var(--ink) !important;
}}
body.md2pdf-mode-dark .md2pdf-document,
body.md2pdf-mode-dark .md2pdf-article {{
  background: {surface['surface']} !important;
  color: var(--ink) !important;
}}
body.md2pdf-mode-dark h1,
body.md2pdf-mode-dark h2,
body.md2pdf-mode-dark h3,
body.md2pdf-mode-dark h4,
body.md2pdf-mode-dark h5,
body.md2pdf-mode-dark h6,
body.md2pdf-mode-dark .md2pdf-cover h1,
body.md2pdf-mode-dark strong {{ color: {surface['heading']} !important; }}
body.md2pdf-mode-dark p,
body.md2pdf-mode-dark li,
body.md2pdf-mode-dark td {{ color: var(--ink) !important; }}
body.md2pdf-mode-dark table {{ background: {surface['panel_alt']} !important; color: var(--ink) !important; }}
body.md2pdf-mode-dark th {{ background: {surface['panel']} !important; color: {surface['heading']} !important; }}
body.md2pdf-mode-dark td,
body.md2pdf-mode-dark th {{ border-bottom-color: var(--line) !important; }}
body.md2pdf-mode-dark tbody tr:nth-child(even) td {{ background: {surface['panel']} !important; }}
body.md2pdf-mode-dark blockquote,
body.md2pdf-mode-dark .callout,
body.md2pdf-mode-dark .md2pdf-details {{
  background: {surface['panel']} !important;
  border-color: var(--line) !important;
  color: var(--ink) !important;
}}
body.md2pdf-mode-dark .mermaid-diagram {{
  background: var(--md2pdf-mermaid-figure-bg) !important;
  border-color: var(--md2pdf-mermaid-figure-border) !important;
  color: var(--md2pdf-mermaid-figure-ink) !important;
}}
body.md2pdf-mode-dark .md2pdf-cover__summary,
body.md2pdf-mode-dark .md2pdf-cover__subtitle,
body.md2pdf-mode-dark .md2pdf-cover__detail span,
body.md2pdf-mode-dark em,
body.md2pdf-mode-dark small,
body.md2pdf-mode-dark .footnotes,
body.md2pdf-mode-dark .footnote-backref {{ color: var(--muted) !important; }}
body.md2pdf-mode-dark :not(pre) > code {{
  background: {surface['panel']} !important;
  border-color: var(--line) !important;
  color: {surface['heading']} !important;
}}
body.md2pdf-mode-dark .code-block,
body.md2pdf-mode-dark .codehilite,
body.md2pdf-mode-dark .highlight,
body.md2pdf-mode-dark pre {{
  background: {surface['code']} !important;
  color: {surface['heading']} !important;
  border-color: var(--line) !important;
}}
body.md2pdf-mode-dark .code-block figcaption {{
  background: {surface['panel']} !important;
  color: {surface['heading']} !important;
  border-bottom-color: var(--line) !important;
}}
body.md2pdf-mode-dark .md2pdf-toc,
body.md2pdf-mode-dark .md2pdf-toc h2 {{ color: {surface['heading']} !important; }}
body.md2pdf-mode-dark .md2pdf-toc a {{
  background: transparent !important;
  color: var(--accent) !important;
}}
body.md2pdf-mode-dark .md2pdf-toc li > ol {{ border-inline-start-color: var(--line) !important; }}
body.md2pdf-mode-dark .md2pdf-toc .toc-number {{ color: {surface['ink']} !important; }}
body.md2pdf-mode-dark .table-wrap,
body.md2pdf-mode-dark .code-block {{ box-shadow: none !important; }}
body.md2pdf-mode-dark .md2pdf-cover-full-bleed .md2pdf-document,
body.md2pdf-mode-dark .md2pdf-cover-full-bleed .md2pdf-article {{ background: {surface['page']} !important; }}
body.md2pdf-mode-dark .md2pdf-cover,
body.md2pdf-mode-dark.md2pdf-cover-full-bleed .md2pdf-cover {{
  background:
    radial-gradient(circle at 5% 5%, color-mix(in srgb, var(--accent) 24%, transparent), transparent 28%),
    radial-gradient(circle at 92% 88%, color-mix(in srgb, var(--accent-2) 18%, transparent), transparent 31%),
    radial-gradient(circle at 72% 20%, color-mix(in srgb, var(--accent) 10%, transparent), transparent 30%),
    linear-gradient(180deg, {surface['page']} 0%, {surface['cover_end']} 100%) !important;
  color: var(--ink) !important;
  border-bottom-color: var(--line) !important;
}}
body.md2pdf-mode-dark .md2pdf-cover__decor--one {{ border-color: color-mix(in srgb, var(--accent) 35%, transparent) !important; }}
body.md2pdf-mode-dark .md2pdf-cover__decor--two {{ background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 18%, transparent), color-mix(in srgb, var(--accent-2) 15%, transparent)) !important; }}
body.md2pdf-mode-dark .md2pdf-cover__brand {{
  background: color-mix(in srgb, {surface['panel']} 82%, transparent) !important;
  border-color: var(--line) !important;
  color: var(--ink) !important;
}}
body.md2pdf-mode-dark .md2pdf-cover__mark {{ background: linear-gradient(135deg, var(--accent), var(--accent-2)) !important; }}
body.md2pdf-mode-dark .md2pdf-cover__brand-copy strong {{ color: {surface['heading']} !important; }}
body.md2pdf-mode-dark .md2pdf-cover__brand-copy em {{ color: var(--muted) !important; }}
body.md2pdf-mode-dark .md2pdf-cover__release {{
  background: color-mix(in srgb, var(--accent) 18%, {surface['panel']}) !important;
  border-color: color-mix(in srgb, var(--accent) 35%, {surface['line']}) !important;
  color: {surface['heading']} !important;
}}
body.md2pdf-mode-dark .md2pdf-cover__eyebrow {{
  color: var(--accent) !important;
  background: transparent !important;
  border-color: transparent !important;
  box-shadow: none !important;
  padding: 0 !important;
  filter: none !important;
  text-shadow: none !important;
}}
body.md2pdf-mode-dark .md2pdf-cover__eyebrow::before {{
  background: var(--accent) !important;
  box-shadow: none !important;
}}
body.md2pdf-mode-dark .md2pdf-cover__summary {{ border-top-color: var(--line) !important; }}
body.md2pdf-mode-dark .md2pdf-cover__detail {{
  background: color-mix(in srgb, {surface['panel']} 82%, transparent) !important;
  border-color: var(--line) !important;
}}
body.md2pdf-mode-dark .md2pdf-cover__detail strong {{ color: {surface['heading']} !important; }}
body.md2pdf-mode-dark .md2pdf-watermark {{ mix-blend-mode: screen; }}
body.md2pdf-mode-dark .md2pdf-watermark--text {{ color: {surface['heading']}; }}
body.md2pdf-mode-dark .md2pdf-watermark--image img {{ filter: invert(1) grayscale(1); }}
"""


def _modern_emerald_guide_css(appearance: Appearance) -> str:
    if appearance.style != "modern" or appearance.palette != "emerald" or appearance.mode != "light":
        return ""
    return """
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .md2pdf-cover {
  background:
    radial-gradient(circle at 4% 5%, rgba(16, 185, 129, 0.22), transparent 28%),
    radial-gradient(circle at 94% 88%, rgba(13, 148, 136, 0.16), transparent 31%),
    radial-gradient(circle at 72% 20%, rgba(52, 211, 153, 0.13), transparent 30%),
    linear-gradient(180deg, #ffffff 0%, #ecfdf5 100%) !important;
}
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .md2pdf-cover__decor--one {
  border-color: rgba(16, 185, 129, 0.32) !important;
}
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .md2pdf-cover__decor--two {
  background: linear-gradient(135deg, rgba(16, 185, 129, 0.16), rgba(13, 148, 136, 0.14)) !important;
}
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .md2pdf-cover__brand {
  border-color: color-mix(in srgb, #10b981 22%, rgba(15, 23, 42, 0.12)) !important;
  background: color-mix(in srgb, #ffffff 92%, #ecfdf5 8%) !important;
  box-shadow: none !important;
}
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .md2pdf-cover__brand--product .md2pdf-cover__mark {
  background: linear-gradient(135deg, #10b981, #0d9488) !important;
}
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .md2pdf-cover__brand--product .md2pdf-cover__brand-copy em {
  color: #047857 !important;
}
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .md2pdf-cover__brand-copy em,
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .md2pdf-cover__summary {
  color: #475569 !important;
}
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) h2::before,
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) h3::before {
  background: linear-gradient(135deg, #10b981, #0d9488) !important;
}
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .callout,
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .callout-note,
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .callout-tip,
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .callout-success,
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .callout-important,
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .callout-warning,
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .callout-caution,
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .callout-danger,
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .callout-failure,
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .callout-bug,
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .callout-question,
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .callout-example,
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .callout-quote,
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .callout-abstract {
  background: linear-gradient(180deg, #ecfdf5 0%, #ffffff 100%) !important;
  border-color: rgba(16, 185, 129, 0.28) !important;
  border-inline-start-color: #10b981 !important;
  color: #0f172a !important;
}
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .callout-title {
  color: #065f46 !important;
}
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) table thead th {
  background: color-mix(in srgb, #ecfdf5 72%, #f8fafc) !important;
}
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .md2pdf-toc,
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .table-wrap table,
body.md2pdf-style-modern.md2pdf-palette-emerald:not(.md2pdf-mode-dark) .code-block {
  border-color: color-mix(in srgb, #10b981 20%, var(--line)) !important;
}
"""


def palette_css(palette_name: str, mode_name: str, style_name: str | None = None) -> str:
    appearance = resolve_appearance(palette=palette_name, mode=mode_name, style=style_name)
    colors = DARK_PALETTES[appearance.palette] if appearance.mode == "dark" else PALETTES[appearance.palette]
    dark_css = _dark_mode_css(appearance) if appearance.mode == "dark" else ""
    return f"""
:root {{
  --accent: {colors['accent']};
  --accent-2: {colors['accent_2']};
  --accent-soft: {colors['accent_soft']};
  --accent-line: {colors['accent_line']};
  --quote: {colors['quote']};
  --blue: {colors['accent']};
  --blue-soft: {colors['accent_soft']};
  --blue-line: {colors['accent_line']};
  --md2pdf-mermaid-stroke: {colors['accent']};
  --md2pdf-mermaid-edge-ink: {colors['accent']};
}}
body.md2pdf-palette-{appearance.palette} a {{ color: var(--accent); }}
body.md2pdf-palette-{appearance.palette} li::marker {{ color: var(--accent); }}
body.md2pdf-palette-{appearance.palette} mark {{
  background: color-mix(in srgb, var(--accent-soft) 74%, transparent);
  color: inherit;
}}
body.md2pdf-palette-{appearance.palette} .md2pdf-cover__eyebrow,
body.md2pdf-palette-{appearance.palette} .md2pdf-summary,
body.md2pdf-palette-{appearance.palette} .footnote-marker {{ color: var(--accent); }}
body.md2pdf-palette-{appearance.palette} .md2pdf-cover__eyebrow {{
  background: transparent !important;
  border-color: transparent !important;
  box-shadow: none !important;
  padding: 0 !important;
  filter: none !important;
  text-shadow: none !important;
}}
body.md2pdf-palette-{appearance.palette} .md2pdf-cover__eyebrow::before {{ background: var(--accent) !important; }}
body.md2pdf-palette-{appearance.palette}:not(.md2pdf-mode-dark) .md2pdf-cover-full-bleed .md2pdf-cover,
body.md2pdf-palette-{appearance.palette}:not(.md2pdf-mode-dark) .md2pdf-cover {{
  background:
    radial-gradient(circle at 4% 5%, color-mix(in srgb, var(--accent) 14%, transparent), transparent 28%),
    radial-gradient(circle at 94% 88%, color-mix(in srgb, var(--accent-2) 10%, transparent), transparent 31%),
    radial-gradient(circle at 72% 20%, color-mix(in srgb, var(--accent) 7%, transparent), transparent 30%),
    linear-gradient(180deg, #ffffff 0%, color-mix(in srgb, var(--accent-soft) 34%, #f8fafc) 100%);
}}
body.md2pdf-palette-{appearance.palette}:not(.md2pdf-mode-dark) .md2pdf-cover__decor--one {{ border-color: color-mix(in srgb, var(--accent) 26%, transparent); }}
body.md2pdf-palette-{appearance.palette}:not(.md2pdf-mode-dark) .md2pdf-cover__decor--two {{ background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 13%, transparent), color-mix(in srgb, var(--accent-2) 10%, transparent)); }}
body.md2pdf-palette-{appearance.palette}:not(.md2pdf-mode-dark) .md2pdf-cover__mark {{ background: linear-gradient(135deg, #0f172a, var(--accent)); }}

body.md2pdf-style-academic.md2pdf-palette-{appearance.palette} blockquote {{
  border-inline-start-color: var(--accent) !important;
  background: var(--quote) !important;
}}
body.md2pdf-style-academic.md2pdf-palette-{appearance.palette} .callout {{
  background: var(--accent-soft) !important;
  border-color: color-mix(in srgb, var(--accent-line) 50%, var(--line)) !important;
}}
body.md2pdf-style-academic.md2pdf-palette-{appearance.palette} .callout-title {{ border-bottom-color: var(--accent-line) !important; }}
body.md2pdf-style-academic.md2pdf-palette-{appearance.palette} .md2pdf-toc .toc-number,
body.md2pdf-style-academic.md2pdf-palette-{appearance.palette} .code-block figcaption {{ color: var(--accent) !important; }}
body.md2pdf-style-academic.md2pdf-palette-{appearance.palette}:not(.md2pdf-mode-dark) .md2pdf-cover {{
  background:
    radial-gradient(circle at 5% 4%, color-mix(in srgb, var(--accent) 11%, transparent), transparent 27%),
    radial-gradient(circle at 92% 86%, color-mix(in srgb, var(--accent-2) 9%, transparent), transparent 31%),
    linear-gradient(180deg, #ffffff 0%, color-mix(in srgb, var(--accent-soft) 20%, #f8fafc) 100%) !important;
}}
body.md2pdf-style-academic.md2pdf-palette-{appearance.palette}:not(.md2pdf-mode-dark) .md2pdf-cover__mark {{
  background: linear-gradient(135deg, #292524, var(--accent)) !important;
}}
body.md2pdf-style-academic.md2pdf-palette-{appearance.palette}:not(.md2pdf-mode-dark) .md2pdf-cover__decor--one {{
  border-color: color-mix(in srgb, var(--accent) 24%, transparent) !important;
}}
body.md2pdf-style-academic.md2pdf-palette-{appearance.palette}:not(.md2pdf-mode-dark) .md2pdf-cover__decor--two {{
  background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 10%, transparent), color-mix(in srgb, var(--accent-2) 9%, transparent)) !important;
}}
{_modern_emerald_guide_css(appearance)}
{dark_css}
"""

from pathlib import Path

from mardas_folio.appearance import PALETTES_ORDER
from mardas_folio.markdown import render_markdown
from mardas_folio.renderer import PdfOptions, build_html


STYLE_DIR = Path(__file__).resolve().parents[1] / "src" / "mardas_folio" / "assets"


def test_toc_can_split_across_pages_without_moving_whole_sections():
    for style in STYLE_DIR.glob("style-*.css"):
        css = style.read_text(encoding="utf-8")
        assert ".md2pdf-toc" in css
        assert "page-break-inside: auto" in css
        assert "break-inside: auto" in css
        assert "page-break-inside: avoid" in css


def test_dark_style_overrides_details_and_mermaid_for_contrast():
    from mardas_folio.appearance import palette_css

    css = palette_css("neutral", "dark", "textbook")
    assert "--md2pdf-details-bg: #101010" in css
    assert "--md2pdf-details-ink: #e5e5e5" in css
    assert "--md2pdf-code-highlight-bg: color-mix(in srgb, var(--accent) 30%, #0a0a0a)" in css
    assert "--md2pdf-code-highlight-border: color-mix(in srgb, var(--accent) 68%, #343434)" in css
    assert "--md2pdf-mermaid-figure-bg: color-mix(in srgb, #0a0a0a 90%, var(--accent) 4%)" in css
    assert "--md2pdf-mermaid-figure-border: color-mix(in srgb, var(--accent) 28%, #343434)" in css
    assert "--md2pdf-mermaid-bg: color-mix(in srgb, #0a0a0a 94%, #050505 6%)" in css
    assert "--md2pdf-mermaid-node-bg: color-mix(in srgb, #171717 88%, var(--accent) 8%)" in css
    assert "--md2pdf-mermaid-node-ink: #ffffff" in css
    assert "--md2pdf-mermaid-stroke: color-mix(in srgb, var(--accent) 76%, #ffffff 24%)" in css
    assert "--md2pdf-mermaid-edge-ink: #ffffff" in css
    assert "--md2pdf-mermaid-label-bg: color-mix(in srgb, #0a0a0a 84%, #050505 16%)" in css
    assert "--md2pdf-mermaid-label-border: color-mix(in srgb, var(--accent) 38%, #343434)" in css
    assert "--md2pdf-mermaid-label-halo: #0a0a0a" in css
    assert "background: var(--md2pdf-mermaid-figure-bg) !important;" in css
    assert "border-color: var(--md2pdf-mermaid-figure-border) !important;" in css


def test_all_dark_appearance_styles_emit_complete_mermaid_contrast_contract():
    from mardas_folio.appearance import PALETTES_ORDER, STYLES, palette_css

    required_vars = [
        "--md2pdf-mermaid-figure-bg:",
        "--md2pdf-mermaid-figure-border:",
        "--md2pdf-mermaid-figure-ink:",
        "--md2pdf-mermaid-bg:",
        "--md2pdf-mermaid-border:",
        "--md2pdf-mermaid-node-bg:",
        "--md2pdf-mermaid-node-ink:",
        "--md2pdf-mermaid-stroke:",
        "--md2pdf-mermaid-edge-ink:",
        "--md2pdf-mermaid-label-bg:",
        "--md2pdf-mermaid-label-border:",
        "--md2pdf-mermaid-label-halo:",
        "--md2pdf-mermaid-caption-ink:",
        "--md2pdf-code-highlight-bg:",
        "--md2pdf-code-highlight-border:",
    ]
    for style in STYLES:
        for palette in PALETTES_ORDER:
            css = palette_css(palette, "dark", style)
            for var in required_vars:
                assert var in css
            assert "body.md2pdf-mode-dark .mermaid-diagram" in css
            assert "background: var(--md2pdf-mermaid-figure-bg) !important;" in css
            assert "border-color: var(--md2pdf-mermaid-figure-border) !important;" in css


def test_academic_style_keeps_accent_colors_palette_driven():
    css = (STYLE_DIR / "style-academic.css").read_text(encoding="utf-8")
    forbidden_legacy_colors = ["#7c2d12", "#c2410c", "#fff7ed", "#fed7aa", "#fffaf5", "124, 45, 18"]
    for color in forbidden_legacy_colors:
        assert color not in css
    assert "--blue: var(--accent" in css
    assert "--md2pdf-mermaid-stroke: var(--accent" in css
    assert "--md2pdf-mermaid-edge-ink: var(--accent" in css


def test_academic_palette_overrides_are_emitted_for_every_palette(tmp_path):
    md = "---\ntitle: Palette QA\ncover_label: Label\n---\n\n# Heading\n\n> [!NOTE]\n> Callout\n"
    input_path = tmp_path / "palette.md"
    input_path.write_text(md, encoding="utf-8")
    for palette in PALETTES_ORDER:
        html = build_html(
            render_markdown(md),
            PdfOptions(
                input_path=input_path,
                output_path=tmp_path / f"{palette}.pdf",
                style="academic",
                palette=palette,
                mode="light",
            ),
        )
        assert f"body.md2pdf-style-academic.md2pdf-palette-{palette} blockquote" in html
        assert "border-inline-start-color: var(--accent)" in html
        assert "background: var(--accent-soft)" in html


def test_all_appearance_combinations_emit_clean_palette_css(tmp_path):
    from mardas_folio.appearance import MODES, PALETTES_ORDER, STYLES
    from mardas_folio.markdown import render_markdown
    from mardas_folio.renderer import PdfOptions, build_html

    md = "---\ntitle: Matrix\ncover_label: Complete Guide\n---\n\n# Heading\n\n`code` and <mark>mark</mark>.\n"
    result = render_markdown(md)
    input_path = tmp_path / "matrix.md"
    input_path.write_text(md, encoding="utf-8")
    for style in STYLES:
        for palette in PALETTES_ORDER:
            for mode in MODES:
                html = build_html(
                    result,
                    PdfOptions(
                        input_path=input_path,
                        output_path=tmp_path / f"{style}-{palette}-{mode}.pdf",
                        style=style,
                        palette=palette,
                        mode=mode,
                    ),
                )
                assert f"md2pdf-style-{style}" in html
                assert f"md2pdf-palette-{palette}" in html
                assert f"md2pdf-mode-{mode}" in html
                assert "background: transparent !important;" in html
                assert "--md2pdf-code-highlight-bg: color-mix(in srgb, var(--accent" in html
                assert "background-color: var(--md2pdf-code-highlight-bg) !important;" in html




def test_dark_code_highlight_overrides_root_light_code_surface(tmp_path):
    from mardas_folio.markdown import render_markdown
    from mardas_folio.renderer import PdfOptions, build_html

    md = (
        '```python title="renderer.py" {2} linenos\n'
        'def convert(markdown: str) -> bytes:\n'
        '    html = render_markdown(markdown)\n'
        '    return html\n'
        '```\n'
    )
    input_path = tmp_path / "dark-highlight.md"
    input_path.write_text(md, encoding="utf-8")

    html = build_html(
        render_markdown(md),
        PdfOptions(
            input_path=input_path,
            output_path=tmp_path / "dark-highlight.pdf",
            style="textbook",
            palette="slate",
            mode="dark",
        ),
    )

    assert "md2pdf-style-textbook" in html
    assert "md2pdf-mode-dark" in html
    assert "--code-bg: #0a0a0a" in html
    assert "--md2pdf-code-highlight-bg: color-mix(in srgb, var(--accent) 30%, #0a0a0a)" in html
    assert "--md2pdf-code-highlight-bg: color-mix(in srgb, var(--accent, #2563eb) 24%, var(--code-bg, #0f172a))" in html
    assert "background-color: var(--md2pdf-code-highlight-bg) !important;" in html


def test_code_highlight_uses_code_surface_not_pale_callout_color(tmp_path):
    md = '```python title="renderer.py" {2} linenos\ndef convert(markdown: str) -> bytes:\n    html = render_markdown(markdown)\n    return html\n```\n'
    input_path = tmp_path / "highlight.md"
    input_path.write_text(md, encoding="utf-8")
    html = build_html(
        render_markdown(md),
        PdfOptions(
            input_path=input_path,
            output_path=tmp_path / "highlight.pdf",
            style="modern",
            palette="emerald",
            mode="light",
        ),
    )

    assert "code-block--highlighted" in html
    assert "--md2pdf-code-highlight-bg: color-mix(in srgb, var(--accent" in html
    assert "var(--code-bg" in html
    assert "background-color: var(--md2pdf-code-highlight-bg) !important;" in html
    assert "box-shadow: inset 3px 0 0 var(--md2pdf-code-highlight-border);" in html
    assert "background-color: color-mix(in srgb, var(--accent-soft" not in html


def test_dark_mode_palettes_use_screen_safe_accent_tokens():
    from mardas_folio.appearance import DARK_PALETTES, DARK_STYLE_SURFACES, palette_css

    def relative_luminance(hex_color: str) -> float:
        channels = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    def contrast_ratio(first: str, second: str) -> float:
        lighter, darker = sorted([relative_luminance(first), relative_luminance(second)], reverse=True)
        return (lighter + 0.05) / (darker + 0.05)

    slate_css = palette_css("slate", "dark", "textbook")
    neutral_css = palette_css("neutral", "dark", "textbook")
    emerald_css = palette_css("emerald", "dark", "modern")

    assert "--accent: #cbd5e1" in slate_css
    assert "--accent: #d4d4d4" in neutral_css
    assert "--accent: #34d399" in emerald_css
    assert "body.md2pdf-mode-dark .md2pdf-toc a" in slate_css
    for palette in DARK_PALETTES.values():
        for surface in DARK_STYLE_SURFACES.values():
            assert contrast_ratio(palette["accent"], surface["page"]) >= 4.5
            assert contrast_ratio(palette["accent"], surface["panel"]) >= 4.5


def test_rtl_script_code_blocks_use_persian_font_fallback(tmp_path):
    from mardas_folio.markdown import render_markdown
    from mardas_folio.renderer import PdfOptions, build_html

    md = "---\nlang: fa\ndir: rtl\n---\n\n```yaml\ntitle: \"گزارش فنی من\"\nversion: \"1.0.0\"\n```\n"
    input_path = tmp_path / "rtl-code.md"
    input_path.write_text(md, encoding="utf-8")

    html = build_html(render_markdown(md), PdfOptions(input_path=input_path, output_path=tmp_path / "out.pdf"))

    assert "code-block--rtl-script" in html
    assert "code-block--mixed-script" in html
    assert "font-family: var(--font-fa), var(--font-code);" in html

def test_modern_emerald_palette_has_strong_guide_identity_contract():
    from mardas_folio.appearance import palette_css

    css = palette_css("emerald", "light", "modern")

    assert "md2pdf-style-modern.md2pdf-palette-emerald" in css
    assert "#10b981" in css
    assert "callout-warning" in css
    assert "md2pdf-cover__brand" in css
    assert "box-shadow: none !important;" in css
    assert "0 8px 22px" not in css
    assert "md2pdf-cover__brand--product .md2pdf-cover__mark" in css
    assert "linear-gradient(135deg, #10b981, #0d9488)" in css
    assert "#047857" in css
    assert "md2pdf-cover__brand--custom" not in css
    assert "linear-gradient(180deg, #ecfdf5 0%, #ffffff 100%)" in css

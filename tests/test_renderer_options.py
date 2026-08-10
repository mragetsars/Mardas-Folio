from mardas_md2pdf.renderer import _css_page_size, _playwright_page_size_kwargs, validate_page_size


def test_css_page_size_accepts_named_orientation_and_dimensions():
    assert _css_page_size("A4 landscape") == "297mm 210mm"
    assert _css_page_size("B0") == "1000mm 1414mm"
    assert _css_page_size("210mm 297mm") == "210mm 297mm"
    assert _css_page_size("bad; value") == "210mm 297mm"
    assert _css_page_size("not-a-size") == "210mm 297mm"


def test_page_size_validation_rejects_unknown_named_sizes():
    import pytest

    assert validate_page_size("Letter") == "Letter"
    assert validate_page_size("A4 landscape") == "A4 landscape"
    assert validate_page_size("148mm 210mm") == "148mm 210mm"
    for invalid in ("0mm 0mm", "0.1mm 0.1mm", "999999mm 999999mm"):
        with pytest.raises(ValueError, match="page dimensions"):
            validate_page_size(invalid)
    with pytest.raises(ValueError, match="page size"):
        validate_page_size("not-a-size")


def test_playwright_page_size_uses_explicit_dimensions_for_all_formats():
    assert _playwright_page_size_kwargs("Letter") == {"width": "8.5in", "height": "11in"}
    assert _playwright_page_size_kwargs("B2") == {"width": "500mm", "height": "707mm"}
    assert _playwright_page_size_kwargs("210mm 297mm") == {"width": "210mm", "height": "297mm"}
    assert _playwright_page_size_kwargs("A4 landscape") == {"width": "297mm", "height": "210mm"}


def test_font_faces_warns_for_missing_font_directory(tmp_path):
    import pytest

    from mardas_md2pdf.renderer import _font_faces

    with pytest.warns(RuntimeWarning, match="Font directory not found"):
        assert _font_faces(tmp_path / "missing-fonts") == ""


def test_render_pdf_warns_when_mathjax_evaluation_fails(tmp_path):
    import pytest

    from mardas_md2pdf.renderer import PdfOptions, _render_pdf

    class FakePage:
        def __init__(self):
            self.evaluate_calls = 0
            self.pdf_kwargs = None

        def set_content(self, html_text, wait_until):
            self.html_text = html_text
            self.wait_until = wait_until

        def evaluate(self, expression):
            self.evaluate_calls += 1
            if self.evaluate_calls == 2:
                raise RuntimeError("boom")
            return None

        def emulate_media(self, media):
            self.media = media

        def pdf(self, **kwargs):
            self.pdf_kwargs = kwargs

    page = FakePage()
    options = PdfOptions(input_path=tmp_path / "in.md", output_path=tmp_path / "out.pdf")
    with pytest.warns(RuntimeWarning, match="MathJax rendering failed"):
        _render_pdf(
            page,
            "<html></html>",
            options,
            tmp_path / "out.pdf",
            display_footer=False,
            footer_context="T",
        )
    assert page.pdf_kwargs["width"] == "210mm"
    assert page.pdf_kwargs["height"] == "297mm"
    assert "format" not in page.pdf_kwargs


def test_manual_pagebreak_css_breaks_after_marker_not_before(tmp_path):
    from mardas_md2pdf.markdown import render_markdown
    from mardas_md2pdf.renderer import PdfOptions, build_html

    md = "A\n\n<div class=\"md2pdf-page-break\"></div>\n\n# B\n"
    result = render_markdown(md)
    input_path = tmp_path / "pagebreak.md"
    input_path.write_text(md, encoding="utf-8")
    html = build_html(result, PdfOptions(input_path=input_path, output_path=tmp_path / "out.pdf"))

    marker_css = html.split(".md2pdf-page-break {", 1)[1].split("}", 1)[0]
    assert "break-after: page;" in marker_css
    assert "page-break-after: always;" in marker_css
    assert "break-before: auto;" in marker_css
    assert "page-break-before: auto;" in marker_css
    assert "break-before: page;" not in marker_css
    assert "page-break-before: always;" not in marker_css


def test_footer_template_isolates_mixed_title_in_ltr_footer_slot():
    from mardas_md2pdf.renderer import _footer_template

    footer = _footer_template("راهنمای Mardas Folio", "modern")

    assert 'dir="ltr"' in footer
    assert "direction:ltr" in footer
    assert "unicode-bidi:isolate" in footer
    assert "راهنمای Mardas Folio" in footer
    assert "text-align:left" in footer
    assert "position:absolute; left:50%; transform:translateX(-50%)" in footer


def test_print_css_hides_heading_permalink_markers(tmp_path):
    from mardas_md2pdf.markdown import render_markdown
    from mardas_md2pdf.renderer import PdfOptions, build_html

    md = "# Heading\n"
    input_path = tmp_path / "heading.md"
    input_path.write_text(md, encoding="utf-8")
    html = build_html(render_markdown(md), PdfOptions(input_path=input_path, output_path=tmp_path / "out.pdf"))

    assert 'class="heading-anchor"' in html
    assert "@media print" in html
    assert ".heading-anchor { display: none !important; }" in html


def test_callout_direction_follows_resolved_document_direction(tmp_path):
    from mardas_md2pdf.markdown import render_markdown
    from mardas_md2pdf.renderer import PdfOptions, build_html

    md = "---\nlang: en\ndir: ltr\n---\n\n> [!NOTE]\n> English callout text.\n"
    input_path = tmp_path / "callout.md"
    input_path.write_text(md, encoding="utf-8")
    html = build_html(
        render_markdown(md),
        PdfOptions(input_path=input_path, output_path=tmp_path / "out.pdf", style="textbook", mode="light"),
    )

    assert "md2pdf-dir-ltr" in html
    assert "body.md2pdf-dir-ltr .callout { direction: ltr; text-align: left; }" in html
    assert "body.md2pdf-dir-ltr .callout-title," in html
    assert "body.md2pdf-dir-ltr .callout p { text-align: left; }" in html


def test_mermaid_css_uses_appearance_color_variables(tmp_path):
    from mardas_md2pdf.markdown import render_markdown
    from mardas_md2pdf.renderer import PdfOptions, build_html

    md = "```mermaid\nflowchart LR\nA[A] --> B[B]\n```\n"
    input_path = tmp_path / "diagram.md"
    input_path.write_text(md, encoding="utf-8")
    html = build_html(render_markdown(md), PdfOptions(input_path=input_path, output_path=tmp_path / "out.pdf"))

    assert "--md2pdf-mermaid-stroke" in html
    assert "var(--accent, var(--blue" in html
    assert "var(--md2pdf-mermaid-label-halo" in html
    assert "var(--md2pdf-mermaid-figure-bg" in html
    assert "var(--md2pdf-mermaid-figure-border" in html
    assert "var(--md2pdf-mermaid-node-ink" in html
    assert "var(--md2pdf-mermaid-label-bg" in html


def test_mermaid_css_caps_diagram_height_for_print_layout(tmp_path):
    from mardas_md2pdf.markdown import render_markdown
    from mardas_md2pdf.renderer import PdfOptions, build_html

    md = "```mermaid\nflowchart TD\nA[A] --> B[B]\nB --> C[C]\nC --> D[D]\n```\n"
    input_path = tmp_path / "diagram.md"
    input_path.write_text(md, encoding="utf-8")
    html = build_html(render_markdown(md), PdfOptions(input_path=input_path, output_path=tmp_path / "out.pdf"))

    assert "--md2pdf-mermaid-max-height" in html
    assert "--md2pdf-mermaid-tall-max-height" in html
    assert ".mermaid-diagram--tall .md2pdf-mermaid-svg" in html
    assert ".mermaid-diagram--wide .md2pdf-mermaid-svg" in html


def test_chromium_sandbox_off_adds_no_sandbox(tmp_path):
    from mardas_md2pdf.renderer import PdfOptions, _chromium_launch_args

    options = PdfOptions(
        input_path=tmp_path / "input.md",
        output_path=tmp_path / "output.pdf",
        chromium_sandbox="off",
    )

    assert "--no-sandbox" in _chromium_launch_args(options)


def test_chromium_sandbox_on_omits_no_sandbox(tmp_path):
    from mardas_md2pdf.renderer import PdfOptions, _chromium_launch_args

    options = PdfOptions(
        input_path=tmp_path / "input.md",
        output_path=tmp_path / "output.pdf",
        chromium_sandbox="on",
    )

    assert "--no-sandbox" not in _chromium_launch_args(options)


def test_cli_exposes_chromium_sandbox_modes():
    from mardas_md2pdf.cli import build_parser

    parser = build_parser()
    sandbox_action = next(action for action in parser._actions if "--chromium-sandbox" in action.option_strings)

    assert sandbox_action.choices == ["auto", "on", "off"]


def test_outline_source_entries_follow_markdown_headings():
    from mardas_md2pdf.markdown import render_markdown
    from mardas_md2pdf.renderer import _outline_source_entries

    result = render_markdown("# Intro\n\n## Details\n\n### Deep dive\n")

    assert _outline_source_entries(result) == [
        (1, "Intro", "intro"),
        (2, "Details", "details"),
        (3, "Deep dive", "deep-dive"),
    ]


def test_locate_outline_pages_uses_start_page_and_monotonic_lookup():
    from mardas_md2pdf.renderer import _locate_outline_pages

    page_texts = [
        "cover",
        "introoverview",
        "detailsmoretext",
        "deepdiveappendix",
    ]
    entries = [
        (1, "Intro", "intro"),
        (2, "Details", "details"),
        (3, "Deep dive", "deep-dive"),
        (2, "Missing", "missing"),
    ]

    assert _locate_outline_pages(page_texts, entries, start_page=1) == [
        (1, "Intro", 1, None),
        (2, "Details", 2, None),
        (3, "Deep dive", 3, None),
        (2, "Missing", 3, None),
    ]


def test_add_pdf_outline_writes_nested_bookmarks(tmp_path):
    from pypdf import PdfReader, PdfWriter

    from mardas_md2pdf.renderer import _add_pdf_outline

    output_path = tmp_path / "outlined.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    _add_pdf_outline(writer, [(1, "Intro", 0, None), (2, "Details", 1, None)])
    with output_path.open("wb") as fh:
        writer.write(fh)
    writer.close()

    reader = PdfReader(str(output_path))
    outline = reader.outline

    assert outline[0].title == "Intro"
    assert outline[1][0].title == "Details"


def test_cli_rejects_invalid_page_size(tmp_path):
    import pytest

    from mardas_md2pdf.cli import main

    input_path = tmp_path / "doc.md"
    input_path.write_text("# Title\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        main([str(input_path), "--page-size", "not-a-size"])



def test_cli_exposes_remote_asset_opt_in():
    from mardas_md2pdf.cli import build_parser

    parser = build_parser()
    action = next(action for action in parser._actions if "--allow-remote-assets" in action.option_strings)

    assert action.default is False



def test_blocked_image_placeholder_css_is_print_friendly(tmp_path):
    from mardas_md2pdf.markdown import render_markdown_file
    from mardas_md2pdf.renderer import PdfOptions, build_html

    input_path = tmp_path / "missing.md"
    input_path.write_text("![Missing](missing.png)\n", encoding="utf-8")
    result = render_markdown_file(input_path)
    html = build_html(result, PdfOptions(input_path=input_path, output_path=tmp_path / "out.pdf"))

    assert ".md2pdf-image-placeholder" in html
    assert "overflow-wrap: anywhere" in html
    assert "page-break-inside: avoid" in html



def test_wide_table_css_fits_columns_for_print(tmp_path):
    from mardas_md2pdf.markdown import render_markdown
    from mardas_md2pdf.renderer import PdfOptions, build_html

    columns = "|" + "|".join(f"C{i}" for i in range(1, 13)) + "|"
    divider = "|" + "|".join("---" for _ in range(12)) + "|"
    values = "|" + "|".join(f"Value {i}" for i in range(1, 13)) + "|"
    md = "\n".join([columns, divider, values])
    input_path = tmp_path / "wide.md"
    input_path.write_text(md, encoding="utf-8")
    html = build_html(render_markdown(md), PdfOptions(input_path=input_path, output_path=tmp_path / "out.pdf"))

    assert ".table-wrap--wide table" in html
    assert "table-layout: fixed" in html
    assert ".table-wrap--very-wide table" in html
    assert "overflow-wrap: anywhere" in html



def test_pdf_date_honors_source_date_epoch(monkeypatch):
    from mardas_md2pdf.renderer import _pdf_date

    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1735689600")

    assert _pdf_date() == "D:20250101000000+00'00'"



def test_watermark_css_overlays_content_with_mode_aware_blending(tmp_path):
    from mardas_md2pdf.markdown import render_markdown
    from mardas_md2pdf.renderer import PdfOptions, build_html

    input_path = tmp_path / "watermark.md"
    input_path.write_text("# Watermark\n", encoding="utf-8")
    html = build_html(
        render_markdown("# Watermark\n"),
        PdfOptions(input_path=input_path, output_path=tmp_path / "out.pdf", watermark_text="DRAFT", style="textbook", mode="dark"),
    )

    assert ".md2pdf-watermark" in html
    assert "z-index: 2 !important" in html
    assert "mix-blend-mode: multiply" in html
    assert "body.md2pdf-style-textbook.md2pdf-mode-dark .md2pdf-watermark" in html
    assert "mix-blend-mode: screen" in html


def test_build_html_uses_resolved_appearance_classes_and_palette_css(tmp_path):
    from mardas_md2pdf.markdown import render_markdown
    from mardas_md2pdf.renderer import PdfOptions, build_html

    input_path = tmp_path / "appearance.md"
    input_path.write_text("# Appearance\n", encoding="utf-8")
    html = build_html(
        render_markdown("# Appearance\n"),
        PdfOptions(
            input_path=input_path,
            output_path=tmp_path / "out.pdf",
            style="academic",
            palette="emerald",
            mode="dark",
        ),
    )

    assert "md2pdf-style-academic" in html
    assert "md2pdf-palette-emerald" in html
    assert "md2pdf-mode-dark" in html
    assert "--accent: #34d399" in html
    assert "--accent-line: #10b981" in html


def test_front_matter_appearance_is_used_when_cli_keeps_defaults(tmp_path):
    from mardas_md2pdf.markdown import render_markdown
    from mardas_md2pdf.renderer import PdfOptions, build_html

    md = "---\nappearance:\n  style: textbook\n  palette: rose\n  mode: dark\n---\n\n# Title\n"
    input_path = tmp_path / "frontmatter.md"
    input_path.write_text(md, encoding="utf-8")
    html = build_html(render_markdown(md), PdfOptions(input_path=input_path, output_path=tmp_path / "out.pdf"))

    assert "md2pdf-style-textbook" in html
    assert "md2pdf-palette-rose" in html
    assert "md2pdf-mode-dark" in html


def test_cli_lists_appearance_choices_without_input(capsys):
    from mardas_md2pdf.cli import main

    assert main(["--list-styles"]) == 0
    styles_output = capsys.readouterr().out
    assert "Styles" in styles_output
    assert "modern" in styles_output
    assert "textbook" in styles_output

    assert main(["--list-palettes"]) == 0
    palettes_output = capsys.readouterr().out
    assert "Palettes" in palettes_output
    assert "blue" in palettes_output
    assert "emerald" in palettes_output

    assert main(["--list-modes"]) == 0
    modes_output = capsys.readouterr().out
    assert "Modes" in modes_output
    assert "light" in modes_output
    assert "dark" in modes_output


def test_dark_appearance_css_uses_style_specific_surfaces():
    from mardas_md2pdf.appearance import palette_css

    modern = palette_css("blue", "dark", "modern")
    github = palette_css("blue", "dark", "github")
    textbook = palette_css("blue", "dark", "textbook")
    academic = palette_css("blue", "dark", "academic")

    assert "background: #0b1020 !important" in modern
    assert "background: #0d1117 !important" in github
    assert "background: #050505 !important" in textbook
    assert "background: #111111 !important" in academic
    assert modern != github != textbook != academic


def test_dark_appearance_css_overrides_full_bleed_cover_background():
    from mardas_md2pdf.appearance import palette_css

    css = palette_css("emerald", "dark", "textbook")

    assert "body.md2pdf-mode-dark.md2pdf-cover-full-bleed .md2pdf-cover" in css
    assert "linear-gradient(180deg, #050505 0%, #101010 100%) !important" in css
    assert "var(--accent)" in css


def test_light_appearance_css_tints_cover_with_palette():
    from mardas_md2pdf.appearance import palette_css

    css = palette_css("rose", "light", "modern")

    assert "body.md2pdf-palette-rose:not(.md2pdf-mode-dark) .md2pdf-cover" in css
    assert "color-mix(in srgb, var(--accent) 14%" in css
    assert "--accent: #e11d48" in css


def test_cover_eyebrow_is_not_rendered_as_badge_highlight(tmp_path):
    from mardas_md2pdf.markdown import render_markdown
    from mardas_md2pdf.renderer import PdfOptions, build_html

    md = """---
title: Guide
cover_label: Complete Guide
---

# Body
"""
    input_path = tmp_path / "cover.md"
    input_path.write_text(md, encoding="utf-8")

    light_html = build_html(
        render_markdown(md),
        PdfOptions(
            input_path=input_path,
            output_path=tmp_path / "out-light.pdf",
            style="github",
            palette="amber",
            mode="light",
        ),
    )
    dark_html = build_html(
        render_markdown(md),
        PdfOptions(
            input_path=input_path,
            output_path=tmp_path / "out-dark.pdf",
            style="github",
            palette="amber",
            mode="dark",
        ),
    )

    assert "Complete Guide" in light_html
    assert ".md2pdf-cover__eyebrow {" in light_html
    assert "background: transparent !important;" in light_html
    assert "padding: 0 !important;" in light_html
    assert "background: #ddf4ff;" not in light_html
    assert ".md2pdf-cover__eyebrow { color: var(--accent, #0969da); background: transparent; }" in light_html

    assert "Complete Guide" in dark_html
    assert "body.md2pdf-mode-dark .md2pdf-cover__eyebrow {" in dark_html
    assert "background: transparent !important;" in dark_html
    assert "border-color: transparent !important;" in dark_html
    assert "box-shadow: none !important;" in dark_html


def test_numbered_code_css_aligns_line_numbers_with_code_rows(tmp_path):
    from mardas_md2pdf.markdown import render_markdown
    from mardas_md2pdf.renderer import PdfOptions, build_html

    md = '```python title="main.py" linenos\nprint(1)\nprint(2)\n```\n'
    input_path = tmp_path / "code.md"
    input_path.write_text(md, encoding="utf-8")
    html = build_html(render_markdown(md), PdfOptions(input_path=input_path, output_path=tmp_path / "out.pdf"))

    assert "code-block--numbered" in html
    assert ".code-block--numbered .codehilitetable td" in html
    assert "padding: 0 !important;" in html
    assert ".code-block--numbered .linenos pre," in html
    assert "font-size: var(--md2pdf-code-font-size, 8.8pt) !important;" in html
    assert "line-height: var(--md2pdf-code-line-height, 1.65) !important;" in html
    assert "padding: var(--md2pdf-code-pre-padding-block, 4.2mm)" in html
    assert "font-variant-numeric: tabular-nums;" in html
    assert "width: auto;" in html
    assert "white-space: nowrap;" in html
    assert "white-space: pre !important;" in html
    assert "overflow-wrap: normal !important;" in html
    assert "word-break: normal !important;" in html
    assert ".code-block--numbered td.linenos .normal" in html
    assert "background: transparent !important;" in html
    assert "box-shadow: none !important;" in html
    assert "display: inline !important;" in html
    assert "body.md2pdf-style-textbook .code-block--numbered .linenos pre" not in html
    assert "display: inline-block;" in html
    assert "min-width: 100%;" in html
    assert "background-color: var(--md2pdf-code-highlight-bg) !important;" in html



def test_highlighted_code_css_preserves_indentation_and_line_metrics(tmp_path):
    from mardas_md2pdf.markdown import render_markdown
    from mardas_md2pdf.renderer import PdfOptions, build_html

    md = (
        '```python title="renderer.py" {2} linenos\n'
        'def convert(markdown: str) -> bytes:\n'
        '    html = render_markdown(markdown)\n'
        '    pdf = render_pdf(html)\n'
        '    return pdf\n'
        '```\n'
    )
    input_path = tmp_path / "highlighted-code.md"
    input_path.write_text(md, encoding="utf-8")
    html = build_html(render_markdown(md), PdfOptions(input_path=input_path, output_path=tmp_path / "out.pdf"))

    assert '.codehilite .hll,' in html
    assert 'padding-inline-start: 0;' in html
    assert 'line-height: inherit;' in html
    assert 'vertical-align: baseline;' in html
    assert 'padding-inline-start: 1.2mm' not in html
    assert '<span class="hll">    <span class="n">html</span>' in html
    assert '</span>\n    <span class="n">pdf</span>' in html

def test_cover_branding_is_off_by_default(tmp_path):
    from mardas_md2pdf.markdown import render_markdown
    from mardas_md2pdf.renderer import PdfOptions, build_html

    md = "---\ntitle: User Report\n---\n\n# Body\n"
    input_path = tmp_path / "report.md"
    input_path.write_text(md, encoding="utf-8")
    html = build_html(render_markdown(md), PdfOptions(input_path=input_path, output_path=tmp_path / "out.pdf"))

    assert "md2pdf-cover--branding-off" in html
    assert '<div class="md2pdf-cover__brand' not in html
    assert '<span class="md2pdf-cover__brand-copy' not in html
    assert '<strong>Mardas Folio</strong>' not in html
    assert '<em>Markdown to PDF Engine</em>' not in html


def test_cover_branding_full_is_explicit(tmp_path):
    from mardas_md2pdf.markdown import render_markdown
    from mardas_md2pdf.renderer import PdfOptions, build_html

    md = "---\ntitle: Guide\nbranding:\n  mode: full\n---\n\n# Body\n"
    input_path = tmp_path / "guide.md"
    input_path.write_text(md, encoding="utf-8")
    html = build_html(render_markdown(md), PdfOptions(input_path=input_path, output_path=tmp_path / "out.pdf"))

    assert "md2pdf-cover--branding-full" in html
    assert "md2pdf-cover__brand--full" in html
    assert "md2pdf-cover__brand--product" in html
    assert "md2pdf-cover__brand--custom" not in html
    assert "box-shadow: none !important;" in html
    assert "linear-gradient(135deg, var(--accent), var(--accent-2))" in html
    assert "linear-gradient(135deg, #0f172a, #2563eb)" not in html
    assert "color-mix(in srgb, var(--accent) 54%, #64748b)" in html
    assert "Mardas Folio" in html
    assert "Markdown to PDF Engine" in html


def test_cover_branding_uses_custom_brand_metadata(tmp_path):
    from mardas_md2pdf.markdown import render_markdown
    from mardas_md2pdf.renderer import PdfOptions, build_html

    md = """---
title: Internal Report
branding:
  mode: full
brand:
  name: Acme Research Lab
  footer: Internal Report
---

# Body
"""
    input_path = tmp_path / "branded.md"
    input_path.write_text(md, encoding="utf-8")
    html = build_html(render_markdown(md), PdfOptions(input_path=input_path, output_path=tmp_path / "out.pdf"))

    assert "md2pdf-cover--branding-full" in html
    assert "md2pdf-cover__brand--full md2pdf-cover__brand--custom" in html
    assert "md2pdf-cover__brand--full md2pdf-cover__brand--product" not in html
    assert "Acme Research Lab" in html
    assert "Internal Report" in html
    assert "Markdown to PDF Engine" not in html


def test_cover_branding_subtle_is_not_a_large_brand_block(tmp_path):
    from mardas_md2pdf.markdown import render_markdown
    from mardas_md2pdf.renderer import PdfOptions, build_html

    md = "---\ntitle: Report\n---\n\n# Body\n"
    input_path = tmp_path / "subtle.md"
    input_path.write_text(md, encoding="utf-8")
    html = build_html(
        render_markdown(md),
        PdfOptions(input_path=input_path, output_path=tmp_path / "out.pdf", branding="subtle"),
    )

    assert "md2pdf-cover--branding-subtle" in html
    assert "md2pdf-cover__brand--subtle" in html
    assert "Generated with Mardas Folio" in html
    assert '<span class="md2pdf-cover__mark"' not in html


def test_strict_publication_fails_when_required_font_is_missing(tmp_path):
    import pytest

    from mardas_md2pdf.quality import FontValidationError
    from mardas_md2pdf.renderer import PdfOptions, _render_pdf

    class FakePage:
        def set_content(self, html_text, wait_until):
            self.html_text = html_text

        def evaluate(self, expression, argument=None):
            if argument is not None:
                return {
                    "status": "loaded",
                    "required": {"Vazirmatn": False},
                    "missing": ["Vazirmatn"],
                    "computed": {},
                    "loaded_faces": [],
                }
            return None

        def emulate_media(self, media):
            self.media = media

        def pdf(self, **kwargs):
            raise AssertionError("PDF export must not run after strict font validation fails")

    options = PdfOptions(
        input_path=tmp_path / "in.md",
        output_path=tmp_path / "out.pdf",
        quality_profile="strict-publication",
    )
    with pytest.raises(FontValidationError, match="Vazirmatn"):
        _render_pdf(
            FakePage(),
            "<html><body></body></html>",
            options,
            tmp_path / "out.pdf",
            display_footer=False,
            footer_context="T",
        )
    assert options.quality_log.payload()["summary"]["error"] == 1


def test_strict_publication_fails_when_mathjax_is_unresolved(tmp_path):
    import pytest

    from mardas_md2pdf.quality import MathJaxRenderError
    from mardas_md2pdf.renderer import PdfOptions, _render_pdf

    class FakePage:
        def set_content(self, html_text, wait_until):
            self.html_text = html_text

        def evaluate(self, expression, argument=None):
            if argument is not None:
                return {
                    "status": "loaded",
                    "required": {"Vazirmatn": True},
                    "missing": [],
                    "computed": {},
                    "loaded_faces": [{"family": "Vazirmatn", "status": "loaded"}],
                }
            if "document.fonts" in expression and "async" not in expression:
                return None
            return {
                "detected": 1,
                "rendered": 0,
                "unresolved": 1,
                "available": True,
                "errors": [],
                "unresolved_samples": ["x^2"],
                "exception": "",
            }

        def emulate_media(self, media):
            self.media = media

        def pdf(self, **kwargs):
            raise AssertionError("PDF export must not run after strict MathJax validation fails")

    options = PdfOptions(
        input_path=tmp_path / "in.md",
        output_path=tmp_path / "out.pdf",
        quality_profile="strict-publication",
    )
    with pytest.raises(MathJaxRenderError, match="detected=1"):
        _render_pdf(
            FakePage(),
            "<html><body><span class='math'>x^2</span></body></html>",
            options,
            tmp_path / "out.pdf",
            display_footer=False,
            footer_context="T",
        )


def test_quality_report_serializes_font_and_math_evidence(tmp_path):
    import json

    from mardas_md2pdf.renderer import PdfOptions, _render_pdf, _write_quality_report

    class FakePage:
        def __init__(self):
            self.calls = 0

        def set_content(self, html_text, wait_until):
            self.html_text = html_text

        def evaluate(self, expression, argument=None):
            self.calls += 1
            if argument is not None:
                return {
                    "status": "loaded",
                    "required": {},
                    "missing": [],
                    "computed": {"body": "Arial"},
                    "loaded_faces": [],
                }
            if self.calls == 1:
                return None
            return {
                "detected": 1,
                "rendered": 1,
                "unresolved": 0,
                "available": True,
                "errors": [],
                "unresolved_samples": [],
                "exception": "",
            }

        def emulate_media(self, media):
            self.media = media

        def pdf(self, **kwargs):
            self.kwargs = kwargs

    report_path = tmp_path / "quality.json"
    options = PdfOptions(
        input_path=tmp_path / "in.md",
        output_path=tmp_path / "out.pdf",
        quality_report=report_path,
    )
    _render_pdf(
        FakePage(),
        "<html><body><span class='math'>x</span></body></html>",
        options,
        tmp_path / "out.pdf",
        display_footer=False,
        footer_context="T",
    )
    _write_quality_report(options)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert {event["category"] for event in payload["events"]} == {"fonts", "mathjax"}

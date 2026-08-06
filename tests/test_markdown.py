from bs4 import BeautifulSoup
from mardas_md2pdf.markdown import render_markdown


def test_mixed_direction_and_code_highlight():
    result = render_markdown("# سلام English\n\nمتن mixed با `code`.\n\n```python\nprint('hi')\n```")
    assert "dir=\"auto\"" in result.body_html
    assert "code-block" in result.body_html
    assert "PYTHON" in result.body_html


def test_fenced_code_language_caption_is_not_merged_into_code():
    result = render_markdown("```c\nint setSeed(void);\n```\n")
    assert '<figure class="code-block"' in result.body_html
    assert '>C</figcaption>' in result.body_html
    assert 'Cint setSeed' not in result.body_html
    assert '<pre><code class="language-c"><figure' not in result.body_html


def test_table_and_math():
    result = render_markdown("|a|b|\n|-|-|\n|1|2|\n\n$$\nx^2\n$$")
    assert "table-wrap" in result.body_html
    assert "math display" in result.body_html


def test_indented_code_blocks_are_wrapped_and_visible():
    result = render_markdown("برنامه تست:\n\n    #include \"user.h\"\n    int main(void) { return 0; }\n")
    assert "raw-code-block" in result.body_html
    assert "<pre" in result.body_html
    assert "C</figcaption>" in result.body_html
    assert "#include" in result.body_html


def test_hierarchical_toc_numbers_and_nesting():
    markdown = "# فصل اول\n\n## بخش اول\n\n## بخش دوم\n\n### زیر بخش\n\n# فصل دوم\n"
    result = render_markdown(markdown, toc=True)
    assert "md2pdf-toc" in result.toc_html
    assert '<span class="toc-number persian-generated-number">۱</span>' in result.toc_html
    assert 'data-md2pdf-number="1-1"' in result.toc_html
    assert '<span class="toc-number persian-generated-number">۱-۱</span>' in result.toc_html
    assert 'data-md2pdf-number="1-2"' in result.toc_html
    assert '<span class="toc-number persian-generated-number">۱-۲</span>' in result.toc_html
    assert 'data-md2pdf-number="1-2-1"' in result.toc_html
    assert '<span class="toc-number persian-generated-number">۱-۲-۱</span>' in result.toc_html
    assert 'data-md2pdf-number="2"' in result.toc_html
    assert '<span class="toc-number persian-generated-number">۲</span>' in result.toc_html
    assert 'toc-depth-2' in result.toc_html


def test_public_appearance_choices_are_separated_by_responsibility():
    from mardas_md2pdf.cli import build_parser

    parser = build_parser()
    style_action = next(action for action in parser._actions if "--style" in action.option_strings)
    palette_action = next(action for action in parser._actions if "--palette" in action.option_strings)
    mode_action = next(action for action in parser._actions if "--mode" in action.option_strings)

    assert "textbook" in style_action.choices
    assert "textbook-light" not in style_action.choices
    assert "blue" in palette_action.choices
    assert "emerald" in palette_action.choices
    assert mode_action.choices == ["light", "dark"]
    assert all("--theme" not in action.option_strings for action in parser._actions)
    assert all("--profile" not in action.option_strings for action in parser._actions)


def test_cover_branding_option_is_explicit_and_clean():
    from mardas_md2pdf.cli import build_parser

    parser = build_parser()
    help_text = parser.format_help()
    branding_action = next(action for action in parser._actions if "--branding" in action.option_strings)

    assert branding_action.choices == ("off", "subtle", "full")
    assert "--branding" in help_text
    assert "--brand-name" in help_text
    assert "--brand-logo" in help_text
    assert all("--no-cover-brand" not in action.option_strings for action in parser._actions)


def test_gui_entrypoint_module_exists():
    import mardas_md2pdf.gui as gui

    assert gui.build_parser().prog == "mrs-md2pdf-gui"


def test_local_markdown_images_are_embedded_as_data_uris(tmp_path):
    from mardas_md2pdf.markdown import render_markdown_file

    png = tmp_path / "chart.png"
    png.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\xe2\x08\x9b\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    md = tmp_path / "report.md"
    md.write_text("![Chart](chart.png)\n", encoding="utf-8")

    result = render_markdown_file(md)

    assert 'src="data:image/png;base64,' in result.body_html
    assert 'data-md2pdf-source="chart.png"' in result.body_html


def test_local_image_lookup_falls_back_to_markdown_directory_basename(tmp_path):
    from mardas_md2pdf.markdown import render_markdown_file

    png = tmp_path / "executive_overview.png"
    png.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\xe2\x08\x9b\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    md = tmp_path / "report.md"
    md.write_text('<img src="./images/executive_overview.png" alt="Overview">\n', encoding="utf-8")

    result = render_markdown_file(md)

    assert 'src="data:image/png;base64,' in result.body_html
    assert 'data-md2pdf-source="./images/executive_overview.png"' in result.body_html




def test_local_image_lookup_stays_inside_markdown_directory(tmp_path):
    from mardas_md2pdf.markdown import render_markdown_file

    outside = tmp_path / "outside.png"
    outside.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\xe2\x08\x9b\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    md = docs / "report.md"
    md.write_text("![leak](../outside.png)\n", encoding="utf-8")

    result = render_markdown_file(md)

    assert 'data-md2pdf-blocked-src="../outside.png"' in result.body_html
    assert "md2pdf-image--blocked" in result.body_html
    assert "data:image/png;base64" not in result.body_html




def test_missing_local_image_is_blocked_before_chromium_can_resolve_it(tmp_path):
    from mardas_md2pdf.markdown import render_markdown_file

    md = tmp_path / "report.md"
    md.write_text('<img src="images/missing.png" alt="missing">\n', encoding="utf-8")

    result = render_markdown_file(md)

    assert 'data-md2pdf-blocked-src="images/missing.png"' in result.body_html
    assert "md2pdf-image--blocked" in result.body_html
    assert ' src="images/missing.png"' not in result.body_html
    assert "md2pdf-image-placeholder" in result.body_html
    assert "Image blocked or missing" in result.body_html

def test_file_url_markdown_images_are_not_embedded(tmp_path):
    from mardas_md2pdf.markdown import render_markdown_file

    image = tmp_path / "local.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\xe2\x08\x9b\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    md = tmp_path / "report.md"
    md.write_text(f"![local]({image.as_uri()})\n", encoding="utf-8")

    result = render_markdown_file(md)

    assert image.as_uri() in result.body_html
    assert "data:image/png;base64" not in result.body_html


def test_raw_html_sanitizer_removes_file_urls():
    result = render_markdown('<a href="file:///etc/passwd">secret</a><img src="file:///etc/passwd">')

    assert 'href="file://' not in result.body_html
    assert 'src="file://' not in result.body_html




def test_raw_html_sanitizer_restricts_data_image_urls():
    result = render_markdown(
        '<img src="data:image/png;base64,AA==">'
        '<img src="data:image/svg+xml;base64,PHN2Zy8+">'
        '<img src="data:text/html;base64,PGgxPkJvbzwvaDE+">'
    )

    assert 'src="data:image/png;base64,AA=="' in result.body_html
    assert "data:image/svg+xml" not in result.body_html
    assert "data:text/html" not in result.body_html


def test_raw_html_sanitizer_rejects_obfuscated_url_controls():
    result = render_markdown('<a href="java&#10;script:alert(1)">bad</a>')

    assert "href=" not in result.body_html
    assert "bad" in result.body_html


def test_cover_supports_multiline_summary_and_multiple_authors(tmp_path):
    from mardas_md2pdf.renderer import PdfOptions, build_html

    md = """---
title: "گزارش نمونه"
subtitle: "نمونه metadata پیشرفته"
authors:
  - name: "Meraj Rastegar"
    email: "mragetsars@gmail.com"
  - "Mardas Team"
summary: |
  خط اول خلاصه برای جلد PDF.
  خط دوم خلاصه باید در همان پاراگراف با شکست خط بماند.

  این پاراگراف دوم خلاصه است.
cover_label: "گزارش آزمایشی"
institution: "Tehran University"
course: "Data Science"
keywords:
  - RTL
  - PDF
lang: fa
---

# بدنه
"""
    result = render_markdown(md)
    input_path = tmp_path / "sample.md"
    input_path.write_text(md, encoding="utf-8")

    html = build_html(result, PdfOptions(input_path=input_path, output_path=tmp_path / "sample.pdf"))

    assert "نویسندگان" in html
    assert "Meraj Rastegar (mragetsars@gmail.com)" in html
    assert "Mardas Team" in html
    assert "خط اول خلاصه برای جلد PDF.<br>خط دوم خلاصه" in html
    assert "این پاراگراف دوم خلاصه است." in html
    assert "Tehran University" in html
    assert "Data Science" in html
    assert "RTL" in html
    assert "PDF" in html
    assert "گزارش آزمایشی" in html
    assert "گزارش PDF" not in html
    assert '<section class="md2pdf-cover__top" dir="ltr">' in html


def test_inline_math_keeps_mathjax_delimiters_after_markdown_parsing():
    result = render_markdown("متن فارسی با $T=500$ و $\\epsilon=0.05$ وسط جمله.")
    assert '<span class="math inline">\\(T=500\\)</span>' in result.body_html
    assert '<span class="math inline">\\(\\epsilon=0.05\\)</span>' in result.body_html
    assert '<span class="math inline">(T=500)</span>' not in result.body_html
    assert '<span class="math inline">(\\epsilon=0.05)</span>' not in result.body_html


def test_toc_preserves_inline_math_for_mathjax_rendering():
    result = render_markdown("## استنتاج\n\n### اثر $T$ و $\\epsilon$ روی دقت\n", toc=True)
    assert '<span class="toc-title toc-title--mixed mixed-script" dir="auto">اثر <span class="math inline">\\(T\\)</span> و <span class="math inline">\\(\\epsilon\\)</span> روی دقت</span>' in result.toc_html
    assert '(\\epsilon)' not in result.toc_html


def test_multiline_footnotes_render_as_markdown_blocks():
    result = render_markdown(
        "متن دارای ارجاع[^n].\n\n"
        "[^n]: خط اول پانویس.\n"
        "    خط دوم همان پانویس با **تاکید**.\n\n"
        "    - مورد اول\n"
        "    - مورد دوم\n"
    )
    assert 'footnote-body' in result.body_html
    assert 'data-md2pdf-direction-profile="rtl"' in result.body_html
    assert "خط دوم همان پانویس" in result.body_html
    assert "<strong>تاکید</strong>" in result.body_html
    assert '<li class="md2pdf-rtl-text" dir="rtl">مورد اول</li>' in result.body_html
    assert '<section aria-label="پانویس‌ها" class="footnotes footnotes--local footnotes--rtl" dir="rtl">' in result.body_html
    assert 'class="footnote-item footnote-item--persian footnote-item--rtl" id="fn-n"' in result.body_html
    assert '<span class="footnote-marker persian-generated-number">۱.</span>' in result.body_html


def test_raw_html_is_sanitized_by_default():
    result = render_markdown('<img src="chart.png" onerror="alert(1)"><script>alert(1)</script>')
    assert "<script" not in result.body_html
    assert "onerror" not in result.body_html
    assert '<img src="chart.png"' in result.body_html


def test_renderer_page_size_and_direction_are_late_css_overrides(tmp_path):
    from mardas_md2pdf.renderer import PdfOptions, build_html

    md = """---
title: English report
lang: en
dir: ltr
---

# English report

Only English text.
"""
    result = render_markdown(md)
    input_path = tmp_path / "english.md"
    input_path.write_text(md, encoding="utf-8")
    html = build_html(
        result,
        PdfOptions(input_path=input_path, output_path=tmp_path / "english.pdf", page_size="Letter"),
    )
    assert "size: 8.5in 11in;" in html
    assert '<html lang="en" dir="ltr">' in html
    assert "md2pdf-dir-ltr" in html


def test_lang_en_localizes_toc_callouts_and_cover_direction(tmp_path):
    from mardas_md2pdf.renderer import PdfOptions, build_html

    md = """---
title: English report
lang: en
---

# English report

> [!NOTE]
> This is a localized callout.

## Analysis
"""
    result = render_markdown(md, toc=True)
    input_path = tmp_path / "english.md"
    input_path.write_text(md, encoding="utf-8")
    html = build_html(result, PdfOptions(input_path=input_path, output_path=tmp_path / "english.pdf"))

    assert "Table of Contents" in result.toc_html
    assert "فهرست مطالب" not in result.toc_html
    assert "Note" in result.body_html
    assert '<html lang="en" dir="ltr">' in html
    assert 'class="md2pdf-cover md2pdf-cover--branding-off md2pdf-cover--unbranded" lang="en" dir="ltr"' in html
    assert "Generated Document" in html
    assert "PDF Report" not in html
    assert '<section class="md2pdf-cover__top" dir="ltr">' in html


def test_lang_en_drives_ltr_shell_even_when_body_contains_persian(tmp_path):
    from mardas_md2pdf.renderer import PdfOptions, build_html

    md = """---
title: Mixed language notes
lang: en
dir: auto
---

# English title

این پاراگراف فارسی است اما پوسته سند باید با lang انگلیسی LTR شود.
"""
    result = render_markdown(md, toc=True)
    input_path = tmp_path / "mixed.md"
    input_path.write_text(md, encoding="utf-8")
    html = build_html(result, PdfOptions(input_path=input_path, output_path=tmp_path / "mixed.pdf"))

    assert '<html lang="en" dir="ltr">' in html
    assert "Table of Contents" in result.toc_html


def test_math_scaling_rules_distinguish_inline_and_display_math(tmp_path):
    from mardas_md2pdf.renderer import PdfOptions, build_html

    md = "متن با $E=mc^2$ و سپس:\n\n$$\nE=mc^2\n$$\n"
    result = render_markdown(md)
    input_path = tmp_path / "math.md"
    input_path.write_text(md, encoding="utf-8")
    html = build_html(result, PdfOptions(input_path=input_path, output_path=tmp_path / "math.pdf"))

    assert "--md2pdf-inline-math-scale: 100%;" in html
    assert "--md2pdf-display-math-scale: 130%;" in html
    assert "mjx-container:not([display=\"true\"])" in html
    assert "mjx-container[display=\"true\"]" in html


def test_cover_label_aliases_and_ltr_cover_alignment(tmp_path):
    from mardas_md2pdf.renderer import PdfOptions, build_html

    md = """---
title: English report
subtitle: Left aligned subtitle
summary: |
  The summary should start on the left side of the English cover.
cover_label: Custom Cover Label
lang: en
---

# Body
"""
    result = render_markdown(md)
    input_path = tmp_path / "english.md"
    input_path.write_text(md, encoding="utf-8")
    html = build_html(result, PdfOptions(input_path=input_path, output_path=tmp_path / "english.pdf"))

    assert "Custom Cover Label" in html
    assert "Generated Document" not in html
    assert "body.md2pdf-dir-ltr .md2pdf-cover__content" in html
    assert "margin-left: 0;" in html
    assert "body.md2pdf-dir-ltr .md2pdf-cover__summary { margin: 5mm auto 0 0; }" in html
    assert "body.md2pdf-dir-rtl .md2pdf-cover__detail > span" in html
    assert "font-family: var(--font-fa), var(--font-en);" in html


def test_fenced_code_without_language_renders_as_text_block():
    result = render_markdown("````\nplain $x$ and [^n]\n````\n\n[^n]: footnote\n")
    assert '<figure class="code-block" data-lines="1" dir="ltr">' in result.body_html
    assert '>TEXT</figcaption>' in result.body_html
    assert 'md2pdf-caption--code' in result.body_html
    assert "plain $x$ and [^n]" in result.body_html


def test_math_and_footnotes_are_not_expanded_inside_inline_code():
    result = render_markdown(
        "Use `$x$` and `[^note]` literally, but render $y$[^note].\n\n[^note]: fn"
    )
    assert '<code dir="ltr">$x$</code>' in result.body_html
    assert '<code dir="ltr">[^note]</code>' in result.body_html
    assert '<span class="math inline">\\(y\\)</span>' in result.body_html
    assert '<sup class="footnote-ref latin-generated-number" id="fnref-note">' in result.body_html


def test_footnote_refs_are_not_expanded_inside_fenced_code():
    result = render_markdown("```text\n[^note]\n```\n\n[^note]: fn")
    assert '[^note]' in result.body_html
    assert '<sup class="footnote-ref" id="fnref-note">' not in result.body_html.split("</figure>", 1)[0]


def test_large_local_images_are_left_as_links_with_warning(tmp_path, monkeypatch):
    import pytest

    from mardas_md2pdf import markdown as markdown_module

    image = tmp_path / "large.png"
    image.write_bytes(b"not really a png, but enough for this test")
    monkeypatch.setattr(markdown_module, "MAX_EMBED_IMAGE_BYTES", 1)

    md = tmp_path / "report.md"
    md.write_text("![large](large.png)\n", encoding="utf-8")

    with pytest.warns(RuntimeWarning, match="Skipping image larger than"):
        result = markdown_module.render_markdown_file(md)

    assert 'src="large.png"' in result.body_html
    assert 'data:image/png;base64' not in result.body_html


def test_mermaid_flowchart_fence_renders_to_inline_svg():
    result = render_markdown(
        "```mermaid\n"
        "flowchart TD\n"
        "    CSV[CSV datasets] --> App[UTMSApplication]\n"
        "    App --> Core[Instruction_Handler]\n"
        "    Core --> Domain[Domain Models]\n"
        "```\n"
    )
    assert "mermaid-diagram--rendered" in result.body_html
    assert "md2pdf-mermaid-svg" in result.body_html
    assert "CSV datasets" in result.body_html
    assert "UTMSApplication" in result.body_html
    assert "code-block" not in result.body_html


def test_mermaid_svg_rendering_does_not_require_xml_parser(monkeypatch):
    from mardas_md2pdf import markdown as markdown_module

    real_beautiful_soup = markdown_module.BeautifulSoup

    def beautiful_soup_without_xml(markup, features=None, *args, **kwargs):
        if features == "xml":
            raise AssertionError("Mermaid SVG rendering must not require the optional lxml/XML parser")
        return real_beautiful_soup(markup, features, *args, **kwargs)

    monkeypatch.setattr(markdown_module, "BeautifulSoup", beautiful_soup_without_xml)

    result = markdown_module.render_markdown(
        "```mermaid\n"
        "flowchart TD\n"
        "    A[Input] --> B[Output]\n"
        "```\n"
    )

    assert "mermaid-diagram--rendered" in result.body_html
    assert "md2pdf-mermaid-svg" in result.body_html


def test_mermaid_supports_labelled_edges_and_shapes():
    result = render_markdown(
        "```mermaid\n"
        "flowchart LR\n"
        "    Start((Start)) -->|valid| Decision{Ready?}\n"
        "    Decision -- yes --> Done[Done]\n"
        "    Decision -. no .-> Retry(Retry)\n"
        "```\n"
    )
    assert "md2pdf-mermaid-node-circle" in result.body_html
    assert "md2pdf-mermaid-node-diamond" in result.body_html
    assert "md2pdf-mermaid-edge-label" in result.body_html
    assert "valid" in result.body_html
    assert "yes" in result.body_html
    assert "md2pdf-mermaid-edge-dotted" in result.body_html


def test_non_mermaid_code_fences_still_highlight_normally():
    result = render_markdown("```python\nprint('hi')\n```\n")
    assert "code-block" in result.body_html
    assert "mermaid-diagram" not in result.body_html


def test_literal_autolinks_are_created_outside_code_only():
    result = render_markdown("Visit www.example.com and dev@example.com, but keep `www.code.test` literal.")
    assert '<a href="https://www.example.com">www.example.com</a>' in result.body_html
    assert '<a href="mailto:dev@example.com">dev@example.com</a>' in result.body_html
    assert '<code dir="ltr">www.code.test</code>' in result.body_html


def test_code_fence_titles_line_numbers_and_highlight_lines():
    result = render_markdown('```python title="main.py" {2} linenos\nprint(1)\nprint(2)\n```\n')
    assert 'code-block--numbered' in result.body_html
    assert 'code-block--highlighted' in result.body_html
    assert '<figcaption class="md2pdf-caption md2pdf-caption--code md2pdf-caption--ltr md2pdf-caption--profiled md2pdf-ltr-text" data-md2pdf-direction-profile="ltr" data-md2pdf-number-profile="none" dir="ltr">main.py</figcaption>' in result.body_html
    assert 'codehilitetable' in result.body_html
    assert 'class="hll"' in result.body_html


def test_highlighted_code_line_break_stays_outside_hll_wrapper():
    result = render_markdown(
        '```python title="renderer.py" {2} linenos\n'
        'def convert(markdown: str) -> bytes:\n'
        '    html = render_markdown(markdown)\n'
        '    pdf = render_pdf(html)\n'
        '    return pdf\n'
        '```\n'
    )

    assert '<span class="hll">' in result.body_html
    assert '</span>\n    <span class="n">pdf</span>' in result.body_html
    assert (
        'render_markdown</span><span class="p">(</span><span class="n">markdown</span>'
        '<span class="p">)</span>\n</span>'
    ) not in result.body_html


def test_pagebreak_directives_normalize_to_pdf_break_class():
    result = render_markdown("A\n\n<!-- pagebreak -->\n\nB\n\n:::pagebreak\n:::\n\nC")
    assert result.body_html.count('md2pdf-page-break') >= 2


def test_image_caption_pair_becomes_semantic_figure():
    result = render_markdown("![Arch](arch.png)\n\n*Figure 1. Architecture overview.*\n")
    assert 'class="md2pdf-figure"' in result.body_html
    assert '<figcaption' in result.body_html
    assert 'Architecture overview' in result.body_html


def test_headings_receive_permalink_anchor():
    result = render_markdown("## Installation\n")
    assert 'class="heading-anchor"' in result.body_html
    assert 'href="#installation"' in result.body_html


def test_details_summary_are_pdf_friendly_and_open():
    result = render_markdown("<details>\n<summary>Advanced</summary>\n<p>Body</p>\n</details>")
    assert '<details class="md2pdf-details" open="open">' in result.body_html or '<details open="open" class="md2pdf-details">' in result.body_html
    assert 'md2pdf-summary' in result.body_html


def test_pagebreak_directives_inside_fenced_code_remain_literal():
    result = render_markdown("```md\n<!-- pagebreak -->\n\n:::pagebreak\n:::\n\n---page---\n```\n")
    first_figure = result.body_html.split("</figure>", 1)[0]
    assert "&lt;!-- pagebreak --&gt;" in first_figure
    assert ":::pagebreak" in first_figure
    assert "---page---" in first_figure
    assert "md2pdf-page-break" not in first_figure


def test_display_math_uses_mathjax_display_delimiters_without_double_escaping():
    result = render_markdown("$$\nx^2 + y^2 = z^2\n$$\n")
    assert '<div class="math display">$$x^2 + y^2 = z^2$$</div>' in result.body_html
    assert "\\[" not in result.body_html



def test_tall_mermaid_flowchart_gets_print_scaling_class():
    md = (
        "```mermaid\n"
        "flowchart TD\n"
        "A[Start] --> B[Middle]\n"
        "B --> C[Next]\n"
        "C --> D[Next]\n"
        "D --> E[Next]\n"
        "E --> F[Next]\n"
        "F --> G[Next]\n"
        "G --> H[Next]\n"
        "H --> I[Next]\n"
        "I --> J[End]\n"
        "```\n"
    )
    result = render_markdown(md)

    assert "mermaid-diagram--rendered" in result.body_html
    assert "mermaid-diagram--tall" in result.body_html
    assert "preserveaspectratio" in result.body_html.lower()


def test_wide_mermaid_flowchart_gets_print_scaling_class():
    md = (
        "```mermaid\n"
        "flowchart LR\n"
        "A[Alpha] --> B[Beta] --> C[Gamma] --> D[Delta] --> E[Epsilon] --> F[Zeta]\n"
        "```\n"
    )
    result = render_markdown(md)

    assert "mermaid-diagram--rendered" in result.body_html
    assert "mermaid-diagram--wide" in result.body_html



def test_render_markdown_blocks_remote_images_by_default():
    result = render_markdown("![Remote](https://example.com/image.png)\n")

    assert "https://example.com/image.png" in result.body_html
    assert 'data-md2pdf-blocked-reason="remote"' in result.body_html
    assert "md2pdf-image-placeholder" in result.body_html
    assert "Remote image blocked" in result.body_html
    assert "<img" not in result.body_html


def test_render_markdown_can_allow_remote_images():
    result = render_markdown("![Remote](https://example.com/image.png)\n", allow_remote_images=True)

    assert 'src="https://example.com/image.png"' in result.body_html
    assert "data-md2pdf-blocked-reason" not in result.body_html


def test_render_markdown_file_blocks_remote_images_by_default(tmp_path):
    from mardas_md2pdf.markdown import render_markdown_file

    input_path = tmp_path / "remote.md"
    input_path.write_text("![Remote](https://example.com/image.png)\n", encoding="utf-8")

    result = render_markdown_file(input_path)

    assert "https://example.com/image.png" in result.body_html
    assert "data-md2pdf-blocked-reason=\"remote\"" in result.body_html
    assert "md2pdf-image-placeholder" in result.body_html
    assert "Remote image blocked" in result.body_html


def test_render_markdown_file_can_allow_remote_images(tmp_path):
    from mardas_md2pdf.markdown import render_markdown_file

    input_path = tmp_path / "remote.md"
    input_path.write_text("![Remote](https://example.com/image.png)\n", encoding="utf-8")

    result = render_markdown_file(input_path, allow_remote_images=True)

    assert 'src="https://example.com/image.png"' in result.body_html
    assert "data-md2pdf-blocked-reason" not in result.body_html



def test_missing_local_images_render_visible_placeholders(tmp_path):
    from mardas_md2pdf.markdown import render_markdown_file

    input_path = tmp_path / "missing.md"
    input_path.write_text("![Missing](images/missing.png)\n", encoding="utf-8")

    result = render_markdown_file(input_path)

    assert "md2pdf-image-placeholder" in result.body_html
    assert "Image blocked or missing" in result.body_html
    assert "images/missing.png" in result.body_html



def test_wide_tables_get_print_fit_classes():
    columns = "|" + "|".join(f"C{i}" for i in range(1, 13)) + "|"
    divider = "|" + "|".join("---" for _ in range(12)) + "|"
    values = "|" + "|".join(f"Value {i}" for i in range(1, 13)) + "|"

    result = render_markdown("\n".join([columns, divider, values]))

    assert "table-wrap--wide" in result.body_html
    assert "table-wrap--very-wide" in result.body_html
    assert 'data-md2pdf-columns="12"' in result.body_html


def test_render_markdown_exposes_stable_heading_source_map_with_frontmatter() -> None:
    result = render_markdown(
        """---
title: Source map
---

# Intro

Text.

## تکراری

### Child

## تکراری
"""
    )

    assert [item["line"] for item in result.source_map] == [5, 9, 11, 13]
    assert [item["level"] for item in result.source_map] == [1, 2, 3, 2]
    assert len({item["id"] for item in result.source_map}) == 4
    assert 'data-source-line="5"' in result.body_html
    assert 'data-source-line="13"' in result.body_html


def test_render_markdown_source_map_ignores_fenced_heading_text() -> None:
    result = render_markdown(
        """# Real

```markdown
# Not a heading
```

## Also real
"""
    )

    assert [item["title"] for item in result.source_map] == ["Real", "Also real"]
    assert [item["line"] for item in result.source_map] == [1, 7]


def test_source_map_does_not_assign_markdown_lines_to_raw_html_headings():
    result = render_markdown(
        "# First\n\n<h2>Raw HTML</h2>\n\n## Second\n",
        unsafe_html=True,
    )

    assert [(item["title"], item["line"]) for item in result.source_map] == [
        ("First", 1),
        ("Second", 5),
    ]
    soup = BeautifulSoup(result.body_html, "html.parser")
    raw_heading = next(item for item in soup.find_all("h2") if "Raw HTML" in item.get_text())
    assert raw_heading.get("data-source-line") is None

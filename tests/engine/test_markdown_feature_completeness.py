from mardas_folio.markdown import parse_code_fence_info, render_markdown
from mardas_folio.mermaid import render_mermaid_to_svg


def test_code_fence_parser_accepts_pandoc_style_attributes():
    info = '{.python .numberLines title=renderer.py hl_lines="2 5-6"}'

    parsed = parse_code_fence_info(info)

    assert parsed["language"] == "python"
    assert parsed["title"] == "renderer.py"
    assert parsed["linenos"] is True
    assert parsed["highlight_lines"] == [2, 5, 6]


def test_code_fence_parser_accepts_aliases_and_unquoted_values():
    parsed = parse_code_fence_info('py filename=app.py lineNumbers=true highlight=1,3-4')

    assert parsed["language"] == "python"
    assert parsed["title"] == "app.py"
    assert parsed["linenos"] is True
    assert parsed["highlight_lines"] == [1, 3, 4]


def test_code_fence_attributes_render_with_title_line_numbers_and_highlights():
    result = render_markdown(
        '```{.python .numberLines title=renderer.py hl_lines="2 5-6"}\n'
        'def convert(markdown: str) -> bytes:\n'
        '    html = render_markdown(markdown)\n'
        '    pdf = render_pdf(html)\n'
        '    metadata = inspect_pdf(pdf)\n'
        '    log_export(metadata)\n'
        '    return pdf\n'
        '```\n'
    )

    assert 'md2pdf-caption--code' in result.body_html
    assert 'renderer.py</figcaption>' in result.body_html
    assert 'data-lang="python"' in result.body_html
    assert 'data-lines="6"' in result.body_html
    assert 'code-block--numbered' in result.body_html
    assert 'code-block--highlighted' in result.body_html
    assert result.body_html.count('class="hll"') == 3
    assert 'log_export' in result.body_html


def test_mermaid_fence_title_is_preserved_as_caption():
    result = render_markdown(
        '```mermaid title="Pipeline"\n'
        'flowchart LR\n'
        '  A[Input] --> B[Output]\n'
        '```\n'
    )

    assert 'md2pdf-caption--diagram' in result.body_html
    assert 'Pipeline</figcaption>' in result.body_html
    assert 'mermaid-diagram--rendered' in result.body_html


def test_mermaid_svg_supports_additional_common_node_shapes():
    svg = render_mermaid_to_svg(
        'flowchart LR\n'
        '  Store[(Database)] --> Transform{{Transform}}\n'
        '  Transform --> Stage[[Subroutine]]\n'
        '  Stage --> Done([Done])\n'
    )

    assert svg is not None
    assert 'md2pdf-mermaid-node-database' in svg
    assert 'md2pdf-mermaid-node-hexagon' in svg
    assert 'md2pdf-mermaid-node-subroutine' in svg
    assert 'md2pdf-mermaid-node-stadium' in svg
    assert svg.count('</marker>') == 1


def test_code_fence_parser_accepts_start_line_metadata():
    parsed = parse_code_fence_info('python linenos linenostart=42 title="module.py" {43}')

    assert parsed["language"] == "python"
    assert parsed["title"] == "module.py"
    assert parsed["linenos"] is True
    assert parsed["line_start"] == 42
    assert parsed["highlight_lines"] == [43]


def test_numbered_code_blocks_can_start_from_custom_line():
    result = render_markdown(
        '```python linenos linenostart=42 title="module.py" {43}\n'
        'def first():\n'
        '    return 1\n'
        '```\n'
    )

    assert 'data-line-start="42"' in result.body_html
    assert 'md2pdf-caption--code' in result.body_html
    assert 'module.py</figcaption>' in result.body_html
    assert 'class="hll"' in result.body_html
    assert '>42<' in result.body_html


def test_extended_callout_aliases_render_as_pdf_callouts():
    result = render_markdown(
        '> [!SUCCESS] Build passed\n'
        '> Everything is green.\n\n'
        '> [!QUESTION]- Why?\n'
        '> Because the renderer supports aliases.\n'
    )

    assert 'callout-success' in result.body_html
    assert 'callout-question' in result.body_html
    assert 'callout-foldable' in result.body_html
    assert '<strong class="callout-title">Build passed</strong>' in result.body_html
    assert '<strong class="callout-title">Why?</strong>' in result.body_html

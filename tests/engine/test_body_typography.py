from pathlib import Path

import pytest

from mardas_folio.config import RENDER_OPTION_SPECS, ConfigValueError
from mardas_folio.markdown import render_markdown_text
from mardas_folio.print_layout import layout_css
from mardas_folio.publishing.html_document import compose_document
from mardas_folio.render_contracts import PdfOptions


def test_body_typography_shares_page_layout_contract():
    options = PdfOptions(input_path=Path("input.md"), output_path=Path("out.pdf"))
    base, _ = layout_css(options, document_direction="rtl")
    assert "text-align: justify; text-align-last: auto" in base
    options.body_font = "serif"
    options.body_size_pt = 14.25
    options.body_leading = 1.85
    options.paragraph_align = "start"
    for direction in ["rtl", "ltr"]:
        css, _ = layout_css(options, document_direction=direction)
        assert "font-size: 14.25pt; line-height: 1.85;" in css
        assert "font-family: Georgia" in css
        assert "text-align: start; text-align-last: auto" in css
        assert ".md2pdf-cover *, nav *, .toc *" in css
        assert "table *, figure *" in css


@pytest.mark.parametrize(
    "key,value",
    [
        ("body_size_pt", float("nan")),
        ("body_size_pt", 31),
        ("body_size_pt", True),
        ("body_leading", 0.99),
        ("body_leading", float("inf")),
        ("body_font", "url(https://example.invalid/)"),
        ("paragraph_align", "initial;"),
    ],
)
def test_invalid_typography_rejected(key, value):
    with pytest.raises(ConfigValueError):
        RENDER_OPTION_SPECS[key].validator(value)


def test_explicit_vazirmatn_has_offline_font_faces_for_preview_and_print(tmp_path):
    path = tmp_path / "bilingual.md"
    result = render_markdown_text("English and فارسی.\n", source_path=path)
    options = PdfOptions(input_path=path, output_path=path.with_suffix(".pdf"))
    assert not compose_document(result, options).font_faces_css
    options.body_font = "vazirmatn"
    printed = compose_document(result, options)
    previewed = compose_document(result, options, embed_fonts=True)
    assert printed.font_faces_css == previewed.font_faces_css
    assert printed.font_faces_css.count("data:font/ttf;base64,") == 2
    assert "font-family: 'Vazirmatn'" in printed.font_faces_css

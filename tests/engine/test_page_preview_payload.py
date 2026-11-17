"""The published-page preview must be the page, not an approximation of it.

The export screen exists to answer one question: what will the PDF look like.
Every assertion here holds some part of the answer — the sheet's real size, the
margin box, the cover the exporter prints full-bleed, the running footer, the
contents and bibliography that used to be dropped — against the composition the
renderer actually hands to Chromium.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mardas_folio import application, renderer
from mardas_folio.application import EngineService
from mardas_folio.markdown import render_markdown_text
from mardas_folio.renderer import PdfOptions, build_html, compose_document, page_geometry


DOCUMENT = """---
title: Quarterly Report
author: Mardas
subtitle: Second edition
---

# سرفصل نخست

متن فارسی همراه با English inline text.

## Details

| Column | Value |
| --- | --- |
| One | 1 |

```python
print("hello")
```
"""


def _options(tmp_path: Path, **overrides: object) -> PdfOptions:
    source = tmp_path / "doc.md"
    source.write_text(DOCUMENT, encoding="utf-8")
    return PdfOptions(input_path=source, output_path=tmp_path / "doc.pdf", **overrides)


def _payload(tmp_path: Path, **overrides: object) -> dict:
    options = _options(tmp_path, **overrides)
    result = render_markdown_text(
        DOCUMENT,
        source_path=options.input_path,
        toc=options.toc,
        toc_depth=options.toc_depth,
    )
    return renderer.preview_page_payload(result, options)


def test_page_geometry_reports_the_sheet_and_its_margin_box(tmp_path: Path) -> None:
    geometry = page_geometry(_options(tmp_path))
    assert geometry["width_mm"] == 210.0
    assert geometry["height_mm"] == 297.0
    assert geometry["orientation"] == "portrait"
    # The content box is what decides how much fits on a page.
    assert geometry["content_width_mm"] == pytest.approx(210 - 16 * 2)
    assert geometry["content_height_mm"] == pytest.approx(297 - 18 - 20)


def test_page_geometry_follows_size_orientation_and_custom_margins(tmp_path: Path) -> None:
    geometry = page_geometry(
        _options(
            tmp_path,
            page_size="A4 landscape",
            margin_top="1cm",
            margin_bottom="1cm",
            margin_x="0.5in",
        )
    )
    assert geometry["width_mm"] == 297.0
    assert geometry["height_mm"] == 210.0
    assert geometry["orientation"] == "landscape"
    assert geometry["margin_top_mm"] == pytest.approx(10.0)
    assert geometry["margin_x_mm"] == pytest.approx(12.7)


def test_margins_wider_than_the_paper_still_leave_a_printable_box(tmp_path: Path) -> None:
    # A misconfiguration must not produce a negative page that the preview
    # would then try to divide by.
    geometry = page_geometry(_options(tmp_path, page_size="A5", margin_x="120mm"))
    assert geometry["content_width_mm"] >= 10.0


def test_preview_payload_carries_the_whole_published_page(tmp_path: Path) -> None:
    payload = _payload(tmp_path, toc=True, cover=True)

    # Contents and bibliography were silently dropped by the old preview, which
    # is exactly the sort of difference the screen is supposed to show.
    assert "md2pdf-toc" in payload["content_html"] or "toc" in payload["content_html"]
    assert payload["css"]["style"] and payload["css"]["palette"]
    assert payload["css"]["pygments"]
    assert "md2pdf-style-modern" in payload["body_classes"]
    # The direction the renderer settled on is carried through, so the preview
    # lays the page out the same way round as the PDF.
    assert payload["direction"] in {"rtl", "ltr"}
    assert f"md2pdf-dir-{payload['direction']}" in payload["body_classes"]
    assert payload["page"]["width_mm"] == 210.0


def test_the_cover_is_returned_the_way_the_exporter_prints_it(tmp_path: Path) -> None:
    payload = _payload(tmp_path, cover=True)
    cover = payload["cover"]
    assert cover is not None
    assert "md2pdf-cover" in cover["html"]
    # The exporter renders the cover as its own full-bleed PDF, so the preview
    # gets the full-bleed layout rather than the content page's margins.
    assert "md2pdf-cover-full-bleed" in cover["body_classes"]
    assert "--page-margin-top: 0" in cover["layout_css"]


def test_no_cover_option_means_no_cover_sheet(tmp_path: Path) -> None:
    assert _payload(tmp_path, cover=False)["cover"] is None


def test_the_running_footer_matches_the_one_chromium_prints(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    footer = payload["footer"]
    assert footer["enabled"] is True
    assert "pageNumber" in footer["html"] and "totalPages" in footer["html"]

    persian = _payload(tmp_path, document_language="fa-IR")
    assert persian["footer"]["page_label"] == "صفحه"
    assert _payload(tmp_path, document_language="en-US")["footer"]["page_label"] == "Page"

    disabled = _payload(tmp_path, no_header_footer=True)
    assert disabled["footer"]["enabled"] is False


def test_the_watermark_travels_with_the_page(tmp_path: Path) -> None:
    payload = _payload(tmp_path, watermark_text="DRAFT")
    assert "DRAFT" in payload["watermark_html"]
    assert _payload(tmp_path)["watermark_html"] == ""


def test_math_is_reported_rather_than_pretended(tmp_path: Path) -> None:
    source = tmp_path / "math.md"
    source.write_text("Value $x^2$ and\n\n$$y = 1$$\n", encoding="utf-8")
    options = PdfOptions(input_path=source, output_path=tmp_path / "math.pdf")
    result = render_markdown_text(source.read_text(encoding="utf-8"), source_path=source)
    payload = renderer.preview_page_payload(result, options)
    assert payload["math"]["typeset_at_export"] is True
    assert payload["math"]["expressions"] >= 2


def test_the_preview_never_ships_the_two_megabyte_mathjax_bundle(tmp_path: Path) -> None:
    payload = _payload(tmp_path)
    serialized = repr(payload)
    assert "MathJax" not in serialized


def test_build_html_still_produces_what_it_always_did(tmp_path: Path) -> None:
    # compose_document was extracted out of build_html; the exporter's own
    # output must be unchanged by that refactor.
    options = _options(tmp_path, cover=True, toc=True)
    result = render_markdown_text(DOCUMENT, source_path=options.input_path, toc=True)
    document = build_html(result, options)
    composed = compose_document(result, options)
    assert composed.cover_html in document
    assert composed.content_html in document
    assert composed.style_css in document
    assert document.startswith("<!doctype html>")
    assert f'dir="{composed.document_direction}"' in document


def test_the_engine_service_exposes_the_page_preview(tmp_path: Path) -> None:
    source = tmp_path / "doc.md"
    source.write_text(DOCUMENT, encoding="utf-8")
    service = EngineService()
    assert "preview.document_page" in service.capabilities()["methods"]
    payload = service.dispatch(
        "preview.document_page",
        {
            "input_path": str(source),
            "content": DOCUMENT,
            "discover_config": False,
            "options": {"cover": True, "page_size": "Letter"},
        },
    )
    assert payload["page"]["width_mm"] == pytest.approx(215.9)
    assert payload["cover"] is not None
    assert payload["document"]["outline"]
    assert payload["diagnostics"] == []


def test_a_document_that_cannot_publish_fails_the_page_preview(tmp_path: Path) -> None:
    # A preview that renders a document the exporter would refuse is worse than
    # no preview: it promises an output that will never exist.
    source = tmp_path / "doc.md"
    source.write_text("# ok\n", encoding="utf-8")
    options = PdfOptions(
        input_path=source,
        output_path=tmp_path / "doc.pdf",
        citations_enabled=True,
    )
    with pytest.raises(application.EngineValidationError):
        application.preview_page_document_text(options, "See [@missing-key].\n")

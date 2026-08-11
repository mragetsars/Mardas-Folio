from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject

from mardas_folio.markdown import render_markdown
from mardas_folio.renderer import (
    _copy_pdf_with_metadata,
    _heading_destination_names,
)


def test_toc_links_and_headings_share_stable_ids() -> None:
    result = render_markdown(
        """# Intro\n\n## Duplicate\n\n## Duplicate\n\n# فارسی عنوان\n""",
        toc=True,
    )

    assert 'href="#intro"' in result.toc_html
    assert 'id="intro"' in result.body_html
    assert 'href="#duplicate"' in result.toc_html
    assert 'id="duplicate"' in result.body_html
    assert 'href="#duplicate-2"' in result.toc_html
    assert 'id="duplicate-2"' in result.body_html
    assert 'href="#فارسی-عنوان"' in result.toc_html
    assert 'id="فارسی-عنوان"' in result.body_html


def test_heading_destination_names_cover_chromium_encoded_ids() -> None:
    names = _heading_destination_names("فارسی-عنوان")

    assert "/فارسی-عنوان" in names
    assert "/%D9%81%D8%A7%D8%B1%D8%B3%DB%8C-%D8%B9%D9%86%D9%88%D8%A7%D9%86" in names


def test_metadata_copy_preserves_named_destinations_for_toc_links(tmp_path: Path) -> None:
    source_pdf = tmp_path / "source.pdf"
    output_pdf = tmp_path / "output.pdf"

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_named_destination("/intro", 0)
    with source_pdf.open("wb") as handle:
        writer.write(handle)

    _copy_pdf_with_metadata(
        source_pdf,
        output_pdf,
        {"/Title": "TOC destination test"},
        outline_source_entries=[(1, "Intro", "intro")],
    )

    reader = PdfReader(str(output_pdf))
    assert "/intro" in reader.named_destinations
    assert reader.outline[0]["/Title"] == "Intro"
    assert reader.get_destination_page_number(reader.outline[0]) == 0


def test_visible_toc_link_annotations_are_rewritten_to_explicit_destinations(tmp_path: Path) -> None:
    source_pdf = tmp_path / "source-links.pdf"
    output_pdf = tmp_path / "output-links.pdf"

    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.add_named_destination("/intro", 0)
    link_annotation = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Link"),
            NameObject("/Rect"): ArrayObject([FloatObject(20), FloatObject(20), FloatObject(200), FloatObject(42)]),
            NameObject("/Border"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(0)]),
            NameObject("/Dest"): NameObject("/intro"),
        }
    )
    writer.pages[0][NameObject("/Annots")] = ArrayObject([writer._add_object(link_annotation)])
    with source_pdf.open("wb") as handle:
        writer.write(handle)

    _copy_pdf_with_metadata(
        source_pdf,
        output_pdf,
        {"/Title": "Visible TOC annotation test"},
        outline_source_entries=[(1, "Intro", "intro")],
    )

    reader = PdfReader(str(output_pdf))
    annotation = reader.pages[0]["/Annots"][0].get_object()
    destination = annotation["/Dest"]
    assert isinstance(destination, ArrayObject)
    assert str(destination[1]) in {"/Fit", "/XYZ", "/FitH", "/FitBH"}
    assert destination[0].get_object() == reader.pages[0]


def test_navigation_quality_reports_missing_heading_destinations():
    import pytest

    from mardas_folio.pdf_navigation import NavigationTracker, enforce_navigation_quality
    from mardas_folio.quality import PdfNavigationError, RenderQualityLog

    tracker = NavigationTracker(missing_heading_destinations=["missing-heading"])
    log = RenderQualityLog(profile="strict-publication")

    with pytest.raises(PdfNavigationError, match="headings without preserved"):
        enforce_navigation_quality(tracker, log=log, policy="error")
    assert log.payload()["summary"]["error"] == 1

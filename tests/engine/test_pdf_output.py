from __future__ import annotations

import os

import pytest
from pypdf import PdfReader

from mardas_folio.renderer import PdfOptions, convert


def _outline_titles(outline: list[object]) -> list[str]:
    titles: list[str] = []
    for item in outline:
        if isinstance(item, list):
            titles.extend(_outline_titles(item))
        elif hasattr(item, "title"):
            titles.append(str(item.title))
    return titles


@pytest.mark.skipif(
    os.environ.get("MARDAS_RENDER_SMOKE") != "1",
    reason="set MARDAS_RENDER_SMOKE=1 to run Chromium PDF output smoke tests",
)
def test_rendered_pdf_contains_metadata_and_outline(tmp_path):
    input_path = tmp_path / "outline.md"
    output_path = tmp_path / "outline.pdf"
    input_path.write_text(
        "---\n"
        'title: "Outline Smoke"\n'
        'author: "Mardas Test"\n'
        "keywords:\n"
        "  - outline\n"
        "  - metadata\n"
        "lang: en\n"
        "---\n\n"
        "# First Section\n\n"
        "Some content for the first rendered page.\n\n"
        "## Nested Section\n\n"
        "More content for nested bookmark coverage.\n",
        encoding="utf-8",
    )

    convert(
        PdfOptions(
            input_path=input_path,
            output_path=output_path,
            toc=True,
            cover=True,
            style="github",
            palette="blue",
            mode="light",
            timeout_ms=int(os.environ.get("MARDAS_TIMEOUT_MS", "180000")),
        )
    )

    reader = PdfReader(str(output_path))
    metadata = reader.metadata or {}
    outline_titles = _outline_titles(reader.outline)

    assert output_path.stat().st_size > 0
    assert metadata.get("/Title") == "Outline Smoke"
    assert metadata.get("/Author") == "Mardas Test"
    assert "outline" in str(metadata.get("/Keywords"))
    metadata_stream = reader.trailer["/Root"]["/Metadata"].get_object()
    assert metadata_stream.get("/Type") == "/Metadata"
    assert metadata_stream.get("/Subtype") == "/XML"
    assert "First Section" in outline_titles
    assert "Nested Section" in outline_titles

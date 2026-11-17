from __future__ import annotations

from pathlib import Path

from mardas_folio.mermaid import render_mermaid_to_svg
from mardas_folio.markdown import render_markdown
from mardas_folio.renderer import PdfOptions, build_html


def test_mermaid_edge_labels_use_background_chips_not_stroked_text():
    svg = render_mermaid_to_svg(
        """flowchart LR
        Start((Start)) -->|valid input| Check{Ready?}
        Check -- yes --> Done[PDF exported]
        Check -. no .-> Retry[Retry options]
        """
    )

    assert svg is not None
    assert "md2pdf-mermaid-edge-label-bg" in svg
    assert "md2pdf-mermaid-edge-label-group" in svg
    assert "valid input" in svg




def test_mermaid_edge_labels_use_centered_tspan_and_pipe_labelled_dotted_edges():
    svg = render_mermaid_to_svg(
        """flowchart LR
        Start((Start)) -->|valid input| Check{Ready?}
        Check -.->|no| Retry[Retry options]
        """
    )

    assert svg is not None
    assert 'Retry options' in svg
    assert '>no<' in svg
    assert 'class="md2pdf-mermaid-edge md2pdf-mermaid-edge-dotted"' in svg
    assert 'class="md2pdf-mermaid-edge-label"' in svg
    assert 'dy="0.35em"' in svg


def test_renderer_mermaid_label_css_avoids_pdf_text_extraction_duplicates(tmp_path: Path):
    result = render_markdown(
        """```mermaid
flowchart LR
  A[Start] -->|valid input| B{Ready?}
```
"""
    )
    html = build_html(
        result,
        PdfOptions(input_path=tmp_path / "in.md", output_path=tmp_path / "out.pdf"),
        include_mathjax=False,
    )
    label_css = html[html.find(".md2pdf-mermaid-edge-label") : html.find(".md2pdf-page-break")]

    assert ".md2pdf-mermaid-edge-label-bg" in html
    assert "paint-order: stroke" not in label_css
    assert "stroke-width: 4px" not in label_css


def test_guide_markdown_uses_document_local_media_assets_when_available():
    en = Path("docs/guides/GUIDE.en.md")
    fa = Path("docs/guides/GUIDE.fa.md")
    if not en.exists() or not fa.exists():
        return

    combined = en.read_text(encoding="utf-8") + "\n" + fa.read_text(encoding="utf-8")

    assert "README.png" not in combined
    assert "images/architecture.png" in combined
    assert "images/architecture.svg" not in combined
    assert not Path("docs/guides/images/logo.svg").exists()
    assert "images/logo.svg" not in combined

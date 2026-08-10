from __future__ import annotations

import json
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from mardas_md2pdf.cli import main
from mardas_md2pdf.pdf_audit import audit_pdf
from mardas_md2pdf.renderer import _copy_pdf_with_metadata


def _blank_pdf(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with path.open("wb") as handle:
        writer.write(handle)
    writer.close()


def test_pdf_audit_reports_missing_readiness_signals(tmp_path: Path) -> None:
    path = tmp_path / "plain.pdf"
    _blank_pdf(path)
    result = audit_pdf(path)
    codes = {item.code for item in result.diagnostics}
    assert "MARDAS-P811" in codes
    assert "MARDAS-P812" in codes
    assert "MARDAS-P821" in codes
    assert result.metrics["tagged"] is False
    assert result.metrics["compliance_claims"]["pdfa"] is False


def test_pdf_postprocessing_adds_language_title_viewer_preference_and_xmp(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "output.pdf"
    _blank_pdf(source)
    _copy_pdf_with_metadata(
        source,
        output,
        {
            "/Title": "Accessible Report",
            "/Author": "Author",
            "/Creator": "Mardas Folio",
            "/Producer": "Mardas Folio",
            "/CreationDate": "D:20260711120000Z",
            "/ModDate": "D:20260711120000Z",
        },
        page_label_lang="fa-IR",
    )
    reader = PdfReader(str(output))
    assert reader.root_object["/Lang"] == "fa-ir"
    assert bool(reader.root_object["/ViewerPreferences"]["/DisplayDocTitle"])
    assert reader.metadata["/Title"] == "Accessible Report"
    assert reader.root_object.get("/Metadata") is not None

    audit = audit_pdf(output)
    assert audit.metrics["language"] == "fa-ir"
    assert audit.metrics["xmp_metadata"] is True
    assert {item.code for item in audit.diagnostics}.isdisjoint({"MARDAS-P811", "MARDAS-P821"})
    assert "MARDAS-P812" in {item.code for item in audit.diagnostics}


def test_audit_pdf_cli_json_and_warning_policy(tmp_path: Path, capsys) -> None:
    path = tmp_path / "plain.pdf"
    _blank_pdf(path)
    assert main(["audit-pdf", str(path), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "audit-pdf"
    assert payload["metrics"]["pages"] == 1
    assert payload["metrics"]["compliance_claims"]["pdfua"] is False
    assert main(["audit-pdf", str(path), "--fail-on", "warning"]) == 1

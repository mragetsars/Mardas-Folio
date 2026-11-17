from __future__ import annotations

import json
from pathlib import Path

from bs4 import BeautifulSoup

from mardas_folio.accessibility import (
    appearance_contrast_metrics,
    audit_markdown_result,
)
from mardas_folio.appearance import MODES, PALETTES_ORDER, STYLES, resolve_appearance
from mardas_folio.cli import main
from mardas_folio.markdown import render_markdown, render_markdown_file


def test_accessibility_audit_reports_source_and_semantic_problems(tmp_path: Path) -> None:
    path = tmp_path / "bad.md"
    path.write_text(
        "# Title\n\n### Skipped\n\n![](image.png)\n\n[click here](https://example.com)\n\n"
        "<img src=\"x.png\">\n\n<table><tr><td>value</td></tr></table>\n",
        encoding="utf-8",
    )
    result = render_markdown_file(path)
    audit = audit_markdown_result(
        path=path,
        markdown=path.read_text(encoding="utf-8"),
        result=result,
        appearance=resolve_appearance(),
    )
    by_code = {item.code: item for item in audit.diagnostics}
    assert by_code["MARDAS-A001"].severity == "warning"
    assert by_code["MARDAS-A101"].line == 3
    assert by_code["MARDAS-A201"].line == 5
    assert by_code["MARDAS-A302"].line == 7
    assert by_code["MARDAS-A204"].line == 9
    assert by_code["MARDAS-A401"].severity == "error"


def test_accessibility_semantics_add_table_scopes_and_caption_associations() -> None:
    result = render_markdown(
        "---\nlang: en-US\n---\n# Report\n\n"
        "![Architecture](diagram.png)\n\n*Figure. System architecture.*\n\n"
        "| Name | Value |\n| --- | --- |\n| Alpha | 1 |\n\nTable: Metrics\n"
    )
    soup = BeautifulSoup(result.body_html, "html.parser")
    figure = soup.find("figure", class_="md2pdf-figure")
    assert figure is not None
    caption = figure.find("figcaption", recursive=False)
    assert caption is not None
    assert figure.get("role") == "group"
    assert figure.get("aria-labelledby") == caption.get("id")

    table = soup.find("table")
    assert table is not None
    table_caption = table.find("caption", recursive=False)
    assert table_caption is not None
    assert table.get("aria-describedby") == table_caption.get("id")
    assert {header.get("scope") for header in table.find_all("th")} == {"col"}


def test_all_bundled_palette_link_accents_meet_ordinary_text_contrast() -> None:
    for style in STYLES:
        for palette in PALETTES_ORDER:
            for mode in MODES:
                metrics = appearance_contrast_metrics(
                    resolve_appearance(style=style, palette=palette, mode=mode)
                )
                assert float(metrics["accent_contrast"]) >= 4.5, (style, palette, mode, metrics)


def test_project_language_overrides_front_matter_and_reaches_html(tmp_path: Path) -> None:
    path = tmp_path / "document.md"
    path.write_text("---\nlang: en\n---\n# عنوان\n", encoding="utf-8")
    result = render_markdown_file(path, language="fa-IR")
    assert result.metadata["lang"] == "fa-ir"


def test_audit_accessibility_cli_json_and_fail_on_warning(tmp_path: Path, capsys) -> None:
    path = tmp_path / "document.md"
    path.write_text("# Title\n\n[click here](https://example.com)\n", encoding="utf-8")
    assert main(["audit-accessibility", str(path), "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "audit-accessibility"
    assert payload["summary"]["warning"] >= 1
    assert payload["compliance_claims"]["pdfua"] is False
    assert main(["audit-accessibility", str(path), "--fail-on", "warning"]) == 1


def test_audit_book_accessibility_reports_chapter_paths(tmp_path: Path, capsys) -> None:
    (tmp_path / "chapters").mkdir()
    (tmp_path / "chapters" / "one.md").write_text(
        "---\nlang: en\n---\n# One\n\nGood text.\n", encoding="utf-8"
    )
    (tmp_path / "chapters" / "two.md").write_text(
        "# Two\n\n![](missing.png)\n", encoding="utf-8"
    )
    (tmp_path / "mardas.toml").write_text(
        'schema_version = 1\n[project]\nlanguage = "en-US"\n[book]\nchapters = ["chapters/one.md", "chapters/two.md"]\noutput = "dist/book.pdf"\n',
        encoding="utf-8",
    )
    code = main(["audit-book-accessibility", str(tmp_path), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["command"] == "audit-book-accessibility"
    assert [item["path"] for item in payload["files"]] == ["chapters/one.md", "chapters/two.md"]
    assert payload["summary"]["warning"] >= 1


def test_accessibility_audit_ignores_literal_inline_code_and_code_layout_tables(
    tmp_path: Path,
) -> None:
    path = tmp_path / "literal.md"
    path.write_text(
        "---\nlang: en-US\n---\n# Literal examples\n\n"
        "The sanitizer supports `<img>` and `<table>` elements.\n\n"
        "```python linenos\nprint('accessible code')\n```\n",
        encoding="utf-8",
    )
    result = render_markdown_file(path)
    audit = audit_markdown_result(
        path=path,
        markdown=path.read_text(encoding="utf-8"),
        result=result,
        appearance=resolve_appearance(),
    )
    codes = {item.code for item in audit.diagnostics}
    assert "MARDAS-A204" not in codes
    assert "MARDAS-A401" not in codes
    assert "MARDAS-A402" not in codes

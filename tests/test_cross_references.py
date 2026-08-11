from __future__ import annotations

import json
from pathlib import Path

from bs4 import BeautifulSoup

from mardas_folio.book import load_book_manifest, render_book
from mardas_folio.cli import main
from mardas_folio.config import load_project_config
from mardas_folio.markdown import render_markdown


def _diagnostic_codes(result) -> list[str]:
    return [item.code for item in result.diagnostics]


def test_numbering_resolves_all_supported_object_kinds() -> None:
    markdown = """---
lang: en
references:
  enabled: true
---
See @fig:architecture, @tbl:results, @eq:energy, and @lst:training.

![Architecture](architecture.png)

*Figure. System architecture.* {#fig:architecture}

| Metric | Value |
| --- | ---: |
| Accuracy | 0.98 |

Table: Evaluation results {#tbl:results}

$$
E = mc^2
$$

{#eq:energy}

```python title="Training loop" {#lst:training}
print("train")
```
"""

    result = render_markdown(markdown)

    assert not result.diagnostics
    assert [(item["kind"], item["number"]) for item in result.reference_objects] == [
        ("fig", "1"),
        ("tbl", "1"),
        ("eq", "1"),
        ("lst", "1"),
    ]
    soup = BeautifulSoup(result.body_html, "html.parser")
    assert soup.select_one('a[data-md2pdf-reference="fig:architecture"]').get_text(strip=True) == "Figure 1"
    assert soup.select_one('a[data-md2pdf-reference="tbl:results"]').get_text(strip=True) == "Table 1"
    assert soup.select_one('a[data-md2pdf-reference="eq:energy"]').get_text(strip=True) == "Equation 1"
    assert soup.select_one('a[data-md2pdf-reference="lst:training"]').get_text(strip=True) == "Listing 1"
    assert soup.select_one('#xref-fig-architecture .md2pdf-caption-label').get_text(strip=True) == "Figure 1"
    assert soup.select_one('#xref-tbl-results .md2pdf-caption-label').get_text(strip=True) == "Table 1"
    assert soup.select_one('#xref-eq-energy .md2pdf-equation-number').get_text(strip=True) == "(1)"
    assert soup.select_one('#xref-lst-training .md2pdf-caption-label').get_text(strip=True) == "Listing 1"


def test_persian_references_use_localized_labels_and_digits() -> None:
    result = render_markdown(
        """---
lang: fa
references: true
---
# آزمایش

مطابق @fig:model نتیجه مشخص است.

![مدل](model.png)

شکل: مدل پیشنهادی {#fig:model}
"""
    )

    assert not result.diagnostics
    soup = BeautifulSoup(result.body_html, "html.parser")
    assert soup.select_one('a[data-md2pdf-reference="fig:model"]').get_text(strip=True) == "شکل ۱"
    assert soup.select_one('.md2pdf-caption-label').get_text(strip=True) == "شکل ۱"


def test_reference_token_does_not_consume_sentence_punctuation() -> None:
    result = render_markdown(
        """---
references: true
---
See @lst:code.

```python {#lst:code}
print(1)
```
"""
    )

    assert not result.diagnostics
    assert "Listing 1</a>." in result.body_html


def test_duplicate_label_is_reported() -> None:
    result = render_markdown(
        """---
references: true
---
![One](one.png)

Figure: One {#fig:same}

![Two](two.png)

Figure: Two {#fig:same}
"""
    )

    assert "MARDAS-E601" in _diagnostic_codes(result)


def test_unresolved_reference_is_reported_and_marked() -> None:
    result = render_markdown(
        """---
references: true
---
See @fig:missing.
"""
    )

    assert _diagnostic_codes(result) == ["MARDAS-E602"]
    assert "md2pdf-xref--unresolved" in result.body_html


def test_label_kind_must_match_attached_object() -> None:
    result = render_markdown(
        """---
references: true
---
![Image](image.png)

Figure: Image {#tbl:not-a-table}
"""
    )

    assert _diagnostic_codes(result) == ["MARDAS-E603"]


def test_unattached_standalone_label_produces_warning() -> None:
    result = render_markdown(
        """---
references: true
---
Paragraph.

{#fig:orphan}
"""
    )

    assert _diagnostic_codes(result) == ["MARDAS-W603"]
    assert "{#fig:orphan}" in result.body_html


def test_reference_markup_inside_code_is_not_transformed() -> None:
    result = render_markdown(
        """---
references: true
---
```text
@fig:not-a-reference
```
"""
    )

    assert not result.diagnostics
    assert "@fig:not-a-reference" in result.body_html
    assert "data-md2pdf-reference" not in result.body_html


def test_lists_are_generated_only_for_requested_kinds() -> None:
    result = render_markdown(
        """---
lang: en
references:
  enabled: true
  list_of_figures: true
  list_of_tables: true
---
![A](a.png)

Figure: Alpha {#fig:a}

| A |
|---|
| 1 |

Table: Beta {#tbl:b}
"""
    )

    assert "List of Figures" in result.reference_lists_html
    assert "List of Tables" in result.reference_lists_html
    assert "List of Equations" not in result.reference_lists_html
    assert 'href="#xref-fig-a"' in result.reference_lists_html
    assert 'href="#xref-tbl-b"' in result.reference_lists_html


def test_references_are_opt_in_and_legacy_output_is_preserved() -> None:
    result = render_markdown(
        """See @fig:legacy.

![Legacy](legacy.png)

Figure: Legacy {#fig:legacy}
"""
    )

    assert not result.diagnostics
    assert not result.reference_objects
    assert "@fig:legacy" in result.body_html
    assert "{#fig:legacy}" in result.body_html


def _write_reference_book(root: Path, *, duplicate: bool = False) -> Path:
    chapters = root / "chapters"
    chapters.mkdir(parents=True)
    (chapters / "01-first.md").write_text(
        """---
lang: en
---
# First

See @fig:second-model.

![First](first.png)

Figure: First model {#fig:first-model}
""",
        encoding="utf-8",
    )
    second_label = "fig:first-model" if duplicate else "fig:second-model"
    (chapters / "02-second.md").write_text(
        f"""---
lang: en
---
# Second

![Second](second.png)

Figure: Second model {{#{second_label}}}
""",
        encoding="utf-8",
    )
    config = root / "mardas.toml"
    config.write_text(
        """schema_version = 1
[project]
title = "Reference Book"

[references]
enabled = true
numbering_scope = "chapter"
list_of_figures = true

[book]
chapters = ["chapters/01-first.md", "chapters/02-second.md"]
output = "dist/book.pdf"
""",
        encoding="utf-8",
    )
    return config


def test_book_resolves_cross_chapter_reference_with_chapter_numbering(tmp_path: Path) -> None:
    config_path = _write_reference_book(tmp_path)
    config = load_project_config(start=tmp_path, explicit_path=config_path).config
    manifest, manifest_diagnostics = load_book_manifest(config)
    assert manifest is not None and not manifest_diagnostics

    bundle, diagnostics = render_book(manifest)

    assert bundle is not None
    assert not diagnostics
    assert [(item["label"], item["number"]) for item in bundle.result.reference_objects] == [
        ("fig:first-model", "1.1"),
        ("fig:second-model", "2.1"),
    ]
    assert "Figure 2.1" in bundle.result.body_html
    assert "List of Figures" in bundle.result.reference_lists_html


def test_book_rejects_duplicate_label_across_chapters(tmp_path: Path) -> None:
    config_path = _write_reference_book(tmp_path, duplicate=True)
    config = load_project_config(start=tmp_path, explicit_path=config_path).config
    manifest, _ = load_book_manifest(config)
    assert manifest is not None

    bundle, diagnostics = render_book(manifest)

    assert bundle is None
    assert "MARDAS-E601" in [item.code for item in diagnostics]


def test_validate_json_reports_reference_diagnostics(tmp_path: Path, capsys) -> None:
    document = tmp_path / "document.md"
    document.write_text("# Test\n\nSee @fig:missing.\n", encoding="utf-8")
    (tmp_path / "mardas.toml").write_text(
        "schema_version = 1\n[references]\nenabled = true\n",
        encoding="utf-8",
    )

    assert main(["validate", str(document), "--format", "json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["document"]["numbered_objects"] == 0
    assert "MARDAS-E602" in [item["code"] for item in payload["diagnostics"]]


def test_cli_no_references_overrides_project_configuration(
    tmp_path: Path, monkeypatch
) -> None:
    document = tmp_path / "document.md"
    document.write_text("# Test\n\nSee @fig:missing.\n", encoding="utf-8")
    (tmp_path / "mardas.toml").write_text(
        "schema_version = 1\n[references]\nenabled = true\n",
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def fake_convert(options):
        captured["references_enabled"] = options.references_enabled
        options.output_path.write_bytes(b"%PDF-1.7\n")
        return options.output_path

    monkeypatch.setattr("mardas_folio.cli.convert", fake_convert)

    assert main([str(document), "--no-references", "--progress", "off"]) == 0
    assert captured["references_enabled"] is False


def test_raw_html_can_define_safe_reference_label() -> None:
    result = render_markdown(
        """---
references: true
---
See @fig:raw.

<figure data-md2pdf-label="fig:raw"><img alt="Raw"><figcaption>Raw figure</figcaption></figure>
"""
    )

    assert not result.diagnostics
    assert result.reference_objects[0]["label"] == "fig:raw"
    assert "Figure 1" in result.body_html


def test_mixed_language_book_localizes_each_reference_in_its_chapter(tmp_path: Path) -> None:
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "01-fa.md").write_text(
        """---
lang: fa
---
# فارسی

مطابق @fig:shared نتیجه روشن است.
""",
        encoding="utf-8",
    )
    (chapters / "02-en.md").write_text(
        """---
lang: en
---
# English

See @fig:shared.

![Shared](shared.png)

Figure: Shared model {#fig:shared}
""",
        encoding="utf-8",
    )
    config_path = tmp_path / "mardas.toml"
    config_path.write_text(
        """schema_version = 1
[references]
enabled = true
[book]
chapters = ["chapters/01-fa.md", "chapters/02-en.md"]
""",
        encoding="utf-8",
    )
    config = load_project_config(start=tmp_path, explicit_path=config_path).config
    manifest, _ = load_book_manifest(config)
    assert manifest is not None

    bundle, diagnostics = render_book(manifest)

    assert bundle is not None and not diagnostics
    soup = BeautifulSoup(bundle.result.body_html, "html.parser")
    references = soup.select('a[data-md2pdf-reference="fig:shared"]')
    assert [item.get_text(strip=True) for item in references] == ["شکل ۱", "Figure 1"]
    assert soup.select_one('[data-md2pdf-label="fig:shared"] .md2pdf-caption-label').get_text(strip=True) == "Figure 1"


def test_standalone_figure_label_uses_image_alt_as_caption() -> None:
    result = render_markdown(
        """---
references: true
---
![Architecture overview](architecture.png)

{#fig:architecture}
"""
    )

    assert not result.diagnostics
    assert result.reference_objects[0]["caption"] == "Architecture overview"
    assert "Figure 1" in result.body_html


def test_standalone_table_label_is_attached_before_table_wrapping() -> None:
    result = render_markdown(
        """---
references: true
---
| A |
|---|
| 1 |

{#tbl:data}
"""
    )

    assert not result.diagnostics
    assert result.reference_objects[0]["label"] == "tbl:data"
    assert 'class="md2pdf-caption-label">Table 1' in result.body_html


def test_project_config_loads_reference_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "mardas.toml"
    config_path.write_text(
        """schema_version = 1
[references]
enabled = true
numbering_scope = "chapter"
list_of_figures = true
list_of_tables = true
list_of_equations = true
list_of_listings = true
""",
        encoding="utf-8",
    )

    loaded = load_project_config(start=tmp_path, explicit_path=config_path)

    assert not loaded.diagnostics
    assert loaded.config.values["references_enabled"] is True
    assert loaded.config.values["numbering_scope"] == "chapter"
    assert loaded.config.values["list_of_figures"] is True
    assert loaded.config.values["list_of_listings"] is True


def test_explain_config_reports_front_matter_reference_sources(tmp_path: Path, capsys) -> None:
    document = tmp_path / "document.md"
    document.write_text(
        """---
references:
  enabled: true
  numbering_scope: global
  list_of_figures: true
---
# Document
""",
        encoding="utf-8",
    )

    assert main(["explain-config", str(document), "--no-config", "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["effective"]["references_enabled"] == {
        "source": "front matter",
        "value": True,
    }
    assert payload["effective"]["list_of_figures"]["source"] == "front matter"


def test_single_file_conversion_rejects_unresolved_reference_before_browser(tmp_path: Path) -> None:
    from mardas_folio.markdown import MarkdownInputError
    from mardas_folio.renderer import PdfOptions, convert

    source = tmp_path / "document.md"
    source.write_text("See @fig:missing.\n", encoding="utf-8")

    try:
        convert(
            PdfOptions(
                input_path=source,
                output_path=tmp_path / "document.pdf",
                references_enabled=True,
            )
        )
    except MarkdownInputError as exc:
        assert "MARDAS-E602" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("Conversion should fail before Chromium starts")


def test_inline_code_label_marker_remains_literal() -> None:
    result = render_markdown(
        """---
references: true
---
![Architecture](architecture.png)

`{#fig:architecture}`
"""
    )

    assert not result.diagnostics
    assert not result.reference_objects
    assert "{#fig:architecture}" in result.body_html
    assert "<code" in result.body_html


def test_label_marker_inside_caption_code_remains_literal() -> None:
    result = render_markdown(
        """---
references: true
---
![Architecture](architecture.png)

Figure: literal `{#fig:architecture}`
"""
    )

    assert not result.diagnostics
    assert not result.reference_objects
    assert "{#fig:architecture}" in result.body_html


def test_invalid_label_marker_reports_structured_error() -> None:
    result = render_markdown(
        """---
references: true
---
![Architecture](architecture.png)

Figure: Architecture {#fig:bad label}
"""
    )

    assert _diagnostic_codes(result) == ["MARDAS-E605"]
    assert "{#fig:bad label}" in result.body_html


def test_semantic_target_does_not_reuse_author_supplied_object_id() -> None:
    result = render_markdown(
        """---
references: true
---
See @fig:model.

<figure id="legacy-model" data-md2pdf-label="fig:model"><figcaption>Model</figcaption></figure>
"""
    )

    soup = BeautifulSoup(result.body_html, "html.parser")
    assert not result.diagnostics
    assert result.reference_objects[0]["target_id"] == "xref-fig-model"
    assert soup.select_one('#xref-fig-model[data-md2pdf-label="fig:model"]') is not None
    assert soup.select_one('span#legacy-model.md2pdf-reference-target') is not None
    assert soup.select_one('a[data-md2pdf-reference="fig:model"]')["href"] == "#xref-fig-model"


def test_duplicate_raw_ids_cannot_merge_semantic_destinations() -> None:
    result = render_markdown(
        """---
references: true
---
See @fig:first and @fig:second.

<figure id="same" data-md2pdf-label="fig:first"><figcaption>First</figcaption></figure>
<figure id="same" data-md2pdf-label="fig:second"><figcaption>Second</figcaption></figure>
"""
    )

    soup = BeautifulSoup(result.body_html, "html.parser")
    assert not result.diagnostics
    assert [item["target_id"] for item in result.reference_objects] == [
        "xref-fig-first",
        "xref-fig-second",
    ]
    assert soup.select_one('a[data-md2pdf-reference="fig:first"]')["href"] == "#xref-fig-first"
    assert soup.select_one('a[data-md2pdf-reference="fig:second"]')["href"] == "#xref-fig-second"
    assert not soup.select("#same")


def test_semantic_target_uses_deterministic_suffix_when_xref_id_is_reserved() -> None:
    result = render_markdown(
        """---
references: true
---
<div id="xref-fig-model">Reserved</div>

See @fig:model.

![Model](model.png)

Figure: Model {#fig:model}
"""
    )

    assert not result.diagnostics
    assert result.reference_objects[0]["target_id"] == "xref-fig-model-2"
    assert 'href="#xref-fig-model-2"' in result.body_html


def test_raw_label_on_unsupported_element_is_rejected() -> None:
    result = render_markdown(
        """---
references: true
---
<div data-md2pdf-label="fig:not-a-figure">Not a figure</div>
"""
    )

    assert _diagnostic_codes(result) == ["MARDAS-E605"]
    assert not result.reference_objects


def test_invalid_code_fence_label_reports_structured_error() -> None:
    result = render_markdown(
        """---
references: true
---
```python {#lst:bad-}
print(1)
```
"""
    )

    assert _diagnostic_codes(result) == ["MARDAS-E605"]
    assert not result.reference_objects


def test_invalid_code_fence_label_is_ignored_when_references_are_disabled() -> None:
    result = render_markdown(
        """```python {#lst:bad-}
print(1)
```
"""
    )

    assert not result.diagnostics
    assert not result.reference_objects


def test_multiple_code_fence_labels_are_rejected() -> None:
    result = render_markdown(
        """---
references: true
---
```python {#lst:first} {#lst:second}
print(1)
```
"""
    )

    assert "MARDAS-E604" in _diagnostic_codes(result)

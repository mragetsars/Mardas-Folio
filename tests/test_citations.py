from __future__ import annotations

import json
from pathlib import Path

from bs4 import BeautifulSoup

from mardas_folio.citations import (
    BibliographyLibrary,
    CitationOptions,
    annotate_citation_markup,
    load_bibliography,
    resolve_citations,
)
from mardas_folio.markdown import render_markdown_file


def _write_bib(path: Path) -> Path:
    path.write_text(
        """
@article{doe2024,
  author = {Doe, Jane and Smith, John},
  title = {Deterministic Publishing},
  year = {2024},
  journal = {Journal of Reproducible Documents},
  volume = {8},
  number = {2},
  pages = {10--24},
  doi = {10.1000/example}
}
@book{ahmadi1403,
  author = {احمدی، مریم},
  title = {انتشار علمی فارسی},
  year = {1403},
  publisher = {انتشارات پژوهش}
}
""".strip(),
        encoding="utf-8",
    )
    return path


def test_load_bibtex_and_resolve_author_date_citations(tmp_path: Path) -> None:
    library, diagnostics = load_bibliography([_write_bib(tmp_path / "references.bib")])
    assert not diagnostics
    assert set(library.entries) == {"doe2024", "ahmadi1403"}
    assert library.entries["doe2024"].authors[0].family == "Doe"

    annotated, annotation_diagnostics = annotate_citation_markup(
        "<p>Prior work [@doe2024, p. 12] and @ahmadi1403 are relevant.</p>",
    )
    assert not annotation_diagnostics
    result = resolve_citations(
        annotated,
        library=library,
        options=CitationOptions(enabled=True, style="author-date"),
        lang="en",
    )
    assert not result.diagnostics
    soup = BeautifulSoup(result.body_html, "html.parser")
    assert "Doe & Smith, 2024, p. 12" in soup.get_text(" ", strip=True)
    assert "احمدی (1403)" in soup.get_text(" ", strip=True)
    assert result.cited_keys == ("doe2024", "ahmadi1403")
    bibliography = BeautifulSoup(result.bibliography_html, "html.parser")
    assert bibliography.select_one("#bibliography")
    assert len(bibliography.select(".md2pdf-bibliography-entry")) == 2
    assert bibliography.select_one('[data-md2pdf-bibliography-key="doe2024"]')


def test_numeric_citations_follow_first_use_order(tmp_path: Path) -> None:
    library, diagnostics = load_bibliography([_write_bib(tmp_path / "references.bib")])
    assert not diagnostics
    annotated, _ = annotate_citation_markup(
        "<p>First [@ahmadi1403], then [@doe2024; @ahmadi1403].</p>",
    )
    result = resolve_citations(
        annotated,
        library=library,
        options=CitationOptions(enabled=True, style="numeric"),
        lang="en",
    )
    soup = BeautifulSoup(result.body_html, "html.parser")
    groups = soup.select(".md2pdf-citation--parenthetical")
    assert groups[0].get_text("", strip=True) == "[1]"
    assert groups[1].get_text("", strip=True) == "[2,1]"
    assert ", " in str(groups[1])
    bibliography = BeautifulSoup(result.bibliography_html, "html.parser")
    entries = bibliography.select(".md2pdf-bibliography-entry")
    assert entries[0]["data-md2pdf-bibliography-key"] == "ahmadi1403"
    assert entries[1]["data-md2pdf-bibliography-key"] == "doe2024"


def test_load_csl_json_and_include_uncited(tmp_path: Path) -> None:
    path = tmp_path / "references.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "smith2022",
                    "type": "article-journal",
                    "title": "Structured Citations",
                    "author": [{"family": "Smith", "given": "Alex"}],
                    "issued": {"date-parts": [[2022]]},
                    "container-title": "Publishing Systems",
                },
                {
                    "id": "zeta2020",
                    "type": "book",
                    "title": "Uncited Work",
                    "author": [{"family": "Zeta", "given": "Zoe"}],
                    "issued": {"date-parts": [[2020]]},
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    library, diagnostics = load_bibliography([path])
    assert not diagnostics
    annotated, _ = annotate_citation_markup("<p>See [@smith2022].</p>")
    result = resolve_citations(
        annotated,
        library=library,
        options=CitationOptions(enabled=True, include_uncited=True),
        lang="en",
    )
    assert {item.key for item in result.entries} == {"smith2022", "zeta2020"}


def test_duplicate_and_missing_keys_report_stable_diagnostics(tmp_path: Path) -> None:
    first = tmp_path / "first.bib"
    second = tmp_path / "second.bib"
    first.write_text("@book{dup, title={First}, year={2020}}", encoding="utf-8")
    second.write_text("@book{dup, title={Second}, year={2021}}", encoding="utf-8")
    library, diagnostics = load_bibliography([first, second])
    assert any(item.code == "MARDAS-E703" for item in diagnostics)

    annotated, _ = annotate_citation_markup("<p>See [@missing].</p>")
    result = resolve_citations(
        annotated,
        library=library,
        options=CitationOptions(enabled=True),
    )
    assert any(item.code == "MARDAS-E704" for item in result.diagnostics)


def test_malformed_citation_and_literal_contexts() -> None:
    annotated, diagnostics = annotate_citation_markup(
        "<p>Bad [@key locator].</p><pre><code>[@key]</code></pre>"
    )
    assert any(item.code == "MARDAS-E705" for item in diagnostics)
    soup = BeautifulSoup(annotated, "html.parser")
    assert soup.code.get_text() == "[@key]"
    assert not soup.code.select_one(".md2pdf-citation")


def test_render_markdown_file_uses_frontmatter_bibliography(tmp_path: Path) -> None:
    _write_bib(tmp_path / "references.bib")
    document = tmp_path / "document.md"
    document.write_text(
        """---
title: Citation Test
lang: en
bibliography: references.bib
citations:
  enabled: true
  style: author-date
---

# Citation Test

Evidence [@doe2024].
""",
        encoding="utf-8",
    )
    result = render_markdown_file(document, document_root=tmp_path)
    assert not [item for item in result.diagnostics if item.severity == "error"]
    assert result.cited_keys == ("doe2024",)
    assert "md2pdf-bibliography" in result.bibliography_html
    assert "Doe & Smith, 2024" in BeautifulSoup(result.body_html, "html.parser").get_text(" ")


def test_unknown_narrative_citation_is_diagnosed() -> None:
    annotated, diagnostics = annotate_citation_markup("<p>See @missing for details.</p>")
    assert not diagnostics
    result = resolve_citations(
        annotated,
        library=BibliographyLibrary({}),
        options=CitationOptions(enabled=True),
    )
    assert [item.code for item in result.diagnostics] == ["MARDAS-E704"]


def test_bibtex_unicode_normalization_and_literal_organization(tmp_path: Path) -> None:
    path = tmp_path / "latex.bib"
    path.write_text(
        r"""@book{latex2024,
  author = {Garc{\'i}a, Jos{\'e} and {Research and Development Group}},
  title = {An {\"o}pen and \emph{reproducible} system},
  year = {2024}
}""",
        encoding="utf-8",
    )
    library, diagnostics = load_bibliography([path])
    assert not diagnostics
    entry = library.entries["latex2024"]
    assert entry.authors[0].family == "García"
    assert entry.authors[0].given == "José"
    assert entry.authors[1].literal == "Research and Development Group"
    assert entry.title == "An öpen and reproducible system"


def test_numeric_include_uncited_assigns_deterministic_numbers(tmp_path: Path) -> None:
    library, diagnostics = load_bibliography([_write_bib(tmp_path / "references.bib")])
    assert not diagnostics
    annotated, _ = annotate_citation_markup("<p>See [@doe2024].</p>")
    result = resolve_citations(
        annotated,
        library=library,
        options=CitationOptions(enabled=True, style="numeric", include_uncited=True),
        lang="en",
    )
    bibliography = BeautifulSoup(result.bibliography_html, "html.parser")
    numbers = [item.get_text("", strip=True) for item in bibliography.select(".md2pdf-bib-number")]
    assert numbers == ["[1]", "[2]"]


def test_author_date_disambiguates_same_author_and_year(tmp_path: Path) -> None:
    path = tmp_path / "same-year.bib"
    path.write_text(
        """
@article{smith-z,
  author = {Smith, Alex},
  title = {Zeta Study},
  year = {2024}
}
@article{smith-a,
  author = {Smith, Alex},
  title = {Alpha Study},
  year = {2024}
}
""".strip(),
        encoding="utf-8",
    )
    library, diagnostics = load_bibliography([path])
    assert not diagnostics
    annotated, _ = annotate_citation_markup("<p>See [@smith-z; @smith-a].</p>")
    result = resolve_citations(
        annotated,
        library=library,
        options=CitationOptions(enabled=True, style="author-date"),
        lang="en",
    )
    body = BeautifulSoup(result.body_html, "html.parser").get_text(" ", strip=True)
    assert "Smith, 2024b" in body
    assert "Smith, 2024a" in body
    bibliography = BeautifulSoup(result.bibliography_html, "html.parser")
    entries = bibliography.select(".md2pdf-bibliography-entry")
    assert [item["data-md2pdf-bibliography-key"] for item in entries] == [
        "smith-a",
        "smith-z",
    ]
    assert "(2024a)" in entries[0].get_text(" ", strip=True)
    assert "(2024b)" in entries[1].get_text(" ", strip=True)


def test_duplicate_bibliography_source_is_rejected(tmp_path: Path) -> None:
    path = _write_bib(tmp_path / "references.bib")
    library, diagnostics = load_bibliography([path, path])
    assert len(library.entries) == 2
    assert [item.code for item in diagnostics] == ["MARDAS-E701"]
    assert "listed more than once" in diagnostics[0].message


def test_bibliography_source_and_entry_limits_are_enforced(tmp_path: Path, monkeypatch) -> None:
    import mardas_folio.citations as citations

    oversized = tmp_path / "oversized.bib"
    oversized.write_text("@book{x,title={X}}", encoding="utf-8")
    monkeypatch.setattr(citations, "MAX_BIBLIOGRAPHY_SOURCE_BYTES", 8)
    library, diagnostics = citations.load_bibliography([oversized])
    assert not library.entries
    assert [item.code for item in diagnostics] == ["MARDAS-E702"]

    monkeypatch.setattr(citations, "MAX_BIBLIOGRAPHY_SOURCE_BYTES", 1024)
    monkeypatch.setattr(citations, "MAX_BIBLIOGRAPHY_ENTRIES", 1)
    limited = tmp_path / "limited.bib"
    limited.write_text(
        "@book{a,title={A}}\n@book{b,title={B}}",
        encoding="utf-8",
    )
    library, diagnostics = citations.load_bibliography([limited])
    assert set(library.entries) == {"a"}
    assert [item.code for item in diagnostics] == ["MARDAS-E706"]


def test_bibtex_string_macros_and_invalid_csl_json_are_diagnosed(tmp_path: Path) -> None:
    bib = tmp_path / "macros.bib"
    bib.write_text(
        """
@string{journalName = "Journal of Offline Publishing"}
@article{macro2024,
  author = {Doe, Jane},
  title = {Macro Test},
  year = {2024},
  journal = journalName
}
""".strip(),
        encoding="utf-8",
    )
    library, diagnostics = load_bibliography([bib])
    assert not diagnostics
    assert library.entries["macro2024"].container_title == "Journal of Offline Publishing"

    csl = tmp_path / "broken.json"
    csl.write_text('[{"id": "broken"}', encoding="utf-8")
    library, diagnostics = load_bibliography([csl])
    assert not library.entries
    assert [item.code for item in diagnostics] == ["MARDAS-E702"]
    assert diagnostics[0].line == 1

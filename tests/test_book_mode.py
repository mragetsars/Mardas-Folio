from __future__ import annotations

import json
from pathlib import Path

import pytest

from mardas_folio.book import convert_book, load_book_manifest, render_book
from mardas_folio.cli import main
from mardas_folio.config import load_project_config


def _write_book_project(tmp_path: Path, *, chapter_page_break: bool = True) -> Path:
    chapters = tmp_path / "chapters"
    first_dir = chapters / "part-a"
    second_dir = chapters / "part-b"
    first_dir.mkdir(parents=True)
    second_dir.mkdir(parents=True)
    image_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    )
    (first_dir / "pixel.png").write_bytes(image_bytes)
    (second_dir / "pixel.png").write_bytes(image_bytes)
    (first_dir / "01-introduction.md").write_text(
        "# Shared Heading\n\n![First](pixel.png)\n\n## Details\n",
        encoding="utf-8",
    )
    (second_dir / "02-methods.md").write_text(
        "# Shared Heading\n\n![Second](pixel.png)\n\n## Details\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "mardas.toml"
    config_path.write_text(
        f'''schema_version = 1
[project]
title = "Ordered Research Book"
author = "Researcher"
direction = "ltr"

[output]
toc = true
toc_depth = 3
cover = false
header_footer = true
mathjax = false

[book]
chapters = [
  "chapters/part-a/01-introduction.md",
  {{ path = "chapters/part-b/02-methods.md", title = "Methods Override" }},
]
output = "dist/research-book.pdf"
chapter_page_break = {str(chapter_page_break).lower()}
''',
        encoding="utf-8",
    )
    return config_path


def test_book_manifest_preserves_declared_order_and_resolves_paths(tmp_path: Path) -> None:
    config_path = _write_book_project(tmp_path)
    result = load_project_config(start=tmp_path, explicit_path=config_path)

    manifest, diagnostics = load_book_manifest(result.config)

    assert not result.diagnostics
    assert not diagnostics
    assert manifest is not None
    assert [chapter.path.name for chapter in manifest.chapters] == [
        "01-introduction.md",
        "02-methods.md",
    ]
    assert manifest.chapters[1].title_override == "Methods Override"
    assert manifest.output_path == (tmp_path / "dist/research-book.pdf").resolve()
    assert manifest.chapter_page_break is True


def test_book_chapter_must_remain_inside_project_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-book-chapter.md"
    outside.write_text("# Outside\n", encoding="utf-8")
    config_path = tmp_path / "mardas.toml"
    config_path.write_text(
        "schema_version = 1\n[book]\nchapters = ['../outside-book-chapter.md']\n",
        encoding="utf-8",
    )

    result = load_project_config(start=tmp_path, explicit_path=config_path)

    assert [item.code for item in result.diagnostics] == ["MARDAS-E117"]


def test_book_rejects_absolute_chapter_path(tmp_path: Path) -> None:
    chapter = tmp_path / "chapter.md"
    chapter.write_text("# Chapter\n", encoding="utf-8")
    config_path = tmp_path / "mardas.toml"
    config_path.write_text(
        f"schema_version = 1\n[book]\nchapters = [{str(chapter)!r}]\n",
        encoding="utf-8",
    )

    result = load_project_config(start=tmp_path, explicit_path=config_path)

    assert [item.code for item in result.diagnostics] == ["MARDAS-E116"]


def test_book_rejects_duplicate_chapter_source(tmp_path: Path) -> None:
    chapter = tmp_path / "chapter.md"
    chapter.write_text("# Chapter\n", encoding="utf-8")
    config_path = tmp_path / "mardas.toml"
    config_path.write_text(
        "schema_version = 1\n[book]\nchapters = ['chapter.md', 'chapter.md']\n",
        encoding="utf-8",
    )
    config = load_project_config(start=tmp_path, explicit_path=config_path).config

    _manifest, diagnostics = load_book_manifest(config)

    assert "MARDAS-E505" in [item.code for item in diagnostics]


def test_render_book_namespaces_heading_ids_and_embeds_each_chapter_assets(
    tmp_path: Path,
) -> None:
    config_path = _write_book_project(tmp_path)
    config = load_project_config(start=tmp_path, explicit_path=config_path).config
    manifest, diagnostics = load_book_manifest(config)
    assert manifest is not None and not diagnostics

    bundle, render_diagnostics = render_book(manifest)

    assert bundle is not None
    assert not [item for item in render_diagnostics if item.severity == "error"]
    html = bundle.result.body_html
    assert 'id="book-chapter-001-shared-heading"' in html
    assert 'id="book-chapter-002-shared-heading"' in html
    assert html.count("data:image/png;base64,") == 2
    assert "md2pdf-book-chapter-break" in html
    assert [entry[2] for entry in bundle.result.toc_entries[:3]] == [
        "book-chapter-001-shared-heading",
        "book-chapter-001-details",
        "book-chapter-002-shared-heading",
    ]
    assert bundle.result.title == "Ordered Research Book"


def test_render_book_can_disable_inter_chapter_page_break(tmp_path: Path) -> None:
    config_path = _write_book_project(tmp_path, chapter_page_break=False)
    config = load_project_config(start=tmp_path, explicit_path=config_path).config
    manifest, _ = load_book_manifest(config)
    assert manifest is not None

    bundle, _diagnostics = render_book(manifest)

    assert bundle is not None
    assert "md2pdf-book-chapter-break" not in bundle.result.body_html


def test_book_generates_heading_when_chapter_has_no_h1(tmp_path: Path) -> None:
    chapter = tmp_path / "chapter.md"
    chapter.write_text("---\ntitle: Generated Chapter\n---\n\nParagraph.\n", encoding="utf-8")
    config_path = tmp_path / "mardas.toml"
    config_path.write_text(
        "schema_version = 1\n[book]\nchapters = ['chapter.md']\n",
        encoding="utf-8",
    )
    config = load_project_config(start=tmp_path, explicit_path=config_path).config
    manifest, _ = load_book_manifest(config)
    assert manifest is not None

    bundle, diagnostics = render_book(manifest)

    assert bundle is not None
    assert [item.code for item in diagnostics] == ["MARDAS-W501"]
    assert bundle.result.toc_entries[0][:3] == (
        1,
        "Generated Chapter",
        "book-chapter-001-title",
    )


def test_validate_book_json_reports_ordered_chapters(tmp_path: Path, capsys) -> None:
    _write_book_project(tmp_path)

    assert main(["validate-book", str(tmp_path), "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["command"] == "validate-book"
    assert payload["chapter_count"] == 2
    assert [Path(item["path"]).name for item in payload["chapters"]] == [
        "01-introduction.md",
        "02-methods.md",
    ]
    assert payload["headings"] == 4


def test_explain_book_uses_manifest_title_override(tmp_path: Path, capsys) -> None:
    _write_book_project(tmp_path)

    assert main(["explain-book", str(tmp_path), "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["chapters"][1]["title"] == "Methods Override"
    assert payload["title"] == "Ordered Research Book"
    output = Path(payload["output"])
    assert output.name == "research-book.pdf"
    assert output.parent.name == "dist"


def test_init_book_creates_config_and_ordered_sample_chapters(tmp_path: Path) -> None:
    project = tmp_path / "new-book"

    assert main(["init", str(project), "--book"]) == 0

    config_text = (project / "mardas.toml").read_text(encoding="utf-8")
    assert "[book]" in config_text
    assert '"chapters/01-introduction.md"' in config_text
    assert (project / "chapters/01-introduction.md").is_file()
    assert (project / "chapters/02-content.md").is_file()
    assert main(["validate-book", str(project), "--format", "json"]) == 0


def test_build_book_uses_pre_rendered_bundle_and_output_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _write_book_project(tmp_path)
    output = tmp_path / "custom.pdf"
    captured: dict[str, object] = {}

    def fake_convert_render_result(result, options):
        captured["title"] = result.title
        captured["output"] = options.output_path
        captured["toc_entries"] = list(result.toc_entries)
        options.output_path.parent.mkdir(parents=True, exist_ok=True)
        options.output_path.write_bytes(b"%PDF-1.7\n")
        return options.output_path

    monkeypatch.setattr("mardas_folio.book.convert_render_result", fake_convert_render_result)

    assert (
        main(
            [
                "build-book",
                str(tmp_path),
                "--output",
                str(output),
                "--format",
                "json",
                "--progress",
                "off",
            ]
        )
        == 0
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["output"] == str(output.resolve())
    assert captured["title"] == "Ordered Research Book"
    assert captured["output"] == output.resolve()
    assert len(captured["toc_entries"]) == 4


def test_convert_book_rejects_debug_html_source_collision(tmp_path: Path) -> None:
    config_path = _write_book_project(tmp_path)
    config = load_project_config(start=tmp_path, explicit_path=config_path).config
    manifest, _ = load_book_manifest(config)
    assert manifest is not None
    bundle, _ = render_book(manifest)
    assert bundle is not None

    output, _bundle, diagnostics = convert_book(
        manifest,
        debug_html=manifest.chapters[0].path,
        bundle=bundle,
    )

    assert output is None
    assert [item.code for item in diagnostics] == ["MARDAS-E509"]


def test_book_resolves_cross_chapter_markdown_links(tmp_path: Path) -> None:
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "01-first.md").write_text(
        "# First\n\n[Go to details](02-second.md#details)\n",
        encoding="utf-8",
    )
    (chapters / "02-second.md").write_text(
        "# Second\n\n## Details\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "mardas.toml"
    config_path.write_text(
        "schema_version = 1\n[book]\nchapters = ['chapters/01-first.md', 'chapters/02-second.md']\n",
        encoding="utf-8",
    )
    config = load_project_config(start=tmp_path, explicit_path=config_path).config
    manifest, _ = load_book_manifest(config)
    assert manifest is not None

    bundle, diagnostics = render_book(manifest)

    assert bundle is not None
    assert not [item for item in diagnostics if item.severity == "error"]
    assert 'href="#book-chapter-002-details"' in bundle.result.body_html
    assert 'data-md2pdf-book-link="cross-chapter"' in bundle.result.body_html
    assert "md2pdf-local-link-blocked" not in bundle.result.body_html


def test_book_title_override_updates_visible_heading_and_global_toc(tmp_path: Path) -> None:
    config_path = _write_book_project(tmp_path)
    config = load_project_config(start=tmp_path, explicit_path=config_path).config
    manifest, _ = load_book_manifest(config)
    assert manifest is not None

    bundle, _diagnostics = render_book(manifest)

    assert bundle is not None
    assert "Methods Override" in bundle.result.body_html
    second_h1 = [entry for entry in bundle.result.toc_entries if entry[0] == 1][1]
    assert second_h1[1] == "Methods Override"
    assert second_h1[3] == "Methods Override"


def test_book_html_exposes_only_project_relative_source_labels(tmp_path: Path) -> None:
    config_path = _write_book_project(tmp_path)
    config = load_project_config(start=tmp_path, explicit_path=config_path).config
    manifest, _ = load_book_manifest(config)
    assert manifest is not None

    bundle, _diagnostics = render_book(manifest)

    assert bundle is not None
    assert str(tmp_path.resolve()) not in bundle.result.body_html
    assert 'data-book-source="chapters/part-a/01-introduction.md"' in bundle.result.body_html


def test_init_book_force_preserves_existing_chapter_content(tmp_path: Path) -> None:
    project = tmp_path / "book"
    assert main(["init", str(project), "--book"]) == 0
    chapter = project / "chapters/01-introduction.md"
    chapter.write_text("# User Content\n", encoding="utf-8")

    assert main(["init", str(project), "--book", "--force"]) == 0

    assert chapter.read_text(encoding="utf-8") == "# User Content\n"


def test_explain_config_serializes_book_manifest_values(tmp_path: Path, capsys) -> None:
    config_path = _write_book_project(tmp_path)
    chapter = tmp_path / "chapters/part-a/01-introduction.md"

    assert main(["explain-config", str(chapter), "--config", str(config_path), "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    chapters = payload["effective"]["book_chapters"]["value"]
    assert Path(chapters[0]["path"]).name == "01-introduction.md"
    output = Path(payload["effective"]["book_output"]["value"])
    assert output.name == "research-book.pdf"
    assert output.parent.name == "dist"


def test_doctor_validates_book_manifest_paths(tmp_path: Path, capsys) -> None:
    config_path = tmp_path / "mardas.toml"
    config_path.write_text(
        "schema_version = 1\n[book]\nchapters = ['missing.md']\n",
        encoding="utf-8",
    )

    assert main(["doctor", str(tmp_path), "--format", "json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert "MARDAS-E504" in [item["code"] for item in payload["diagnostics"]]


def test_book_chapter_can_embed_assets_from_shared_project_directory(tmp_path: Path) -> None:
    chapter_dir = tmp_path / "chapters/part-a"
    assets = tmp_path / "assets"
    chapter_dir.mkdir(parents=True)
    assets.mkdir()
    (assets / "pixel.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    )
    (chapter_dir / "chapter.md").write_text(
        "# Chapter\n\n![Shared](../../assets/pixel.png)\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "mardas.toml"
    config_path.write_text(
        "schema_version = 1\n[book]\nchapters = ['chapters/part-a/chapter.md']\n",
        encoding="utf-8",
    )
    config = load_project_config(start=tmp_path, explicit_path=config_path).config
    manifest, _ = load_book_manifest(config)
    assert manifest is not None

    bundle, diagnostics = render_book(manifest)

    assert bundle is not None
    assert not [item for item in diagnostics if item.severity == "error"]
    assert "data:image/png;base64," in bundle.result.body_html


def test_build_book_reports_controlled_render_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _write_book_project(tmp_path)

    def fail_convert(*_args, **_kwargs):
        raise RuntimeError("Chromium unavailable")

    monkeypatch.setattr("mardas_folio.project_commands.convert_book", fail_convert)

    assert (
        main(
            [
                "build-book",
                str(tmp_path),
                "--format",
                "json",
                "--progress",
                "off",
            ]
        )
        == 1
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["diagnostics"][-1]["code"] == "MARDAS-E511"
    assert "Traceback" not in payload["diagnostics"][-1]["message"]


def test_main_help_lists_book_workflows(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "validate-book" in output
    assert "explain-book" in output
    assert "build-book" in output


def test_book_resolves_citations_across_chapters_and_generates_one_bibliography(
    tmp_path: Path,
) -> None:
    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "01-introduction.md").write_text(
        "# Introduction\n\nPrior work [@doe2024].\n",
        encoding="utf-8",
    )
    (chapters / "02-methods.md").write_text(
        "# Methods\n\nThe method follows @smith2022.\n",
        encoding="utf-8",
    )
    (tmp_path / "references.bib").write_text(
        """
@article{doe2024, author={Doe, Jane}, title={Prior Work}, year={2024}}
@book{smith2022, author={Smith, Alex}, title={Methods}, year={2022}}
""".strip(),
        encoding="utf-8",
    )
    config_path = tmp_path / "mardas.toml"
    config_path.write_text(
        """schema_version = 1
[project]
title = "Cited Book"
lang = "en"

[bibliography]
enabled = true
sources = ["references.bib"]
style = "author-date"

[book]
chapters = ["chapters/01-introduction.md", "chapters/02-methods.md"]
output = "dist/book.pdf"
""".replace('lang = "en"\n', ''),
        encoding="utf-8",
    )
    config = load_project_config(start=tmp_path, explicit_path=config_path).config
    manifest, diagnostics = load_book_manifest(config)
    assert manifest is not None and not diagnostics

    bundle, render_diagnostics = render_book(manifest)

    assert bundle is not None
    assert not [item for item in render_diagnostics if item.severity == "error"]
    assert bundle.result.cited_keys == ("doe2024", "smith2022")
    assert len(bundle.result.citation_entries) == 2
    assert bundle.result.bibliography_html.count("md2pdf-bibliography-entry") == 2
    assert "Doe, 2024" in bundle.result.body_html
    assert "Smith (2022)" in bundle.result.body_html
    assert bundle.result.body_html.count("md2pdf-bibliography") == 0

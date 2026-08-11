from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from mardas_folio.cli import main
from mardas_folio.markdown import MarkdownInputError, render_markdown, render_markdown_file


def test_utf8_bom_does_not_break_frontmatter(tmp_path: Path) -> None:
    input_path = tmp_path / "bom.md"
    input_path.write_bytes(
        "\ufeff---\ntitle: BOM title\nlang: en\n---\n\n# Body\n".encode("utf-8")
    )

    result = render_markdown_file(input_path)

    assert result.metadata["title"] == "BOM title"
    assert result.title == "BOM title"
    assert "title: BOM title" not in result.body_html


def test_malformed_yaml_reports_location_and_reason() -> None:
    with pytest.raises(MarkdownInputError) as exc_info:
        render_markdown("---\ntitle: [broken\n---\n# Body\n")

    message = str(exc_info.value)
    assert "Invalid YAML front matter" in message
    assert "line" in message
    assert "column" in message


def test_indented_code_preserves_math_and_footnote_literals() -> None:
    result = render_markdown(
        "# Code\n\n"
        "    price = \"$x$\"\n"
        "    ref = \"[^note]\"\n\n"
        "[^note]: A real footnote.\n"
    )
    soup = BeautifulSoup(result.body_html, "html.parser")
    code = soup.select_one("figure.code-block pre")

    assert code is not None
    assert '$x$' in code.get_text()
    assert "[^note]" in code.get_text()
    assert code.find(class_="math") is None
    assert code.find("sup", class_="footnote-ref") is None


def test_multiline_inline_code_preserves_preprocessor_literals() -> None:
    result = render_markdown(
        "# Inline\n\n"
        "`first line\n"
        "$x$ and [^note]`\n\n"
        "[^note]: A real footnote.\n"
    )
    soup = BeautifulSoup(result.body_html, "html.parser")
    code = soup.find("code")

    assert code is not None
    assert "$x$" in code.get_text()
    assert "[^note]" in code.get_text()
    assert code.find(class_="math") is None
    assert code.find("sup", class_="footnote-ref") is None


def test_cli_path_collision_fails_without_modifying_source(tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "report.md"
    original = b"# Original Markdown\n"
    input_path.write_bytes(original)

    exit_code = main([str(input_path), "-o", str(input_path), "--progress", "off"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "must reference different files" in captured.err
    assert "Traceback" not in captured.err
    assert input_path.read_bytes() == original


def test_cli_invalid_encoding_returns_concise_error(tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "invalid.md"
    input_path.write_bytes(b"\xff\xfe\x00")

    exit_code = main([str(input_path), "--progress", "off"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("Error:")
    assert "codec can't decode" in captured.err
    assert "Traceback" not in captured.err


def test_cli_missing_chromium_path_returns_concise_error(tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "report.md"
    input_path.write_text("# Report\n", encoding="utf-8")

    exit_code = main(
        [
            str(input_path),
            "--chromium-path",
            str(tmp_path / "missing-chromium"),
            "--no-cover",
            "--no-mathjax",
            "--progress",
            "off",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("Error:")
    assert "missing-chromium" in captured.err
    assert "Traceback" not in captured.err

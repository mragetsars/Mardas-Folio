from __future__ import annotations

import json
from pathlib import Path

import pytest

from mardas_folio.cli import main
from mardas_folio.config import (
    CONFIG_SCHEMA_VERSION,
    default_config_text,
    discover_config,
    load_project_config,
)
from mardas_folio.renderer import PdfOptions


def test_init_creates_versioned_configuration_atomically(tmp_path: Path, capsys) -> None:
    assert main(["init", str(tmp_path)]) == 0

    config_path = tmp_path / "mardas.toml"
    assert config_path.is_file()
    assert f"schema_version = {CONFIG_SCHEMA_VERSION}" in config_path.read_text(encoding="utf-8")
    assert "Created project configuration" in capsys.readouterr().out

    with pytest.raises(SystemExit):
        main(["init", str(tmp_path)])


def test_default_configuration_is_valid(tmp_path: Path) -> None:
    path = tmp_path / "mardas.toml"
    path.write_text(default_config_text(), encoding="utf-8")

    result = load_project_config(start=tmp_path, explicit_path=path)

    assert not result.diagnostics
    assert result.config.values["page_size"] == "A4"
    assert result.config.values["toc"] is True
    assert result.config.values["no_cover"] is False
    assert result.config.values["no_header_footer"] is False
    assert result.config.values["no_mathjax"] is False


def test_config_discovery_uses_nearest_ancestor(tmp_path: Path) -> None:
    root_config = tmp_path / "mardas.toml"
    root_config.write_text("schema_version = 1\n", encoding="utf-8")
    nested = tmp_path / "project" / "docs"
    nested.mkdir(parents=True)
    project_config = tmp_path / "project" / "mardas.toml"
    project_config.write_text("schema_version = 1\n", encoding="utf-8")
    document = nested / "report.md"
    document.write_text("# Report\n", encoding="utf-8")

    assert discover_config(document) == project_config.resolve()


def test_relative_config_paths_resolve_from_config_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    logo = project / "assets" / "logo.png"
    logo.parent.mkdir()
    logo.write_bytes(b"png")
    config_path = project / "mardas.toml"
    config_path.write_text(
        "schema_version = 1\n[branding]\nlogo = 'assets/logo.png'\n",
        encoding="utf-8",
    )

    result = load_project_config(start=project, explicit_path=config_path)

    assert not result.diagnostics
    assert result.config.values["brand_logo"] == logo.resolve()


def test_unknown_config_key_returns_stable_diagnostic(tmp_path: Path) -> None:
    config_path = tmp_path / "mardas.toml"
    config_path.write_text(
        "schema_version = 1\n[appearance]\ncolour = 'blue'\n",
        encoding="utf-8",
    )

    result = load_project_config(start=tmp_path, explicit_path=config_path)

    assert [item.code for item in result.diagnostics] == ["MARDAS-E108"]
    assert "appearance.colour" in result.diagnostics[0].message


def test_invalid_config_value_returns_stable_diagnostic(tmp_path: Path) -> None:
    config_path = tmp_path / "mardas.toml"
    config_path.write_text(
        "schema_version = 1\n[output]\ntoc_depth = 99\n",
        encoding="utf-8",
    )

    result = load_project_config(start=tmp_path, explicit_path=config_path)

    assert [item.code for item in result.diagnostics] == ["MARDAS-E109"]
    assert "output.toc_depth" in result.diagnostics[0].message


def test_config_values_apply_to_conversion_and_cli_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "report.md"
    input_path.write_text("# Report\n", encoding="utf-8")
    (tmp_path / "mardas.toml").write_text(
        """schema_version = 1
[output]
toc = true
toc_depth = 2
page_size = "B5"
cover = false
[appearance]
style = "academic"
palette = "rose"
mode = "dark"
[security]
allow_remote_assets = true
""",
        encoding="utf-8",
    )
    captured: list[PdfOptions] = []

    def fake_convert(options: PdfOptions) -> Path:
        captured.append(options)
        return options.output_path

    monkeypatch.setattr("mardas_folio.cli.convert", fake_convert)

    assert main([str(input_path), "--style", "github", "--no-toc", "--progress", "off"]) == 0

    options = captured[0]
    assert options.style == "github"
    assert options.palette == "rose"
    assert options.mode == "dark"
    assert options.toc is False
    assert options.toc_depth == 2
    assert options.page_size == "B5"
    assert options.cover is False
    assert options.allow_remote_assets is True


def test_no_config_preserves_legacy_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    input_path = tmp_path / "report.md"
    input_path.write_text("# Report\n", encoding="utf-8")
    (tmp_path / "mardas.toml").write_text(
        "schema_version = 1\n[output]\ntoc = true\n",
        encoding="utf-8",
    )
    captured: list[PdfOptions] = []

    def fake_convert(options: PdfOptions) -> Path:
        captured.append(options)
        return options.output_path

    monkeypatch.setattr("mardas_folio.cli.convert", fake_convert)

    assert main([str(input_path), "--no-config", "--progress", "off"]) == 0
    assert captured[0].toc is False
    assert captured[0].style is None
    assert captured[0].palette is None
    assert captured[0].mode is None


def test_validate_json_is_machine_readable(tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "report.md"
    input_path.write_text("# Report\n\n### Jump\n", encoding="utf-8")

    assert main(["validate", str(input_path), "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["command"] == "validate"
    assert payload["document"]["headings"] == 2
    assert payload["diagnostics"][0]["code"] == "MARDAS-W202"


def test_validate_invalid_toml_returns_error_json(tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "report.md"
    input_path.write_text("# Report\n", encoding="utf-8")
    (tmp_path / "mardas.toml").write_text("[output\ntoc = true\n", encoding="utf-8")

    assert main(["validate", str(input_path), "--format", "json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["diagnostics"][0]["code"] == "MARDAS-E103"


def test_validate_malformed_front_matter_returns_structured_error(tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "report.md"
    input_path.write_text("---\ntitle: [broken\n---\n# Report\n", encoding="utf-8")

    assert main(["validate", str(input_path), "--format", "json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["diagnostics"][0]["code"] == "MARDAS-E203"
    assert "Invalid YAML front matter" in payload["diagnostics"][0]["message"]


def test_explain_config_reports_front_matter_then_project_precedence(
    tmp_path: Path, capsys
) -> None:
    input_path = tmp_path / "report.md"
    input_path.write_text(
        "---\ntitle: Front title\nappearance:\n  style: academic\n---\n# Report\n",
        encoding="utf-8",
    )

    assert main(["explain-config", str(input_path), "--format", "json"]) == 0
    without_config = json.loads(capsys.readouterr().out)
    assert without_config["effective"]["title"] == {
        "source": "front matter",
        "value": "Front title",
    }
    assert without_config["effective"]["style"]["value"] == "academic"

    (tmp_path / "mardas.toml").write_text(
        "schema_version = 1\n[project]\ntitle = 'Project title'\n[appearance]\nstyle = 'github'\n",
        encoding="utf-8",
    )
    assert main(["explain-config", str(input_path), "--format", "json"]) == 0
    with_config = json.loads(capsys.readouterr().out)
    assert with_config["effective"]["title"]["value"] == "Project title"
    assert with_config["effective"]["style"]["value"] == "github"
    assert with_config["effective"]["style"]["source"].endswith("mardas.toml")


def test_doctor_reports_missing_configured_chromium(tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "report.md"
    input_path.write_text("# Report\n", encoding="utf-8")
    (tmp_path / "mardas.toml").write_text(
        "schema_version = 1\n[browser]\nchromium_path = 'missing-browser'\n",
        encoding="utf-8",
    )

    assert main(["doctor", str(input_path), "--format", "json"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["diagnostics"][0]["code"] == "MARDAS-E401"


def test_conversion_rejects_invalid_project_config(tmp_path: Path) -> None:
    input_path = tmp_path / "report.md"
    input_path.write_text("# Report\n", encoding="utf-8")
    (tmp_path / "mardas.toml").write_text(
        "schema_version = 1\n[appearance]\nstyle = 'unknown'\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        main([str(input_path), "--progress", "off"])

    assert exc_info.value.code == 2


def test_validate_reports_project_security_warnings(tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "report.md"
    input_path.write_text("# Report\n", encoding="utf-8")
    (tmp_path / "mardas.toml").write_text(
        """schema_version = 1
[security]
unsafe_html = true
allow_remote_assets = true
""",
        encoding="utf-8",
    )

    assert main(["validate", str(input_path), "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert [item["code"] for item in payload["diagnostics"]] == [
        "MARDAS-W301",
        "MARDAS-W302",
    ]


def test_validate_reports_blocked_local_and_remote_images(tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "report.md"
    input_path.write_text(
        "# Report\n\n![Missing](missing.png)\n\n![Remote](https://example.invalid/image.png)\n",
        encoding="utf-8",
    )

    assert main(["validate", str(input_path), "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    codes = [item["code"] for item in payload["diagnostics"]]
    assert "MARDAS-W203" in codes
    assert "MARDAS-W204" in codes


def test_explain_config_marks_builtin_appearance_sources(tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "report.md"
    input_path.write_text("# Report\n", encoding="utf-8")

    assert main(["explain-config", str(input_path), "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["effective"]["style"] == {
        "source": "built-in default",
        "value": "modern",
    }
    assert payload["effective"]["palette"]["source"] == "built-in default"
    assert payload["effective"]["mode"]["source"] == "built-in default"


def test_zero_css_length_is_valid_in_project_config(tmp_path: Path) -> None:
    config_path = tmp_path / "mardas.toml"
    config_path.write_text(
        "schema_version = 1\n[output]\nmargin_top = '0'\n",
        encoding="utf-8",
    )

    result = load_project_config(start=tmp_path, explicit_path=config_path)

    assert not result.diagnostics
    assert result.config.values["margin_top"] == "0"


def test_doctor_reports_dependency_versions(tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "report.md"
    input_path.write_text("# Report\n", encoding="utf-8")

    assert main(["doctor", str(input_path), "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert "playwright" in payload["dependencies"]
    assert "pypdf" in payload["dependencies"]
    assert payload["ok"] is True


def test_front_matter_appearance_controls_code_style_when_cli_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mardas_folio.markdown import render_markdown

    captured: list[str] = []

    def fake_highlight_code(
        code: str,
        lang: str,
        attrs: str = "",
        *,
        code_style: str,
        caption: str | None = None,
        linenos: bool = False,
        highlight_lines: list[int] | None = None,
        line_start: int = 1,
        **kwargs: object,
    ) -> str:
        captured.append(code_style)
        return "<pre><code>ok</code></pre>"

    monkeypatch.setattr("mardas_folio.markdown.highlight_code", fake_highlight_code)

    render_markdown(
        "---\nappearance:\n  style: academic\n  mode: dark\n---\n```python\nprint('x')\n```\n"
    )

    assert captured and set(captured) == {"bw"}


def test_partial_project_appearance_combines_with_front_matter_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mardas_folio.markdown import render_markdown

    captured: list[str] = []

    def fake_highlight_code(
        code: str,
        lang: str,
        attrs: str = "",
        *,
        code_style: str,
        caption: str | None = None,
        linenos: bool = False,
        highlight_lines: list[int] | None = None,
        line_start: int = 1,
        **kwargs: object,
    ) -> str:
        captured.append(code_style)
        return "<pre><code>ok</code></pre>"

    monkeypatch.setattr("mardas_folio.markdown.highlight_code", fake_highlight_code)

    render_markdown(
        "---\nappearance:\n  mode: dark\n---\n```python\nprint('x')\n```\n",
        appearance_style="academic",
    )

    assert captured and set(captured) == {"bw"}


def test_resolved_appearance_is_persisted_for_footer_and_pdf_rendering(tmp_path: Path) -> None:
    from mardas_folio.renderer import PdfOptions, _apply_resolved_appearance

    options = PdfOptions(input_path=tmp_path / "in.md", output_path=tmp_path / "out.pdf")

    appearance = _apply_resolved_appearance(
        {"appearance": {"style": "academic", "palette": "rose", "mode": "dark"}},
        options,
    )

    assert appearance.style == "academic"
    assert options.style == "academic"
    assert options.palette == "rose"
    assert options.mode == "dark"


def test_oversized_project_config_is_rejected_before_toml_parsing(tmp_path: Path) -> None:
    from mardas_folio.config import MAX_CONFIG_BYTES

    config_path = tmp_path / "mardas.toml"
    config_path.write_bytes(b"#" * (MAX_CONFIG_BYTES + 1))

    result = load_project_config(start=tmp_path, explicit_path=config_path)

    assert [item.code for item in result.diagnostics] == ["MARDAS-E110"]


def test_project_title_prevents_missing_title_warning(tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "report.md"
    input_path.write_text("Paragraph only.\n", encoding="utf-8")
    (tmp_path / "mardas.toml").write_text(
        "schema_version = 1\n[project]\ntitle = 'Configured title'\n",
        encoding="utf-8",
    )

    assert main(["validate", str(input_path), "--format", "json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert "MARDAS-W201" not in [item["code"] for item in payload["diagnostics"]]
    assert payload["document"]["title"] == "Configured title"


def test_bibliography_config_resolves_local_sources_and_cli_can_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = tmp_path / "report.md"
    document.write_text("# Report\n\nEvidence [@doe2024].\n", encoding="utf-8")
    bibliography = tmp_path / "references.bib"
    bibliography.write_text(
        "@book{doe2024, author={Doe, Jane}, title={Evidence}, year={2024}}",
        encoding="utf-8",
    )
    alternate = tmp_path / "alternate.json"
    alternate.write_text(
        '[{"id":"alt2020","type":"book","title":"Alternate","issued":{"date-parts":[[2020]]}}]',
        encoding="utf-8",
    )
    config_path = tmp_path / "mardas.toml"
    config_path.write_text(
        """schema_version = 1
[bibliography]
enabled = true
sources = ["references.bib"]
style = "numeric"
include_uncited = true
""",
        encoding="utf-8",
    )
    loaded = load_project_config(start=document, explicit_path=config_path)
    assert not loaded.diagnostics
    assert loaded.config.values["bibliography_sources"] == (bibliography.resolve(),)

    captured: list[PdfOptions] = []

    def fake_convert(options: PdfOptions) -> Path:
        captured.append(options)
        return options.output_path

    monkeypatch.setattr("mardas_folio.cli.convert", fake_convert)
    assert (
        main(
            [
                str(document),
                "--bibliography",
                str(alternate),
                "--citation-style",
                "author-date",
                "--cited-only",
                "--progress",
                "off",
            ]
        )
        == 0
    )
    options = captured[0]
    assert options.citations_enabled is True
    assert options.bibliography_sources == (alternate,)
    assert options.citation_style == "author-date"
    assert options.bibliography_include_uncited is False


def test_bibliography_config_rejects_absolute_and_escaping_sources(tmp_path: Path) -> None:
    absolute = tmp_path / "absolute.bib"
    absolute.write_text("", encoding="utf-8")
    config_path = tmp_path / "mardas.toml"
    config_path.write_text(
        f'''schema_version = 1
[bibliography]
sources = [{str(absolute)!r}, "../outside.bib"]
''',
        encoding="utf-8",
    )

    result = load_project_config(start=tmp_path, explicit_path=config_path)

    assert {item.code for item in result.diagnostics} == {"MARDAS-E118", "MARDAS-E119"}


def test_quality_configuration_supports_strict_publication(tmp_path: Path) -> None:
    config_path = tmp_path / "mardas.toml"
    config_path.write_text(
        """schema_version = 1
[quality]
profile = "strict-publication"
math_errors = "error"
font_errors = "error"
navigation_errors = "error"
required_fonts = ["Vazirmatn", "JetBrains Mono"]
report = "build/quality.json"
""",
        encoding="utf-8",
    )

    result = load_project_config(start=tmp_path, explicit_path=config_path)

    assert not result.diagnostics
    assert result.config.values["quality_profile"] == "strict-publication"
    assert result.config.values["required_fonts"] == ("Vazirmatn", "JetBrains Mono")
    assert result.config.values["quality_report"] == (tmp_path / "build/quality.json").resolve()

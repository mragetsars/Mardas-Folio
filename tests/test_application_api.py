from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Callable

import pytest

from mardas_md2pdf import application, renderer, runtime
from mardas_md2pdf.application import EngineError, EngineService
from mardas_md2pdf.diagnostics import Diagnostic
from mardas_md2pdf.quality import RenderQualityLog
from mardas_md2pdf.renderer import PdfOptions


def test_atomic_text_write_honors_umask_and_preserves_existing_mode(
    tmp_path: Path,
) -> None:
    target = tmp_path / "preview.html"
    old_umask = os.umask(0o027)
    try:
        application._atomic_write_text(target, "first")
    finally:
        os.umask(old_umask)
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o640
        target.chmod(0o600)
    application._atomic_write_text(target, "second")
    assert target.read_text(encoding="utf-8") == "second"
    if os.name != "nt":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_pdf_options_request_resolves_relative_paths_and_configured_browser(
    tmp_path: Path,
) -> None:
    source = tmp_path / "doc.md"
    source.write_text("# Test", encoding="utf-8")
    browser = tmp_path / "runtime" / "chrome"
    browser.parent.mkdir()
    browser.write_bytes(b"browser")
    options = application.pdf_options_from_request(
        input_path=source,
        output_path="out/result.pdf",
        discover_config=False,
        options={
            "debug_html": "out/debug.html",
            "chromium_path": "runtime/chrome",
            "required_fonts": ["Vazirmatn", "Vazirmatn", "JetBrains Mono"],
            "bibliography_sources": ["refs.bib"],
        },
    )

    assert options.output_path == (tmp_path / "out/result.pdf").resolve()
    assert options.debug_html == (tmp_path / "out/debug.html").resolve()
    assert options.chromium_path == str(browser)
    assert options.required_fonts == ("Vazirmatn", "JetBrains Mono")
    assert options.bibliography_sources == ((tmp_path / "refs.bib").resolve(),)


@pytest.mark.parametrize(
    ("option", "value"),
    [
        pytest.param("margin_top", "18mm; color: red", id="css-injection"),
        pytest.param("toc", "false", id="wrong-boolean"),
        pytest.param("toc_depth", True, id="boolean-is-not-integer"),
        pytest.param("style", "minimal", id="unknown-enum"),
        pytest.param("timeout_ms", -1, id="integer-below-range"),
        pytest.param("watermark_opacity", 1.01, id="number-above-range"),
        pytest.param("watermark_opacity", float("nan"), id="nan"),
        pytest.param("watermark_opacity", float("inf"), id="infinity"),
        pytest.param("font_dir", 7, id="path-is-not-string"),
        pytest.param("required_fonts", ["Vazirmatn", 7], id="font-is-not-string"),
        pytest.param("required_fonts", ["Font"] * 33, id="too-many-fonts"),
        pytest.param("bibliography_sources", ["refs.bib", 7], id="bib-is-not-string"),
        pytest.param("bibliography_sources", ["refs.bib"] * 33, id="too-many-bibs"),
        pytest.param("bibliography_sources", ["refs.txt"], id="wrong-bib-extension"),
        pytest.param("title", "x" * 4_097, id="free-text-too-long"),
        pytest.param("title", "\ud800", id="free-text-invalid-unicode"),
        pytest.param("font_dir", "\ud800", id="path-invalid-unicode"),
    ],
)
def test_pdf_options_request_rejects_invalid_untrusted_overrides(
    tmp_path: Path,
    option: str,
    value: object,
) -> None:
    source = tmp_path / "doc.md"
    source.write_text("# Test", encoding="utf-8")

    with pytest.raises(EngineError) as caught:
        application.pdf_options_from_request(
            input_path=source,
            discover_config=False,
            options={option: value},
        )

    assert caught.value.code == "MARDAS-INVALID-PARAMS"
    assert caught.value.details["option"] == option
    assert isinstance(caught.value.details["reason"], str)


def test_pdf_options_request_validates_and_normalizes_all_supported_overrides(
    tmp_path: Path,
) -> None:
    source = tmp_path / "doc.md"
    source.write_text("# Test", encoding="utf-8")
    values: dict[str, object] = {
        "title": " Report ",
        "author": "Author",
        "description": "Summary",
        "toc": True,
        "toc_depth": 4,
        "toc_page_break": True,
        "h1_page_break": True,
        "debug_html": "artifacts/debug.html",
        "page_size": "Letter landscape",
        "document_language": "fa_IR",
        "document_direction": "RTL",
        "margin_top": "12.5mm",
        "margin_bottom": "0",
        "margin_x": "5%",
        "font_dir": "fonts",
        "chromium_path": "runtime/chrome",
        "chromium_sandbox": "OFF",
        "no_header_footer": True,
        "no_mathjax": True,
        "timeout_ms": 1_500,
        "style": "ACADEMIC",
        "palette": "EMERALD",
        "mode": "DARK",
        "cover": False,
        "cover_logo": "assets/cover.svg",
        "cover_logo_enabled": False,
        "branding": "SUBTLE",
        "brand_name": "Brand",
        "brand_logo": "assets/brand.svg",
        "brand_footer": "Footer",
        "watermark_text": "Draft",
        "watermark_image": "assets/watermark.svg",
        "watermark_opacity": 0.25,
        "watermark_width": "105mm",
        "unsafe_html": False,
        "allow_remote_assets": False,
        "references_enabled": True,
        "numbering_scope": "CHAPTER",
        "list_of_figures": True,
        "list_of_tables": False,
        "list_of_equations": True,
        "list_of_listings": False,
        "citations_enabled": True,
        "bibliography_sources": ["refs/library.bib", "refs/library.json"],
        "citation_style": "NUMERIC",
        "bibliography_title": "References",
        "bibliography_include_uncited": True,
        "quality_profile": "STRICT-PUBLICATION",
        "math_error_policy": "ERROR",
        "font_error_policy": "WARN",
        "navigation_error_policy": "IGNORE",
        "required_fonts": ["Vazirmatn", "Vazirmatn", "JetBrains Mono"],
        "quality_report": "artifacts/quality.json",
    }

    options = application.pdf_options_from_request(
        input_path=source,
        discover_config=False,
        options=values,
    )

    assert options.title == " Report "
    assert options.toc_depth == 4
    assert options.page_size == "Letter landscape"
    assert options.document_language == "fa-IR"
    assert options.document_direction == "rtl"
    assert options.chromium_sandbox == "off"
    assert options.style == "academic"
    assert options.palette == "emerald"
    assert options.mode == "dark"
    assert options.numbering_scope == "chapter"
    assert options.citation_style == "numeric"
    assert options.quality_profile == "strict-publication"
    assert options.required_fonts == ("Vazirmatn", "JetBrains Mono")
    assert options.debug_html == (tmp_path / "artifacts/debug.html").resolve()
    assert options.font_dir == (tmp_path / "fonts").resolve()
    assert options.chromium_path == str((tmp_path / "runtime/chrome").resolve())
    assert options.bibliography_sources == (
        (tmp_path / "refs/library.bib").resolve(),
        (tmp_path / "refs/library.json").resolve(),
    )


def test_pdf_options_request_accepts_null_only_for_nullable_overrides(
    tmp_path: Path,
) -> None:
    source = tmp_path / "doc.md"
    source.write_text("# Test", encoding="utf-8")

    options = application.pdf_options_from_request(
        input_path=source,
        discover_config=False,
        options={
            "title": None,
            "list_of_figures": None,
            "bibliography_include_uncited": None,
            "bibliography_sources": None,
            "required_fonts": None,
        },
    )
    assert options.title is None
    assert options.list_of_figures is None
    assert options.bibliography_include_uncited is None
    assert options.bibliography_sources == ()
    assert options.required_fonts == ()

    with pytest.raises(EngineError) as caught:
        application.pdf_options_from_request(
            input_path=source,
            discover_config=False,
            options={"toc": None},
        )
    assert caught.value.code == "MARDAS-INVALID-PARAMS"
    assert caught.value.details == {"option": "toc", "reason": "value cannot be null"}


def test_source_authoring_defers_cached_browser_resolution_until_pdf(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "doc.md"
    source.write_text("# Source\n", encoding="utf-8")
    browser = tmp_path / "runtime" / "chrome"
    browser.parent.mkdir()
    browser.write_bytes(b"browser")
    probe_calls = 0

    def probe_bundled_browser() -> Path:
        nonlocal probe_calls
        probe_calls += 1
        return browser

    runtime._clear_chromium_resolution_cache()
    monkeypatch.setattr(runtime, "bundled_chromium_path", probe_bundled_browser)
    try:
        service = EngineService()
        assert service.health()["status"] == "ok"
        assert service.dispatch(
            "validate.document",
            {"input_path": str(source), "discover_config": False},
        )["ok"] is True
        assert service.dispatch(
            "validate.document_text",
            {
                "input_path": str(source),
                "content": "# Dirty validate\n",
                "discover_config": False,
            },
        )["ok"] is True
        assert service.dispatch(
            "preview.document_text",
            {
                "input_path": str(source),
                "content": "# Dirty preview\n",
                "discover_config": False,
            },
        )["title"] == "Dirty preview"
        preview = tmp_path / "preview.html"
        assert service.dispatch(
            "preview.document",
            {
                "input_path": str(source),
                "output_path": str(preview),
                "discover_config": False,
            },
        )["output_path"] == str(preview)
        assert probe_calls == 0

        first = PdfOptions(source, tmp_path / "first.pdf")
        second = PdfOptions(source, tmp_path / "second.pdf")
        renderer._resolve_pdf_chromium_path(first)
        renderer._resolve_pdf_chromium_path(second)
        assert first.chromium_path == str(browser)
        assert second.chromium_path == str(browser)
        assert probe_calls == 1
    finally:
        runtime._clear_chromium_resolution_cache()


def test_render_document_returns_structured_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "doc.md"
    target = tmp_path / "doc.pdf"
    source.write_text("# Test", encoding="utf-8")
    options = PdfOptions(input_path=source, output_path=target)
    options.quality_log = RenderQualityLog()
    options.quality_log.record("render", "passed", "ok")

    def fake_convert(received: PdfOptions, *, session=None) -> Path:
        assert received is options
        target.write_bytes(b"%PDF-fake")
        return target

    monkeypatch.setattr(application, "convert", fake_convert)
    result = application.render_document(options)
    assert result["output_path"] == str(target)
    assert result["size_bytes"] == len(b"%PDF-fake")
    assert result["quality"]["ok"] is True


def test_validate_and_preview_document_without_chromium(tmp_path: Path) -> None:
    source = tmp_path / "doc.md"
    source.write_text("# سلام\n\nمتن **آزمایشی**.", encoding="utf-8")
    options = PdfOptions(input_path=source, output_path=tmp_path / "unused.pdf", cover=False)

    validated = application.validate_document(options)
    assert validated["ok"] is True
    assert validated["document"]["title"] == "سلام"

    preview_path = tmp_path / "preview.html"
    preview = application.preview_document(options, output_path=preview_path)
    assert preview["output_path"] == str(preview_path)
    assert preview_path.is_file()
    assert "آزمایشی" in preview_path.read_text(encoding="utf-8")


def test_preview_document_rejects_unsafe_output_paths_without_touching_source(
    tmp_path: Path,
) -> None:
    source = tmp_path / "doc.md"
    original = "# Original\n"
    source.write_text(original, encoding="utf-8")
    options = PdfOptions(input_path=source, output_path=tmp_path / "unused.pdf", cover=False)

    with pytest.raises(EngineError) as collision:
        application.preview_document(options, output_path=source)
    assert collision.value.code == "MARDAS-PREVIEW-PATH-COLLISION"
    assert source.read_text(encoding="utf-8") == original

    with pytest.raises(EngineError) as wrong_type:
        application.preview_document(options, output_path=tmp_path / "preview.pdf")
    assert wrong_type.value.code == "MARDAS-PREVIEW-OUTPUT-TYPE"
    assert not (tmp_path / "preview.pdf").exists()

    hardlink = tmp_path / "preview.html"
    try:
        hardlink.hardlink_to(source)
    except OSError:
        return
    with pytest.raises(EngineError) as alias:
        application.preview_document(options, output_path=hardlink)
    assert alias.value.code == "MARDAS-PREVIEW-PATH-COLLISION"
    assert source.read_text(encoding="utf-8") == original


def test_preview_document_text_normalizes_non_finite_frontmatter(tmp_path: Path) -> None:
    source = tmp_path / "doc.md"
    source.write_text("# Saved\n", encoding="utf-8")
    options = PdfOptions(input_path=source, output_path=tmp_path / "unused.pdf", cover=False)

    preview = application.preview_document_text(
        options,
        "---\nnot_a_number: .nan\npositive_infinity: .inf\n---\n\n# Preview\n",
    )

    assert preview["document"]["metadata"]["not_a_number"] is None
    assert preview["document"]["metadata"]["positive_infinity"] is None
    json.dumps(preview, allow_nan=False)


def test_validate_document_returns_controlled_parse_diagnostic(tmp_path: Path) -> None:
    source = tmp_path / "bad.md"
    source.write_text("---\ninvalid: [\n---\n", encoding="utf-8")
    options = PdfOptions(input_path=source, output_path=tmp_path / "unused.pdf")
    result = application.validate_document(options)
    assert result["ok"] is False
    assert result["diagnostics"][0]["code"] == "MARDAS-E203"


def test_engine_service_rejects_unknown_parameters_and_invalid_booleans(tmp_path: Path) -> None:
    source = tmp_path / "doc.md"
    source.write_text("# Test", encoding="utf-8")
    service = EngineService()
    with pytest.raises(EngineError) as unknown:
        service.dispatch(
            "validate.document",
            {"input_path": str(source), "unexpected": True},
        )
    assert unknown.value.details["unknown_parameters"] == ["unexpected"]

    with pytest.raises(EngineError, match="discover_config must be true or false"):
        service.dispatch(
            "validate.document",
            {"input_path": str(source), "discover_config": "false"},
        )


def test_engine_service_dispatches_document_methods(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "doc.md"
    source.write_text("# Test", encoding="utf-8")
    preview = tmp_path / "preview.html"
    monkeypatch.setattr(application, "validate_document", lambda options: {"ok": True})
    monkeypatch.setattr(
        application,
        "preview_document",
        lambda options, *, output_path: {"output_path": str(output_path)},
    )
    monkeypatch.setattr(
        application,
        "render_document",
        lambda options, *, session=None: {"output_path": str(options.output_path)},
    )
    service = EngineService()

    assert service.dispatch(
        "validate.document", {"input_path": str(source), "discover_config": False}
    ) == {"ok": True}
    assert service.dispatch(
        "preview.document",
        {
            "input_path": str(source),
            "output_path": str(preview),
            "discover_config": False,
        },
    ) == {"output_path": str(preview)}
    rendered = service.dispatch(
        "render.document",
        {
            "input_path": str(source),
            "output_path": str(tmp_path / "doc.pdf"),
            "discover_config": False,
        },
    )
    assert rendered["output_path"].endswith("doc.pdf")


def test_engine_service_dispatches_book_methods(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "mardas.toml"
    config.write_text("schema_version = 1\n", encoding="utf-8")
    monkeypatch.setattr(
        application,
        "validate_book",
        lambda config_path, *, cancelled=None: {"ok": True, "config": str(config_path)},
    )
    monkeypatch.setattr(
        application,
        "render_book_project",
        lambda config_path, **kwargs: {
            "output_path": str(kwargs["output_path"]),
            "debug_html": str(kwargs["debug_html"]),
        },
    )
    service = EngineService()
    validated = service.dispatch("validate.book", {"config_path": str(config)})
    assert validated["ok"] is True
    rendered = service.dispatch(
        "render.book",
        {
            "config_path": str(config),
            "output_path": "dist/book.pdf",
            "debug_html": "dist/book.html",
        },
    )
    assert rendered["output_path"] == str((tmp_path / "dist/book.pdf").resolve())
    assert rendered["debug_html"] == str((tmp_path / "dist/book.html").resolve())


def test_engine_service_capabilities_and_unknown_method() -> None:
    service = EngineService()
    capabilities = service.capabilities()
    assert capabilities["engine_api_version"] == application.ENGINE_API_VERSION
    assert "render.document" in capabilities["methods"]
    with pytest.raises(EngineError) as caught:
        service.dispatch("missing.method", {})
    assert caught.value.code == "MARDAS-METHOD-NOT-FOUND"


def test_render_book_project_reads_configured_quality_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    quality_path = tmp_path / "quality.json"
    quality_path.write_text(json.dumps({"ok": True}), encoding="utf-8")

    class Config:
        values = {"quality_report": quality_path}

    class Manifest:
        config = Config()

    output = tmp_path / "book.pdf"
    output.write_bytes(b"%PDF-book")
    monkeypatch.setattr(application, "_load_book", lambda path: (Manifest(), ()))
    monkeypatch.setattr(
        application,
        "convert_book",
        lambda *args, **kwargs: (output, object(), (Diagnostic("I", "info", "ok"),)),
    )
    monkeypatch.setattr(application, "book_context", lambda *args: {"title": "Book"})

    result = application.render_book_project(tmp_path / "mardas.toml")
    assert result["quality"] == {"ok": True}
    assert result["quality_report"] == str(quality_path)


def test_unsaved_document_text_uses_source_relative_assets(tmp_path: Path) -> None:
    source = tmp_path / "doc.md"
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    source.write_text("# Saved title\n", encoding="utf-8")
    options = PdfOptions(input_path=source, output_path=tmp_path / "unused.pdf", cover=False)

    validated = application.validate_document_text(
        options,
        "---\ntitle: Dirty title\n---\n\n# Heading\n\n![Local](image.png)\n",
    )
    assert validated["ok"] is True
    assert validated["document"]["title"] == "Dirty title"
    assert validated["document"]["outline"][0]["title"] == "Heading"

    preview = application.preview_document_text(options, "# Unsaved\n\n**buffer**")
    assert preview["title"] == "Unsaved"
    assert "buffer" in preview["body_html"]
    assert preview["source_map"] == [
        {"id": "unsaved", "line": 1, "level": 1, "title": "Unsaved"}
    ]
    assert source.read_text(encoding="utf-8") == "# Saved title\n"


def test_document_read_save_conflict_and_asset_import(tmp_path: Path) -> None:
    source = tmp_path / "doc.md"
    source.write_text("# One\n", encoding="utf-8")
    opened = application.read_document(source)
    assert opened["content"] == "# One\n"
    assert opened["kind"] == "markdown"

    saved = application.save_document(
        source,
        "# Two\n",
        expected_revision=opened["revision"],
    )
    assert saved["revision"] != opened["revision"]
    source.write_text("# External\n", encoding="utf-8")
    with pytest.raises(EngineError) as conflict:
        application.save_document(
            source,
            "# Editor\n",
            expected_revision=saved["revision"],
        )
    assert conflict.value.code == "MARDAS-DOCUMENT-CONFLICT"
    assert source.read_text(encoding="utf-8") == "# External\n"

    image = tmp_path / "outside.png"
    image.write_bytes(b"png")
    imported = application.import_document_asset(source, image)
    assert imported["relative_path"] == "assets/outside.png"
    assets = application.list_document_assets(source)["assets"]
    assert any(item["relative_path"] == "assets/outside.png" for item in assets)


@pytest.mark.parametrize("suffix", [".txt", ".toml", ".json", ".yaml", ".yml", ".bib"])
def test_engine_service_saves_supported_text_documents_with_revision_conflicts(
    tmp_path: Path,
    suffix: str,
) -> None:
    target = tmp_path / f"notes{suffix}"
    service = EngineService()
    saved = service.dispatch(
        "document.save_text",
        {"path": str(target), "content": "سلام\n", "force": False},
    )
    assert target.read_text(encoding="utf-8") == "سلام\n"
    assert saved["path"] == str(target)
    expected_kind = {
        ".bib": "bibliography",
        ".json": "json",
        ".toml": "toml",
    }.get(suffix, "text")
    assert saved["kind"] == expected_kind
    assert isinstance(saved["revision"], str)
    assert saved["size_bytes"] == len("سلام\n".encode("utf-8"))
    opened = service.dispatch("document.read_text", {"path": str(target)})
    assert opened["content"] == "سلام\n"
    assert opened["kind"] == expected_kind
    assert opened["revision"] == saved["revision"]

    target.write_text("external\n", encoding="utf-8")
    with pytest.raises(EngineError) as conflict:
        service.dispatch(
            "document.save_text",
            {
                "path": str(target),
                "content": "editor\n",
                "expected_revision": saved["revision"],
                "force": False,
            },
        )
    assert conflict.value.code == "MARDAS-DOCUMENT-CONFLICT"
    assert target.read_text(encoding="utf-8") == "external\n"


def test_text_document_save_rejects_unsupported_extensions_and_invalid_utf8(
    tmp_path: Path,
) -> None:
    with pytest.raises(EngineError) as unsupported:
        application.save_text_document(tmp_path / "notes.ini", "value=1\n")
    assert unsupported.value.code == "MARDAS-DOCUMENT-TYPE"

    with pytest.raises(EngineError) as encoding:
        application.save_text_document(tmp_path / "notes.txt", "bad surrogate: \ud800")
    assert encoding.value.code == "MARDAS-DOCUMENT-ENCODING"
    assert not (tmp_path / "notes.txt").exists()

    unsupported_read = tmp_path / "notes.md"
    unsupported_read.write_text("# Markdown\n", encoding="utf-8")
    with pytest.raises(EngineError) as read_type:
        application.read_text_document(unsupported_read)
    assert read_type.value.code == "MARDAS-DOCUMENT-TYPE"

    invalid_utf8 = tmp_path / "invalid.txt"
    invalid_utf8.write_bytes(b"\xff")
    with pytest.raises(EngineError) as read_encoding:
        application.read_text_document(invalid_utf8)
    assert read_encoding.value.code == "MARDAS-DOCUMENT-ENCODING"


@pytest.mark.parametrize(
    ("reader", "suffix"),
    [
        pytest.param(application.read_document, ".md", id="markdown"),
        pytest.param(application.read_text_document, ".txt", id="text"),
    ],
)
@pytest.mark.parametrize("case", ["missing", "directory"])
def test_document_read_maps_filesystem_failures_to_stable_engine_errors(
    tmp_path: Path,
    reader: Callable[[Path], dict[str, object]],
    suffix: str,
    case: str,
) -> None:
    path = tmp_path / f"document{suffix}"
    if case == "directory":
        path.mkdir()

    with pytest.raises(EngineError) as caught:
        reader(path)

    assert caught.value.code == "MARDAS-DOCUMENT-READ"
    assert caught.value.details == {"path": str(path)}
    assert "[Errno" not in str(caught.value)


def test_engine_service_dispatches_authoring_methods(tmp_path: Path) -> None:
    source = tmp_path / "doc.md"
    source.write_text("# Source\n", encoding="utf-8")
    service = EngineService()
    opened = service.dispatch("document.read", {"path": str(source)})
    saved = service.dispatch(
        "document.save",
        {
            "path": str(source),
            "content": "# Changed\n",
            "expected_revision": opened["revision"],
            "force": False,
        },
    )
    assert saved["path"] == str(source)
    preview = service.dispatch(
        "preview.document_text",
        {
            "input_path": str(source),
            "content": "# Dirty buffer\n",
            "discover_config": False,
        },
    )
    assert preview["title"] == "Dirty buffer"
    assert preview["source_map"][0]["line"] == 1
    assert "document.read" in service.capabilities()["methods"]
    assert "document.read_text" in service.capabilities()["methods"]
    assert "validate.document_text" in service.capabilities()["methods"]


def test_asset_import_rejects_symbolic_links(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symbolic links are not supported")
    document = tmp_path / "doc.md"
    document.write_text("# Doc\n", encoding="utf-8")
    source = tmp_path / "source.png"
    source.write_bytes(b"png")
    selected = tmp_path / "selected.png"
    try:
        selected.symlink_to(source)
    except OSError:
        pytest.skip("symbolic links are not available for this test user")

    with pytest.raises(EngineError) as caught:
        application.import_document_asset(document, selected)
    assert caught.value.code == "MARDAS-ASSET-INVALID"


def test_asset_import_rejects_symbolic_assets_directory(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symbolic links are not supported")
    document = tmp_path / "doc.md"
    document.write_text("# Doc\n", encoding="utf-8")
    external = tmp_path / "external-assets"
    external.mkdir()
    assets = tmp_path / "assets"
    try:
        assets.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are not available for this test user")
    source = tmp_path / "source.png"
    source.write_bytes(b"png")

    with pytest.raises(EngineError) as caught:
        application.import_document_asset(document, source)
    assert caught.value.code == "MARDAS-ASSET-INVALID"
    assert not (external / "source.png").exists()


def _desktop_project(tmp_path: Path) -> Path:
    root = tmp_path / "پروژه"
    root.mkdir()
    (root / "mardas.toml").write_text(
        """schema_version = 1

[project]
title = "Desktop Project"

[bibliography]
sources = ["references.bib"]
""",
        encoding="utf-8",
    )
    (root / "chapter.md").write_text("# سلام\n\nProject needle.\n", encoding="utf-8")
    (root / "references.bib").write_text(
        "@article{sample, title={Project Source}, author={Doe, Jane}, year={2026}}\n",
        encoding="utf-8",
    )
    return root


def test_engine_service_dispatches_project_and_bibliography_methods(tmp_path: Path) -> None:
    root = _desktop_project(tmp_path)
    service = EngineService()

    opened = service.dispatch("project.open", {"path": str(root)})
    assert opened["path"] == str(root.resolve())
    assert {item["path"] for item in opened["files"]} >= {
        "chapter.md",
        "references.bib",
    }

    document = service.dispatch(
        "project.read",
        {"project_path": str(root), "relative_path": "chapter.md"},
    )
    assert document["absolute_path"] == str((root / "chapter.md").resolve())
    assert document["content"].startswith("# سلام")
    assert document["kind"] == "markdown"
    assert isinstance(document["revision"], str)
    assert document["read_only"] is False

    searched = service.dispatch(
        "project.search",
        {"project_path": str(root), "query": "needle"},
    )
    assert searched["matches"][0]["path"] == "chapter.md"

    bibliography = service.dispatch(
        "bibliography.index",
        {
            "project_path": str(root),
            "query": "project source",
            "cited_keys": ["sample"],
        },
    )
    assert bibliography["entries"][0]["key"] == "sample"
    assert bibliography["entries"][0]["cited"] is True

    saved = service.dispatch(
        "project.save",
        {
            "project_path": str(root),
            "relative_path": "chapter.md",
            "content": "# Updated\n",
            "expected_sha256": document["sha256"],
        },
    )
    assert saved["absolute_path"] == str((root / "chapter.md").resolve())
    assert saved["kind"] == "markdown"
    assert isinstance(saved["revision"], str)
    assert saved["read_only"] is False
    assert (root / "chapter.md").read_text(encoding="utf-8") == "# Updated\n"


def test_engine_service_project_parameters_are_strict(tmp_path: Path) -> None:
    root = _desktop_project(tmp_path)
    service = EngineService()

    with pytest.raises(EngineError) as caught:
        service.dispatch(
            "project.search",
            {"project_path": str(root), "query": "x", "max_results": 0},
        )
    assert caught.value.code == "MARDAS-INVALID-PARAMS"

    with pytest.raises(EngineError) as unsafe:
        service.dispatch(
            "project.search",
            {"project_path": str(root), "query": r"(a+)+$", "regex": True},
        )
    assert unsafe.value.code == "MARDAS-UNSAFE-PROJECT-SEARCH-REGEX"


def test_engine_service_rejects_non_utf8_project_content_without_codec_leak(
    tmp_path: Path,
) -> None:
    root = _desktop_project(tmp_path)
    service = EngineService()
    opened = service.dispatch(
        "project.read",
        {"project_path": str(root), "relative_path": "chapter.md"},
    )

    with pytest.raises(EngineError) as caught:
        service.dispatch(
            "project.save",
            {
                "project_path": str(root),
                "relative_path": "chapter.md",
                "content": "\ud800",
                "expected_sha256": opened["sha256"],
            },
        )

    assert caught.value.code == "MARDAS-INVALID-PROJECT-CONTENT"
    assert str(caught.value) == "Project file content must be valid UTF-8 text."
    assert (root / "chapter.md").read_text(encoding="utf-8").startswith("# سلام")

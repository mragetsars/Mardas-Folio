from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from mardas_md2pdf import application
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


def test_pdf_options_request_resolves_relative_paths_and_runtime_browser(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "doc.md"
    source.write_text("# Test", encoding="utf-8")
    browser = tmp_path / "runtime" / "chrome"
    browser.parent.mkdir()
    browser.write_bytes(b"browser")
    monkeypatch.setattr(application, "resolved_chromium_path", lambda: browser)

    options = application.pdf_options_from_request(
        input_path=source,
        output_path="out/result.pdf",
        discover_config=False,
        options={
            "debug_html": "out/debug.html",
            "required_fonts": ["Vazirmatn", "Vazirmatn", ""],
            "bibliography_sources": ["refs.bib"],
        },
    )

    assert options.output_path == (tmp_path / "out/result.pdf").resolve()
    assert options.debug_html == (tmp_path / "out/debug.html").resolve()
    assert options.chromium_path == str(browser)
    assert options.required_fonts == ("Vazirmatn", "Vazirmatn")
    assert options.bibliography_sources == ((tmp_path / "refs.bib").resolve(),)


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
    monkeypatch.setattr(application, "resolved_chromium_path", lambda: None)
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

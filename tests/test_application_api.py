from __future__ import annotations

import json
import os
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

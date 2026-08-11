from __future__ import annotations

import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from mardas_folio import gui
from mardas_folio.markdown import render_markdown
from mardas_folio.renderer import (
    DocumentAssetError,
    OutputPathError,
    PdfOptions,
    _atomic_write_pdf,
    _validate_conversion_paths,
    build_html,
)


def test_frontmatter_branding_cannot_read_absolute_or_parent_files(tmp_path: Path) -> None:
    document_dir = tmp_path / "document"
    document_dir.mkdir()
    input_path = document_dir / "report.md"
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"not really an image")

    for reference in (str(outside), "../outside.png"):
        result = render_markdown(
            f"---\nbranding: full\nbrand_logo: {json.dumps(reference)}\n---\n\n# Report\n"
        )
        with pytest.raises(DocumentAssetError, match="document directory"):
            build_html(result, PdfOptions(input_path=input_path, output_path=document_dir / "out.pdf"))


def test_frontmatter_branding_rejects_symlink_escape(tmp_path: Path) -> None:
    document_dir = tmp_path / "document"
    document_dir.mkdir()
    input_path = document_dir / "report.md"
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"\x89PNG\r\n\x1a\n")
    link = document_dir / "logo.png"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable in this environment")

    result = render_markdown("---\nbranding: full\nbrand_logo: logo.png\n---\n\n# Report\n")
    with pytest.raises(DocumentAssetError, match="outside"):
        build_html(result, PdfOptions(input_path=input_path, output_path=document_dir / "out.pdf"))


def test_studio_reports_unsafe_frontmatter_asset_without_disclosing_file(tmp_path: Path) -> None:
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"secret-bytes")
    server = ThreadingHTTPServer(("127.0.0.1", 0), gui.GuiRequestHandler)
    server.studio_bind_host = "127.0.0.1"  # type: ignore[attr-defined]
    server.studio_csrf_token = "secret"  # type: ignore[attr-defined]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        markdown = (
            f"---\nbranding: full\nbrand_logo: {json.dumps(str(outside))}\n---\n\n# Report\n"
        )
        body = json.dumps({"markdown": markdown, "options": {"branding": "full"}})
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        connection.request(
            "POST",
            "/api/render-html",
            body=body,
            headers={
                "Content-Type": "application/json",
                "Origin": f"http://127.0.0.1:{server.server_port}",
                "X-Mardas-Studio-Token": "secret",
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)

    assert response.status == 400
    assert payload["code"] == "unsafe_document_asset"
    assert "secret-bytes" not in json.dumps(payload)


def test_conversion_paths_must_not_alias_input_output_or_debug_html(tmp_path: Path) -> None:
    input_path = tmp_path / "report.md"
    input_path.write_text("# Report\n", encoding="utf-8")

    with pytest.raises(OutputPathError, match="different files"):
        _validate_conversion_paths(PdfOptions(input_path=input_path, output_path=input_path))

    with pytest.raises(OutputPathError, match="different files"):
        _validate_conversion_paths(
            PdfOptions(
                input_path=input_path,
                output_path=tmp_path / "report.pdf",
                debug_html=input_path,
            )
        )

    output_path = tmp_path / "hardlink.pdf"
    try:
        output_path.hardlink_to(input_path)
    except OSError:
        pytest.skip("hardlinks are unavailable in this environment")
    with pytest.raises(OutputPathError, match="different files"):
        _validate_conversion_paths(PdfOptions(input_path=input_path, output_path=output_path))


def test_atomic_pdf_write_preserves_previous_output_on_failure(tmp_path: Path) -> None:
    output_path = tmp_path / "report.pdf"
    original = b"%PDF-1.7\nORIGINAL\n"
    output_path.write_bytes(original)

    class FailingWriter:
        def write(self, fh) -> None:
            fh.write(b"%PDF-1.7\nPARTIAL\n")
            raise OSError("simulated disk failure")

    with pytest.raises(OSError, match="simulated disk failure"):
        _atomic_write_pdf(FailingWriter(), output_path)  # type: ignore[arg-type]

    assert output_path.read_bytes() == original
    assert not list(tmp_path.glob(".report.pdf.*.tmp"))


def test_fast_preview_enforces_safe_link_and_image_url_policy() -> None:
    source = (Path(gui.__file__).parent / "assets" / "gui.html").read_text(encoding="utf-8")

    assert "function safeFastPreviewLinkUrl" in source
    assert "function safeFastPreviewImageUrl" in source
    assert "['http:', 'https:', 'mailto:']" in source
    assert "Fast Preview blocks local and remote images" in source
    assert "src=\"$2\"" not in source
    assert "href=\"$2\"" not in source


def test_conversion_paths_protect_bibliography_sources(tmp_path: Path) -> None:
    input_path = tmp_path / "report.md"
    input_path.write_text("# Report\n", encoding="utf-8")
    bibliography = tmp_path / "references.bib"
    bibliography.write_text("@book{x, title={X}, year={2024}}", encoding="utf-8")

    with pytest.raises(OutputPathError, match="bibliography source"):
        _validate_conversion_paths(
            PdfOptions(
                input_path=input_path,
                output_path=bibliography,
                bibliography_sources=(bibliography,),
            )
        )
    with pytest.raises(OutputPathError, match="bibliography source"):
        _validate_conversion_paths(
            PdfOptions(
                input_path=input_path,
                output_path=tmp_path / "report.pdf",
                debug_html=bibliography,
                bibliography_sources=(bibliography,),
            )
        )

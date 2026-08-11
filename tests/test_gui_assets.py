import socket
import time
from email.message import Message
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Event, Lock, Thread


GUI_HTML = Path(__file__).resolve().parents[1] / "src" / "mardas_folio" / "assets" / "gui.html"


def test_gui_exposes_pdf_like_and_fast_preview_modes_and_custom_page_sizes():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert "PDF-like preview uses backend renderer HTML" in html
    assert "page size and margins" in html
    assert "page guides" not in html
    assert "Fast is an approximate browser-local editing preview" in html
    assert "Exact PDF" not in html
    assert '<option value="accurate" selected>PDF-like</option>' in html
    assert '<option value="pdf">' not in html
    assert '<option value="fast">Fast (approx)</option>' in html
    assert "A4 landscape" in html
    assert "210mm 297mm" in html




def test_studio_pdf_like_preview_page_dimensions():
    from mardas_folio import gui

    assert gui._studio_preview_page_dimensions("A4") == ("210mm", "297mm")
    assert gui._studio_preview_page_dimensions("A4 landscape") == ("297mm", "210mm")
    assert gui._studio_preview_page_dimensions("Letter") == ("8.5in", "11in")
    assert gui._studio_preview_page_dimensions("210mm 297mm") == ("210mm", "297mm")


def test_studio_html_preview_injects_pdf_like_screen_css():
    from mardas_folio import gui

    html = gui._render_studio_html_payload(
        {
            "markdown": "# Title\n\n<!-- pagebreak -->\n\nBody",
            "options": {"toc": False, "noCover": True, "pageSize": "A4 landscape"},
            "assets": [],
        }
    )

    assert 'id="mardas-studio-preview-css"' in html
    assert "--md2pdf-preview-page-width: 297mm;" in html
    assert "--md2pdf-preview-page-height: 210mm;" in html
    assert "padding: var(--page-margin-top) var(--page-margin-x) var(--page-margin-bottom)" in html
    assert "--md2pdf-preview-scale: 1;" in html
    assert "zoom: var(--md2pdf-preview-scale);" in html
    assert 'id="mardas-studio-preview-scale-script"' in html
    assert "updatePreviewScale" in html
    assert "refreshPageGuides" not in html
    assert ".md2pdf-preview-page-guides" not in html
    assert ".md2pdf-preview-page-guide" not in html
    assert ".md2pdf-page-break::after" in html
    assert "Explicit page break" in html


def test_studio_html_preview_styles_scrollbars_for_dark_pdf_like_frames():
    from mardas_folio import gui

    html = gui._render_studio_html_payload(
        {
            "markdown": "# Dark preview\n\n" + "Body\n\n" * 80,
            "options": {"toc": False, "noCover": True, "mode": "dark"},
            "assets": [],
        }
    )

    assert "scrollbar-color: #4a4a4a transparent" in html
    assert "*::-webkit-scrollbar-thumb" in html
    assert "md2pdf-preview-dark" in html
    assert "syncPreviewShellTheme" in html


def test_gui_wires_pdf_like_and_fast_preview_refresh_triggers():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert "const ACCURATE_PREVIEW_DELAY_MS = 720" in html
    assert "function schedulePreviewRender" in html
    assert "function requestAccuratePreview" in html
    assert "accuratePreviewAbortController" in html
    assert "accuratePreviewSequence" in html
    assert "X-Mardas-Studio-Preview-Id" in html
    assert "lastAccuratePreviewKey" in html
    assert "function cancelAccuratePreviewRequest" in html
    assert "function assetPreviewFingerprint" in html
    assert "function requestPdfPreview" not in html
    assert "previewPdfObjectUrl" not in html
    assert "['fast','accurate'].includes(state.previewMode)" in html
    assert "control.addEventListener('input', () =>" in html
    assert "control.addEventListener('change', () =>" in html
    assert "setBrandLogoFromAsset" in html


def test_gui_limits_scroll_sync_to_fast_preview_and_hardens_editor_gutter():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert 'spellcheck="false" wrap="off"' in html
    assert "function buildLineNumberRows" in html
    assert "line-number-row" in html
    assert "lineNumberContent.innerHTML = buildLineNumberRows" in html
    assert "editor.scrollTop - padding.top" in html
    assert "activePreviewMode() !== 'fast'" in html
    assert "function syncFramePreviewScroll" not in html
    assert "accuratePreviewFrame.addEventListener('load', () => syncPreviewScroll())" not in html
    assert "Fast is an approximate browser-local editing preview with editor scroll sync" in html


def test_gui_direction_toggle_updates_document_options_for_pdf_like_preview():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert "function activeDocumentDirection" in html
    assert "function applyDocumentDirection" in html
    assert "const next = activeDocumentDirection() === 'rtl' ? 'ltr' : 'rtl';" in html
    assert "if (field) field.value = next;" in html
    assert "renderPreview();" in html
    assert "state.previewDirection" in html  # backward-compatible migration only
    assert "previewDirection: preview.getAttribute" not in html


def test_gui_copy_command_uses_shell_quoting_for_paths_and_metadata():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert "function shellQuote" in html
    assert "text.replace(/'/g" in html
    assert "\\''" in html
    assert "function pushOption" in html
    assert "'folio'," in html
    assert "'--page-size', shellQuote(options.pageSize || 'A4')" in html
    assert "pushOption(cmd, '--title', options.title)" in html
    assert "pushOption(cmd, '--brand-name', options.brandName)" in html
    assert "pushOption(cmd, '--watermark', options.watermark)" in html
    assert '--brand-name "' not in html


def test_gui_clarifies_fast_mermaid_preview_is_subset_based():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert 'title="Mermaid flowchart subset"' in html
    assert "Mermaid flowchart preview" in html
    assert "export uses offline subset" in html

def test_gui_asset_writer_enforces_size_limits(tmp_path, monkeypatch):
    import base64

    from mardas_folio import gui

    def asset(path: str, size: int) -> dict[str, str]:
        payload = base64.b64encode(b"x" * size).decode("ascii")
        return {"path": path, "data": f"data:image/png;base64,{payload}"}

    monkeypatch.setattr(gui, "MAX_GUI_ASSET_BYTES", 10)
    monkeypatch.setattr(gui, "MAX_GUI_TOTAL_ASSET_BYTES", 15)

    gui._write_gui_assets(tmp_path, [asset("a.png", 10), asset("b.png", 6), asset("c.png", 11)])

    assert (tmp_path / "a.png").exists()
    assert not (tmp_path / "b.png").exists()
    assert not (tmp_path / "c.png").exists()




def _encoded_asset(path: str, payload: str = "eA==") -> dict[str, str]:
    return {"path": path, "data": f"data:application/octet-stream;base64,{payload}"}


def test_studio_asset_writer_rejects_file_directory_collisions_without_partial_writes(tmp_path):
    import pytest

    from mardas_folio import gui

    for paths in [
        ("collision", "collision/child.png"),
        ("collision/child.png", "collision"),
        ("same.png", "same.png"),
        ("Images/Logo.png", "images/logo.png"),
    ]:
        case_dir = tmp_path / str(len(list(tmp_path.iterdir())))
        case_dir.mkdir()
        with pytest.raises(gui.StudioRequestError) as exc_info:
            gui._write_gui_assets(case_dir, [_encoded_asset(path) for path in paths])
        assert exc_info.value.status == 400
        assert exc_info.value.code == "conflicting_asset_path"
        assert list(case_dir.iterdir()) == []


def test_studio_asset_writer_keeps_duplicate_basenames_in_separate_directories(tmp_path):
    from mardas_folio import gui

    gui._write_gui_assets(
        tmp_path,
        [_encoded_asset("a/logo.png"), _encoded_asset("b/logo.png", "eQ==")],
    )

    assert (tmp_path / "a" / "logo.png").read_bytes() == b"x"
    assert (tmp_path / "b" / "logo.png").read_bytes() == b"y"
    assert not (tmp_path / "logo.png").exists()


def test_studio_asset_writer_skips_ambiguous_basename_fallback(tmp_path):
    from mardas_folio import gui

    gui._write_gui_assets(
        tmp_path,
        [_encoded_asset("logo.png"), _encoded_asset("images/logo.png", "eQ==")],
    )

    assert (tmp_path / "logo.png").read_bytes() == b"x"
    assert (tmp_path / "images" / "logo.png").read_bytes() == b"y"


def test_studio_asset_writer_rejects_reserved_working_paths(tmp_path):
    import pytest

    from mardas_folio import gui

    for path in ("document.md", "document.md/child.png", "DOCUMENT.MD"):
        with pytest.raises(gui.StudioRequestError) as exc_info:
            gui._write_gui_assets(
                tmp_path,
                [_encoded_asset(path)],
                reserved_paths=(Path("document.md"), Path("export.pdf")),
            )
        assert exc_info.value.status == 400
        assert exc_info.value.code == "reserved_asset_path"
        assert list(tmp_path.iterdir()) == []


def test_studio_http_preview_rejects_colliding_asset_paths_as_client_error():
    import json

    from mardas_folio import gui

    server = ThreadingHTTPServer(("127.0.0.1", 0), gui.GuiRequestHandler)
    server.studio_bind_host = "127.0.0.1"  # type: ignore[attr-defined]
    server.studio_csrf_token = "secret"  # type: ignore[attr-defined]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps(
            {
                "markdown": "# Collision",
                "assets": [_encoded_asset("collision"), _encoded_asset("collision/child.png")],
            }
        )
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
    assert payload["code"] == "conflicting_asset_path"
    assert "File exists" not in payload["error"]


def test_studio_asset_paths_preserve_spaces_and_unicode(tmp_path):
    from mardas_folio import gui

    gui._write_gui_assets(
        tmp_path,
        [
            {
                "path": "images/my chart ۱۴۰۵.png",
                "data": "data:image/png;base64,eA==",
            }
        ],
    )

    assert (tmp_path / "images" / "my chart ۱۴۰۵.png").read_bytes() == b"x"
    assert (tmp_path / "my chart ۱۴۰۵.png").read_bytes() == b"x"
    assert gui._safe_asset_relative_path("images/my chart ۱۴۰۵.png").as_posix() == "images/my chart ۱۴۰۵.png"


def test_studio_html_render_embeds_attached_assets_with_spaces_in_paths():
    from mardas_folio import gui

    html = gui._render_studio_html_payload(
        {
            "markdown": "![Chart](<images/my chart ۱۴۰۵.png>)\n",
            "options": {"toc": False, "noCover": True},
            "assets": [
                {
                    "path": "images/my chart ۱۴۰۵.png",
                    "data": "data:image/png;base64,eA==",
                }
            ],
        }
    )

    assert "data:image/png;base64,eA==" in html
    assert 'data-md2pdf-source="images/my%20chart%20%DB%B1%DB%B4%DB%B0%DB%B5.png"' in html
    assert "data-md2pdf-blocked-reason" not in html
    assert "Image blocked or missing" not in html


def test_studio_brand_logo_path_uses_attached_assets(tmp_path):
    from mardas_folio import gui

    gui._write_gui_assets(
        tmp_path,
        [
            {
                "path": "images/logo.png",
                "data": "data:image/png;base64,eA==",
            }
        ],
    )

    logo = tmp_path / gui._safe_asset_relative_path("images/logo.png", fallback="brand-logo")
    assert logo.is_file()
    assert logo.read_bytes() == b"x"


def test_gui_documents_asset_limits():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert "Up to 250 assets" in html
    assert "12 MB per asset" in html
    assert "32 MB total" in html
    assert "MAX_GUI_ASSETS" in html


def test_studio_json_decode_errors_are_client_facing():
    import pytest

    from mardas_folio import gui

    with pytest.raises(gui.StudioRequestError) as exc_info:
        gui._decode_json_payload(b'{bad json')

    assert exc_info.value.status == 400
    assert exc_info.value.code == "invalid_json"
    assert "valid JSON" in str(exc_info.value)


def test_studio_error_payload_includes_code_and_status():
    from mardas_folio import gui

    assert gui._error_payload("Nope", status=413, code="too_large") == {
        "error": "Nope",
        "status": 413,
        "code": "too_large",
    }


def _headers(**items: str) -> Message:
    headers = Message()
    for key, value in items.items():
        headers[key.replace("_", "-")] = value
    return headers


def test_studio_api_headers_require_same_origin_json_and_token():
    from mardas_folio import gui

    gui._validate_studio_post_headers(
        _headers(
            Host="127.0.0.1:8765",
            Origin="http://127.0.0.1:8765",
            Content_Type="application/json; charset=utf-8",
            Sec_Fetch_Site="same-origin",
            X_Mardas_Studio_Token="secret",
        ),
        bind_host="127.0.0.1",
        csrf_token="secret",
    )

    for headers, expected_code in [
        (
            _headers(
                Host="evil.example",
                Origin="http://evil.example",
                Content_Type="application/json",
                X_Mardas_Studio_Token="secret",
            ),
            "untrusted_host",
        ),
        (
            _headers(
                Host="127.0.0.1:8765",
                Origin="https://evil.example",
                Content_Type="application/json",
                X_Mardas_Studio_Token="secret",
            ),
            "untrusted_origin",
        ),
        (
            _headers(
                Host="127.0.0.1:8765",
                Origin="http://127.0.0.1:8765",
                Content_Type="text/plain",
                X_Mardas_Studio_Token="secret",
            ),
            "unsupported_media_type",
        ),
        (
            _headers(
                Host="127.0.0.1:8765",
                Origin="http://127.0.0.1:8765",
                Content_Type="application/json",
                Sec_Fetch_Site="cross-site",
                X_Mardas_Studio_Token="secret",
            ),
            "untrusted_fetch_site",
        ),
        (
            _headers(
                Host="127.0.0.1:8765",
                Origin="http://127.0.0.1:8765",
                Content_Type="application/json",
                X_Mardas_Studio_Token="wrong",
            ),
            "invalid_studio_token",
        ),
    ]:
        try:
            gui._validate_studio_post_headers(headers, bind_host="127.0.0.1", csrf_token="secret")
        except gui.StudioRequestError as exc:
            assert exc.status in {403, 415}
            assert exc.code == expected_code
        else:  # pragma: no cover - defensive assertion branch
            raise AssertionError(f"expected StudioRequestError for {expected_code}")




def test_studio_content_length_requires_non_negative_bounded_values():
    import pytest

    from mardas_folio import gui

    assert gui._studio_content_length(_headers(Content_Length="0")) == 0
    assert (
        gui._studio_content_length(_headers(Content_Length=str(gui.MAX_GUI_REQUEST_BYTES)))
        == gui.MAX_GUI_REQUEST_BYTES
    )

    cases = [
        ({}, 411, "length_required"),
        ({"Content_Length": "not-a-number"}, 400, "invalid_content_length"),
        ({"Content_Length": "-1"}, 400, "invalid_content_length"),
        (
            {"Content_Length": str(gui.MAX_GUI_REQUEST_BYTES + 1)},
            413,
            "request_too_large",
        ),
    ]
    for header_values, expected_status, expected_code in cases:
        with pytest.raises(gui.StudioRequestError) as exc_info:
            gui._studio_content_length(_headers(**header_values))
        assert exc_info.value.status == expected_status
        assert exc_info.value.code == expected_code


def test_studio_post_headers_reject_transfer_encoding():
    import pytest

    from mardas_folio import gui

    headers = _headers(
        Host="127.0.0.1:8765",
        Origin="http://127.0.0.1:8765",
        Content_Type="application/json",
        Transfer_Encoding="chunked",
        X_Mardas_Studio_Token="secret",
    )
    with pytest.raises(gui.StudioRequestError) as exc_info:
        gui._validate_studio_post_headers(
            headers, bind_host="127.0.0.1", csrf_token="secret"
        )

    assert exc_info.value.status == 400
    assert exc_info.value.code == "unsupported_transfer_encoding"


def test_studio_http_api_rejects_negative_content_length_before_reading_body():
    from mardas_folio import gui

    server = ThreadingHTTPServer(("127.0.0.1", 0), gui.GuiRequestHandler)
    server.studio_bind_host = "127.0.0.1"  # type: ignore[attr-defined]
    server.studio_csrf_token = "secret"  # type: ignore[attr-defined]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = (
            "POST /api/render-html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{server.server_port}\r\n"
            f"Origin: http://127.0.0.1:{server.server_port}\r\n"
            "Content-Type: application/json\r\n"
            "X-Mardas-Studio-Token: secret\r\n"
            "Content-Length: -1\r\n"
            "Connection: close\r\n"
            "\r\n"
            '{"markdown":"# must not be read"}'
        ).encode("ascii")
        with socket.create_connection(("127.0.0.1", server.server_port), timeout=10) as connection:
            connection.sendall(request)
            response = bytearray()
            while True:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                response.extend(chunk)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)

    response_text = response.decode("utf-8")
    assert " 400 " in response_text.split("\r\n", 1)[0]
    assert '"code": "invalid_content_length"' in response_text


def test_studio_http_api_rejects_incomplete_request_body():
    from mardas_folio import gui

    server = ThreadingHTTPServer(("127.0.0.1", 0), gui.GuiRequestHandler)
    server.studio_bind_host = "127.0.0.1"  # type: ignore[attr-defined]
    server.studio_csrf_token = "secret"  # type: ignore[attr-defined]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = b'{"markdown":"# short"}'
        request = (
            "POST /api/render-html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{server.server_port}\r\n"
            f"Origin: http://127.0.0.1:{server.server_port}\r\n"
            "Content-Type: application/json\r\n"
            "X-Mardas-Studio-Token: secret\r\n"
            f"Content-Length: {len(body) + 5}\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii") + body
        with socket.create_connection(("127.0.0.1", server.server_port), timeout=10) as connection:
            connection.sendall(request)
            connection.shutdown(socket.SHUT_WR)
            response = bytearray()
            while True:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                response.extend(chunk)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)

    response_text = response.decode("utf-8")
    assert " 400 " in response_text.split("\r\n", 1)[0]
    assert '"code": "incomplete_request_body"' in response_text


def test_studio_http_api_times_out_stalled_request_body(monkeypatch):
    from mardas_folio import gui

    monkeypatch.setattr(gui, "STUDIO_REQUEST_BODY_TIMEOUT_SECONDS", 0.05)
    server = ThreadingHTTPServer(("127.0.0.1", 0), gui.GuiRequestHandler)
    server.studio_bind_host = "127.0.0.1"  # type: ignore[attr-defined]
    server.studio_csrf_token = "secret"  # type: ignore[attr-defined]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = (
            "POST /api/render-html HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{server.server_port}\r\n"
            f"Origin: http://127.0.0.1:{server.server_port}\r\n"
            "Content-Type: application/json\r\n"
            "X-Mardas-Studio-Token: secret\r\n"
            "Content-Length: 10\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode("ascii")
        with socket.create_connection(("127.0.0.1", server.server_port), timeout=10) as connection:
            connection.sendall(request)
            response = bytearray()
            while True:
                chunk = connection.recv(4096)
                if not chunk:
                    break
                response.extend(chunk)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)

    response_text = response.decode("utf-8")
    assert " 408 " in response_text.split("\r\n", 1)[0]
    assert '"code": "request_body_timeout"' in response_text


def test_gui_wires_studio_api_token_into_render_fetches():
    html = GUI_HTML.read_text(encoding="utf-8")
    gui_source = (GUI_HTML.parents[1] / "gui.py").read_text(encoding="utf-8")

    assert "__MARDAS_STUDIO_TOKEN__" in html
    assert "function studioApiHeaders" in html
    assert "X-Mardas-Studio-Token" in html
    assert "headers: studioApiHeaders()" in html
    assert ".replace(\"__MARDAS_STUDIO_TOKEN__\", self._studio_csrf_token())" in gui_source
    assert "secrets.token_urlsafe(32)" in gui_source


def test_studio_http_api_rejects_cross_origin_render_post():
    from mardas_folio import gui

    server = ThreadingHTTPServer(("127.0.0.1", 0), gui.GuiRequestHandler)
    server.studio_bind_host = "127.0.0.1"  # type: ignore[attr-defined]
    server.studio_csrf_token = "secret"  # type: ignore[attr-defined]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        connection.request(
            "POST",
            "/api/render-html",
            body='{"markdown":"# Bad"}',
            headers={
                "Content-Type": "application/json",
                "Origin": "https://evil.example",
                "X-Mardas-Studio-Token": "secret",
            },
        )
        response = connection.getresponse()
        body = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)

    assert response.status == 403
    assert "untrusted_origin" in body


def test_studio_http_render_errors_are_logged_without_leaking_internal_details(monkeypatch, caplog):
    import json
    import logging

    from mardas_folio import gui

    sensitive_detail = "/tmp/private-project/secret.pdf"

    def fail_render(_payload: dict[str, object]) -> str:
        raise RuntimeError(f"renderer exploded at {sensitive_detail}")

    monkeypatch.setattr(gui, "_render_studio_html_payload", fail_render)
    caplog.set_level(logging.ERROR, logger=gui.__name__)

    server = ThreadingHTTPServer(("127.0.0.1", 0), gui.GuiRequestHandler)
    server.studio_bind_host = "127.0.0.1"  # type: ignore[attr-defined]
    server.studio_csrf_token = "secret"  # type: ignore[attr-defined]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        body = json.dumps({"markdown": "# Failure"})
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

    assert response.status == 500
    assert payload == {
        "error": "Studio rendering failed. Check the local Studio logs for details.",
        "status": 500,
        "code": "render_failed",
    }
    assert sensitive_detail not in payload["error"]
    assert "RuntimeError" not in payload["error"]
    assert sensitive_detail in caplog.text
    assert "Studio render failed for /api/render-html" in caplog.text


def test_studio_http_preview_requests_are_latest_only(monkeypatch):
    from mardas_folio import gui

    entered_old_render = Event()
    release_old_render = Event()

    def fake_render(payload: dict[str, object]) -> str:
        if payload.get("markdown") == "# Old":
            entered_old_render.set()
            assert release_old_render.wait(timeout=10)
            return "<html><body>old</body></html>"
        return "<html><body>new</body></html>"

    monkeypatch.setattr(gui, "_render_studio_html_payload", fake_render)

    server = ThreadingHTTPServer(("127.0.0.1", 0), gui.GuiRequestHandler)
    server.studio_bind_host = "127.0.0.1"  # type: ignore[attr-defined]
    server.studio_csrf_token = "secret"  # type: ignore[attr-defined]
    server.studio_preview_state_lock = Lock()  # type: ignore[attr-defined]
    server.studio_preview_render_lock = Lock()  # type: ignore[attr-defined]
    server.studio_latest_preview_ids = {}  # type: ignore[attr-defined]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    responses: dict[str, tuple[int, str]] = {}

    def post_preview(name: str, preview_id: str, markdown: str) -> None:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=20)
        try:
            connection.request(
                "POST",
                "/api/render-html",
                body='{"markdown":"' + markdown + '"}',
                headers={
                    "Content-Type": "application/json",
                    "Origin": f"http://127.0.0.1:{server.server_port}",
                    "X-Mardas-Studio-Token": "secret",
                    "X-Mardas-Studio-Client-Id": "same-client",
                    "X-Mardas-Studio-Preview-Id": preview_id,
                },
            )
            response = connection.getresponse()
            responses[name] = (response.status, response.read().decode("utf-8"))
        finally:
            connection.close()

    old_thread = Thread(target=post_preview, args=("old", "old-preview", "# Old"), daemon=True)
    new_thread = Thread(target=post_preview, args=("new", "new-preview", "# New"), daemon=True)
    try:
        old_thread.start()
        assert entered_old_render.wait(timeout=10)
        new_thread.start()
        deadline = time.monotonic() + 10
        while (
            getattr(server, "studio_latest_preview_ids", {}).get("same-client") != "new-preview"
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        assert getattr(server, "studio_latest_preview_ids", {}).get("same-client") == "new-preview"
        release_old_render.set()
        old_thread.join(timeout=20)
        new_thread.join(timeout=20)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)

    assert responses["old"][0] == 409
    assert "stale_preview" in responses["old"][1]
    assert responses["new"] == (200, "<html><body>new</body></html>")



def test_studio_html_preview_allows_empty_draft_but_pdf_export_still_requires_content():
    import pytest

    from mardas_folio import gui

    html = gui._render_studio_html_payload(
        {"markdown": "   ", "options": {"toc": False, "noCover": True}, "assets": []}
    )

    assert 'id="mardas-studio-preview-css"' in html
    assert "Markdown content is empty" not in html

    with pytest.raises(gui.StudioRequestError) as exc_info:
        gui._validate_studio_payload({"markdown": "   ", "options": {}, "assets": []})

    assert exc_info.value.code == "empty_markdown"


def test_studio_get_routes_ignore_query_strings():
    from mardas_folio import gui

    server = ThreadingHTTPServer(("127.0.0.1", 0), gui.GuiRequestHandler)
    server.studio_bind_host = "127.0.0.1"  # type: ignore[attr-defined]
    server.studio_csrf_token = "secret"  # type: ignore[attr-defined]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        connection.request("GET", "/index.html?v=cache-bust")
        response = connection.getresponse()
        body = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)

    assert response.status == 200
    assert "Mardas Folio" in body


def test_studio_safe_filenames_are_bounded_and_content_disposition_is_utf8_safe():
    from mardas_folio import gui

    filename = gui._safe_filename("x" * 240 + ".pdf")
    assert len(filename) <= gui.MAX_GUI_FILENAME_CHARS
    assert filename.endswith(".pdf")
    assert filename != "x" * 240 + ".pdf"

    rel_path = gui._safe_asset_relative_path("images/" + "نمودار" * 80 + ".png")
    assert len(rel_path.name) <= gui.MAX_GUI_ASSET_PATH_PART_CHARS
    assert rel_path.name.endswith(".png")

    disposition = gui._attachment_disposition("گزارش نهایی.pdf")
    assert 'filename="mardas-document.pdf"' in disposition
    assert "filename*=UTF-8''" in disposition
    disposition.encode("latin-1")


def test_gui_large_document_preview_and_local_save_warnings_are_explicit():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert "MAX_AUTO_ACCURATE_PREVIEW_CHARS" in html
    assert "MAX_FAST_PREVIEW_CHARS" in html
    assert "MAX_DEBUG_HTML_WARNING_CHARS" in html
    assert "function forceAccuratePreview" in html
    assert "Large draft · manual refresh" in html
    assert "Automatic PDF-like refresh is paused for large drafts" in html
    assert "Fast browser preview is skipped to keep Studio responsive" in html
    assert "Draft too large for local save" in html
    assert "Settings saved · draft too large for local save" in html
    assert "Refresh PDF-like preview" in html

def test_studio_bind_warning_only_for_non_local_hosts():
    from mardas_folio import gui

    assert gui._studio_bind_warning("127.0.0.1") is None
    assert gui._studio_bind_warning("localhost") is None
    assert gui._studio_bind_warning("::1") is None

    warning = gui._studio_bind_warning("0.0.0.0")
    assert warning is not None
    assert "non-local host" in warning
    assert "trusted networks" in warning


def test_gui_persists_studio_workspace_state():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert "MARDAS_STUDIO_STATE_KEY" in html
    assert "mardas-folio-studio-state-v1" in html
    assert "function loadStudioState" in html
    assert "function saveStudioState" in html
    assert "Reset State" in html
    assert "MAX_STORED_MARKDOWN_CHARS" in html
    assert "markdownTooLargeForLocalSave" in html
    assert "Settings saved · draft too large" in html


def test_gui_exposes_keyboard_shortcuts_for_local_workflow():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert "event.ctrlKey || event.metaKey" in html
    assert "downloadMarkdown();" in html
    assert "renderPDF();" in html


def test_gui_displays_structured_render_error_codes():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert "async function readRenderError" in html
    assert "payload.code" in html
    assert "Export failed (" in html



def test_studio_validates_render_options():
    import pytest

    from mardas_folio import gui

    options = gui._validated_render_options(
        {
            "tocDepth": "4",
            "watermarkOpacity": "0.35",
            "pageSize": "A4 landscape",
            "toc": "false",
            "noCover": "true",
        }
    )

    assert options["toc_depth"] == 4
    assert options["watermark_opacity"] == 0.35
    assert options["page_size"] == "A4 landscape"
    assert options["style"] == "modern"
    assert options["palette"] == "blue"
    assert options["mode"] == "light"
    assert options["branding"] == "off"
    assert options["toc"] is False
    assert options["cover"] is False

    custom = gui._validated_render_options({"style": "textbook", "palette": "emerald", "mode": "dark", "branding": "full"})
    assert custom["style"] == "textbook"
    assert custom["palette"] == "emerald"
    assert custom["mode"] == "dark"
    assert custom["branding"] == "full"

    for bad_options, code in [
        ({"tocDepth": "bad"}, "invalid_toc_depth"),
        ({"tocDepth": 9}, "invalid_toc_depth"),
        ({"watermarkOpacity": "bad"}, "invalid_watermark_opacity"),
        ({"watermarkOpacity": 1.9}, "invalid_watermark_opacity"),
        ({"pageSize": "not-a-size"}, "invalid_page_size"),
        ({"direction": "sideways"}, "invalid_direction"),
        ({"style": "textbook-dark"}, "invalid_style"),
        ({"palette": "neon"}, "invalid_palette"),
        ({"mode": "auto"}, "invalid_mode"),
        ({"branding": "loud"}, "invalid_branding"),
    ]:
        with pytest.raises(gui.StudioRequestError) as exc_info:
            gui._validated_render_options(bad_options)
        assert exc_info.value.status == 400
        assert exc_info.value.code == code


def test_gui_uses_appearance_controls_instead_of_theme_profile_controls():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert "styleInput" in html
    assert "paletteInput" in html
    assert "modeInput" in html
    assert "brandingInput" in html
    assert "brandNameInput" in html
    assert "brandLogoInput" in html
    assert "brandFooterInput" in html
    assert "appearanceName" in html
    assert "pdfThemeInput" not in html
    assert "profileName" not in html
    assert "--theme" not in html
    assert "--style" in html
    assert "--palette" in html
    assert "--mode" in html


def test_gui_groups_export_settings_into_user_facing_sections():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert "Document<small>Basic identity and page setup</small>" in html
    assert "Appearance<small>Shape, color, and light/dark output</small>" in html
    assert "Branding<small>Keep output owned by the document</small>" in html
    assert "Layout<small>TOC, cover, and page flow</small>" in html
    assert 'class="choice-title"' in html
    assert "#icon-settings" in html


def test_gui_uses_visual_choice_cards_for_appearance_workflow():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert 'data-choice-group="style"' in html
    assert 'data-choice-value="modern"' in html
    assert 'data-choice-value="academic"' in html
    assert 'data-choice-group="palette"' in html
    assert 'class="palette-dot"' in html
    assert 'data-choice-group="mode"' in html
    assert 'data-choice-group="branding"' in html
    assert "function attachChoiceCards" in html
    assert "function syncChoiceCards" in html


def test_gui_copy_command_includes_branding_options():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert "--branding" in html
    assert "--brand-name" in html
    assert "--brand-logo" in html
    assert "--brand-footer" in html


def test_gui_replaces_static_view_modes_with_resizable_panes():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert 'id="settingsGutter"' in html
    assert 'id="previewGutter"' in html
    assert 'id="settingsRestoreBtn"' in html
    assert 'function resizeSettingsPane' in html
    assert 'function resizePreviewPane' in html
    assert 'function collapseSettingsPane' in html
    assert 'function expandSettingsPane' in html
    assert 'SETTINGS_COLLAPSE_THRESHOLD' in html
    assert 'settingsCollapsed' in html
    assert 'layoutSplit' not in html
    assert 'layoutEditor' not in html
    assert 'layoutPreview' not in html
    assert 'layoutZen' not in html
    assert 'zenToolbar' not in html


def test_gui_topbar_uses_grouped_toolbar_and_icon_buttons():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert 'role="toolbar" aria-label="Studio toolbar"' in html
    assert 'class="tool-group" aria-label="File actions"' in html
    assert 'class="tool-group" aria-label="Resources"' in html
    assert 'class="tool-group" aria-label="Export"' in html
    assert 'class="tool-group" aria-label="View mode"' not in html
    assert 'class="tool-divider"' in html
    assert 'class="btn btn-icon btn-quiet" onclick="copyCommand()"' in html
    assert 'id="interfaceBtn" title="Switch to light Studio UI"' in html




def test_gui_uses_inline_svg_icons_and_project_vector_brand_mark():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert 'class="icon-sprite"' in html
    assert 'href="#icon-folder-open"' in html
    assert 'href="#icon-save"' in html
    assert 'href="#icon-file-down"' in html
    assert 'href="#icon-bold"' in html
    assert 'href="#icon-table"' in html
    assert '<span class="brand-mark" aria-hidden="true"></span>' in html
    assert '/assets/mardas-folio-mark-gui-mask.svg' in html
    assert 'background:currentColor' in html
    assert '-webkit-mask:url("/assets/mardas-folio-mark-gui-mask.svg") center/contain no-repeat' in html
    assert 'stroke-width:1.8' in html


def test_gui_has_no_emoji_icon_glyphs():
    html = GUI_HTML.read_text(encoding="utf-8")
    emoji_codepoints = [
        0x1F4C2, 0x1F4BE, 0x1F5BC, 0x2600, 0x1F319, 0x1F4CC, 0x1F3A8,
        0x1F3F7, 0x1F9ED, 0x2699, 0x1F4C4, 0x1F517, 0x2705,
    ]
    for codepoint in emoji_codepoints:
        assert chr(codepoint) not in html


def test_gui_microinteractions_use_stable_numeric_and_soft_cards():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert 'font-variant-numeric:tabular-nums' in html
    assert '.choice-copy{color:color-mix' in html
    assert 'body:not(.light-mode) .choice-copy{color:#d0d0d0}' in html
    assert '.format-btn{height:30px' in html
    assert '--muted:#b3b3b3' in html
    assert '--faint:#9a9a9a' in html
    assert '.editor-formatbar{gap:6px' in html
    assert 'border-color:transparent;background:transparent' in html

def test_gui_uses_chatgpt_like_scrollbars_and_pure_interface_surfaces():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert '*::-webkit-scrollbar' in html
    assert '--scroll-thumb:#4a4a4a' in html
    assert '--scroll-thumb:#cbd5e1' in html
    assert '--bg:#000000' in html
    assert '--panel-2:#212121' in html
    assert '--panel:#ffffff' in html
    assert '--preview:#ffffff' in html


def test_gui_export_button_keeps_contrast_on_hover_and_active():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert '.btn-primary:hover{color:#ffffff' in html
    assert '.btn-primary:active{color:#ffffff' in html
    assert '.btn-primary:focus-visible' in html


def test_gui_settings_are_accordion_sections_with_switches():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert 'class="card settings-section" open' in html
    assert '#icon-palette' in html
    assert '#icon-badge' in html
    assert '#icon-compass' in html
    assert '<details class="card settings-section" open><summary>' in html
    assert 'interpolate-size:allow-keywords' in html
    assert 'class="switch"><span>Generate table of contents</span>' in html
    assert 'class="switch"><span>Hide footer/page number</span>' in html


def test_gui_editor_has_formatting_toolbar_line_numbers_and_sync_scroll():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert 'class="editor-formatbar" aria-label="Markdown formatting toolbar"' in html
    assert "onclick=\"insertMarkdown('bold')\"" in html
    assert "onclick=\"insertMarkdown('table')\"" in html
    assert 'id="lineNumbers" class="line-numbers"' in html
    assert 'id="lineNumberContent" class="line-number-content"' in html
    assert 'function insertMarkdown' in html
    assert 'function syncLineNumbers' in html
    assert 'function scheduleLineNumberSync' in html
    assert 'function countTextLines' in html
    assert 'function syncFramePreviewScroll' not in html
    assert "activePreviewMode() !== 'fast'" in html
    assert 'function syncPreviewScroll' in html
    assert 'function schedulePreviewScrollSync' in html
    assert "editor.addEventListener('scroll'" in html


def test_gui_preview_exposes_render_status_and_footer_save_state():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert 'id="previewStatus" class="preview-status"' in html
    assert 'function setPreviewStatus' in html
    assert 'function schedulePreviewRender' in html
    assert "setPreviewStatus('Updating preview...', true)" in html
    assert "setPreviewStatus('Ready', false)" in html
    assert '<span id="savedState">Live preview</span>' in html
    assert 'Markdown source' in html


def test_gui_has_toast_feedback_region_and_stable_status_helpers():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert 'id="toastRegion" class="toast-region"' in html
    assert 'aria-live="polite"' in html
    assert 'function notify(message' in html
    assert 'function setServerStatus' in html
    assert '.toast.show' in html
    assert "setServerStatus('CLI command copied'" in html


def test_gui_sidebar_scrolls_and_palette_uses_compact_swatches():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert '.sidebar{height:100%;display:flex;flex-direction:column;overflow:hidden' in html
    assert '.sidebar-body{display:block;flex:1 1 auto;min-height:0;padding:16px;overflow-y:auto;overflow-x:hidden' in html
    assert '.palette-grid{display:flex;align-items:center;gap:8px;flex-wrap:wrap' in html
    assert '.palette-card{position:relative;display:inline-grid;place-items:center;width:34px;height:34px' in html
    assert 'title="Blue palette" aria-label="Blue palette"' in html
    assert '.palette-card > span:not(.palette-dot)' in html


def test_gui_logo_uses_contain_fit_with_breathing_room():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert '.brand-mark{overflow:visible;background:transparent' in html
    assert '.brand-mark::before{content:"";width:100%;height:100%;display:block;background:currentColor' in html
    assert 'mask:url("/assets/mardas-folio-mark-gui-mask.svg") center/contain no-repeat' in html
    assert 'body.light-mode .brand-mark{background:transparent;border:0;box-shadow:none}' in html


def test_studio_project_files_roundtrip_workspace_state():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert "MARDAS_PROJECT_SCHEMA" in html
    assert "mardas-folio-studio-project-v1" in html
    assert "function buildProjectBundle" in html
    assert "function applyProjectBundle" in html
    assert "function downloadProject" in html
    assert "function openProject" in html
    assert 'id="projectInput"' in html
    assert ".mardas.json" in html
    assert "schema: MARDAS_PROJECT_SCHEMA" in html
    assert "assets: attachedAssets.map" in html


def test_studio_file_toolbar_exposes_new_project_workflow():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert "onclick=\"newDocument()\"" in html
    assert "Open MD" in html
    assert "Open Bundle" in html
    assert "Save Bundle" in html
    assert "DEFAULT_MARKDOWN" in html
    assert "editor.value = DEFAULT_MARKDOWN;" in html


def test_studio_asset_manager_supports_drag_drop_and_asset_actions():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert 'id="assetSummary"' in html
    assert 'id="dropZone" class="drop-zone"' in html
    assert "function handleAssetFiles" in html
    assert "function readAssetFile" in html
    assert "function removeAsset" in html
    assert "function clearAssets" in html
    assert "function setBrandLogoFromAsset" in html
    assert "window.addEventListener('dragover'" in html
    assert "window.addEventListener('drop'" in html
    assert "body.asset-dragging .drop-zone" in html
    assert "duplicate/over limit" in html
    assert "MAX_PROJECT_BUNDLE_BYTES" in html
    assert "function validateProjectAssets" in html
    assert "normalizeBundleAssetPath" in html
    assert "unsafe/oversized assets" in html




def test_studio_project_bundle_loader_validates_embedded_assets():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert "function validateProjectAssets(rawAssets)" in html
    assert "estimatedDataUrlBytes" in html
    assert "data.startsWith('data:')" in html
    assert "parts.includes('..')" in html
    assert "seen.has(path)" in html
    assert "MAX_GUI_TOTAL_ASSET_BYTES" in html
    assert "MAX_PROJECT_BUNDLE_BYTES" in html
    assert "Project file too large" in html
    assert "unsafe/oversized assets" in html


def test_studio_supports_fast_accurate_preview_and_debug_html_export():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert 'id="previewModeInput"' in html
    assert '<option value="accurate" selected>PDF-like</option>' in html
    assert '<option value="pdf">' not in html
    assert '<option value="fast">Fast (approx)</option>' in html
    assert 'id="accuratePreviewFrame"' in html
    assert "function requestAccuratePreview" in html
    assert "function renderFastPreview" in html
    assert "function exportDebugHTML" in html
    assert "fetch('/api/render-html'" in html
    assert "Debug HTML downloaded" in html


def test_studio_backend_exposes_renderer_html_endpoint_contract():
    source = (GUI_HTML.parents[1] / "gui.py").read_text(encoding="utf-8")

    assert '"/api/render-html"' in source
    assert "def _render_studio_html_payload" in source
    assert "build_html(" in source
    assert "render_markdown_file(" in source
    assert "code_style_for_appearance" in source


def test_studio_exposes_command_palette_and_professional_shortcuts():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert 'id="commandPaletteBackdrop"' in html
    assert 'id="commandPaletteInput"' in html
    assert "const COMMANDS = [" in html
    assert "function openCommandPalette" in html
    assert "function closeCommandPalette" in html
    assert "function runCommand" in html
    assert "function setCommandPaletteActive" in html
    assert "function activeCommandPaletteId" in html
    assert "ArrowDown" in html
    assert "ArrowUp" in html
    assert "aria-selected" in html
    assert "key === 'k'" in html
    assert "key === 'o'" in html
    assert "key === 'e'" in html
    assert "Ctrl/Cmd+Shift+S" in html
    assert "command-palette-open" in html
    assert "Use PDF-like preview" in html
    assert "Use fast approximate preview" in html
    assert "Use exact PDF preview" not in html
    assert "Open Studio bundle" in html


def test_studio_first_run_state_is_not_reported_as_error():
    html = GUI_HTML.read_text(encoding="utf-8")

    assert "$('savedState').textContent = 'Ready';" in html
    assert "Could not restore state" not in html
    assert "Saved state ignored" not in html
    assert "localStorage.removeItem(MARDAS_STUDIO_STATE_KEY)" in html


def test_studio_exposes_and_validates_publication_quality_controls():
    import pytest

    from mardas_folio import gui

    html = GUI_HTML.read_text(encoding="utf-8")
    for control in (
        "qualityProfileInput",
        "mathErrorPolicyInput",
        "fontErrorPolicyInput",
        "navigationErrorPolicyInput",
        "requiredFontsInput",
    ):
        assert f'id="{control}"' in html
    assert "--quality-profile" in html
    assert "--require-font" in html

    options = gui._validated_render_options(
        {
            "qualityProfile": "strict-publication",
            "mathErrorPolicy": "error",
            "fontErrorPolicy": "warn",
            "navigationErrorPolicy": "ignore",
            "requiredFonts": "Vazirmatn, JetBrains Mono, Vazirmatn",
        }
    )
    assert options["quality_profile"] == "strict-publication"
    assert options["math_error_policy"] == "error"
    assert options["font_error_policy"] == "warn"
    assert options["navigation_error_policy"] == "ignore"
    assert options["required_fonts"] == ("Vazirmatn", "JetBrains Mono")

    with pytest.raises(gui.StudioRequestError) as exc_info:
        gui._validated_render_options({"qualityProfile": "maximum"})
    assert exc_info.value.code == "invalid_quality_profile"

    with pytest.raises(gui.StudioRequestError) as exc_info:
        gui._validated_render_options({"mathErrorPolicy": "continue"})
    assert exc_info.value.code == "invalid_math_error_policy"

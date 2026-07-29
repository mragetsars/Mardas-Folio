from __future__ import annotations

from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from threading import Event, Thread
import time

from mardas_md2pdf import gui
from mardas_md2pdf.studio_jobs import StudioExportManager


def _start_server(*, workers: int = 1, queue_size: int = 2):
    server = ThreadingHTTPServer(("127.0.0.1", 0), gui.GuiRequestHandler)
    server.studio_bind_host = "127.0.0.1"  # type: ignore[attr-defined]
    server.studio_csrf_token = "secret"  # type: ignore[attr-defined]
    server.studio_export_manager = StudioExportManager(  # type: ignore[attr-defined]
        workers=workers,
        queue_size=queue_size,
        idle_timeout=10,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_server(server, thread) -> None:
    manager = server.studio_export_manager  # type: ignore[attr-defined]
    server.shutdown()
    manager.close()
    server.server_close()
    thread.join(timeout=10)


def _headers(server) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Origin": f"http://127.0.0.1:{server.server_port}",
        "X-Mardas-Studio-Token": "secret",
        "X-Mardas-Studio-Client-Id": "test-client",
    }


def _request(server, method: str, path: str, payload: dict | None = None):
    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=20)
    body = json.dumps(payload if payload is not None else {}) if method == "POST" else None
    connection.request(method, path, body=body, headers=_headers(server))
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, response.getheaders(), data


def _wait_for_terminal(server, status_url: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status, _headers_list, data = _request(server, "GET", status_url)
        assert status == 200
        payload = json.loads(data)
        if payload["status"] in {"succeeded", "failed", "cancelled"}:
            return payload
        time.sleep(0.02)
    raise AssertionError("export job did not finish")


def test_export_job_reports_progress_and_streams_result(monkeypatch) -> None:
    session_ids: list[int] = []

    def fake_render(
        directory: Path,
        *,
        markdown: str,
        options,
        assets,
        render_options,
        filename: str,
        session,
        progress,
        cancelled,
    ) -> Path:
        session_ids.append(id(session))
        progress("Parsing Markdown", 0.2)
        progress("Rendering PDF", 0.8)
        output = directory / filename
        output.write_bytes(b"%PDF-1.7\nqueued\n")
        (directory / "quality-report.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "profile": "strict-publication",
                    "ok": True,
                    "summary": {"passed": 3, "warning": 0, "error": 0},
                    "events": [{"category": "mathjax", "status": "passed"}],
                }
            ),
            encoding="utf-8",
        )
        return output

    monkeypatch.setattr(gui, "_render_studio_document_export", fake_render)
    server, thread = _start_server()
    try:
        status, _headers_list, data = _request(
            server,
            "POST",
            "/api/export-jobs",
            {"kind": "document", "markdown": "# Report", "options": {"filename": "report.pdf"}},
        )
        created = json.loads(data)
        assert status == 202
        assert created["job_id"] in created["status_url"]
        assert created["job_id"] in created["cancel_url"]
        terminal = _wait_for_terminal(server, created["status_url"])
        assert terminal["status"] == "succeeded"
        assert terminal["progress"] == 1.0
        assert terminal["queue_wait_ms"] is not None
        assert terminal["render_ms"] is not None
        assert terminal["quality"]["ok"] is True
        assert terminal["quality"]["profile"] == "strict-publication"
        assert terminal["quality"]["summary"]["passed"] == 3

        original_read_bytes = Path.read_bytes

        def reject_pdf_read_bytes(path: Path) -> bytes:
            if path.suffix == ".pdf":
                raise AssertionError("PDF results must be streamed instead of loaded into memory")
            return original_read_bytes(path)

        monkeypatch.setattr(Path, "read_bytes", reject_pdf_read_bytes)
        result_status, headers, result = _request(server, "GET", terminal["result_url"])
        assert result_status == 200
        assert result == b"%PDF-1.7\nqueued\n"
        assert "report.pdf" in dict(headers)["Content-Disposition"]

        status, _headers_list, data = _request(
            server,
            "POST",
            "/api/export-jobs",
            {"kind": "document", "markdown": "# Second", "options": {"filename": "two.pdf"}},
        )
        second = json.loads(data)
        assert status == 202
        assert _wait_for_terminal(server, second["status_url"])["status"] == "succeeded"
        assert session_ids[0] == session_ids[1]
    finally:
        _stop_server(server, thread)


def test_export_job_cancels_queued_work(monkeypatch) -> None:
    entered = Event()
    release = Event()
    executed_second = Event()

    def fake_render(
        directory: Path,
        *,
        markdown: str,
        options,
        assets,
        render_options,
        filename: str,
        session,
        progress,
        cancelled,
    ) -> Path:
        if "First" in markdown:
            entered.set()
            assert release.wait(timeout=10)
        else:
            executed_second.set()
        output = directory / filename
        output.write_bytes(b"%PDF-1.7\n")
        return output

    monkeypatch.setattr(gui, "_render_studio_document_export", fake_render)
    server, thread = _start_server(workers=1, queue_size=2)
    try:
        first_status, _, first_data = _request(
            server,
            "POST",
            "/api/export-jobs",
            {"kind": "document", "markdown": "# First", "options": {}},
        )
        assert first_status == 202
        assert entered.wait(timeout=5)
        second_status, _, second_data = _request(
            server,
            "POST",
            "/api/export-jobs",
            {"kind": "document", "markdown": "# Second", "options": {}},
        )
        assert second_status == 202
        second = json.loads(second_data)
        cancel_status, _, _cancel_data = _request(server, "POST", second["cancel_url"], {})
        assert cancel_status == 202
        terminal = _wait_for_terminal(server, second["status_url"])
        assert terminal["status"] == "cancelled"
        assert terminal["code"] == "render_cancelled"
        assert not executed_second.is_set()
        release.set()
        first = json.loads(first_data)
        assert _wait_for_terminal(server, first["status_url"])["status"] == "succeeded"
    finally:
        release.set()
        _stop_server(server, thread)


def test_export_job_queue_returns_429_when_bounded_queue_is_full(monkeypatch) -> None:
    entered = Event()
    release = Event()

    def fake_render(
        directory: Path,
        *,
        markdown: str,
        options,
        assets,
        render_options,
        filename: str,
        session,
        progress,
        cancelled,
    ) -> Path:
        if "First" in markdown:
            entered.set()
            assert release.wait(timeout=10)
        output = directory / filename
        output.write_bytes(b"%PDF-1.7\n")
        return output

    monkeypatch.setattr(gui, "_render_studio_document_export", fake_render)
    server, thread = _start_server(workers=1, queue_size=1)
    try:
        assert _request(
            server,
            "POST",
            "/api/export-jobs",
            {"kind": "document", "markdown": "# First", "options": {}},
        )[0] == 202
        assert entered.wait(timeout=5)
        assert _request(
            server,
            "POST",
            "/api/export-jobs",
            {"kind": "document", "markdown": "# Queued", "options": {}},
        )[0] == 202
        status, _, data = _request(
            server,
            "POST",
            "/api/export-jobs",
            {"kind": "document", "markdown": "# Rejected", "options": {}},
        )
        assert status == 429
        assert json.loads(data)["code"] == "export_queue_full"
    finally:
        release.set()
        _stop_server(server, thread)


def test_export_job_api_requires_studio_token() -> None:
    server, thread = _start_server()
    try:
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        connection.request(
            "POST",
            "/api/export-jobs",
            body='{"kind":"document","markdown":"# Bad"}',
            headers={
                "Content-Type": "application/json",
                "Origin": f"http://127.0.0.1:{server.server_port}",
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        assert response.status == 403
        assert payload["code"] == "invalid_studio_token"
    finally:
        _stop_server(server, thread)

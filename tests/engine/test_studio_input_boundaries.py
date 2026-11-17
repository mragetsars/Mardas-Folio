from __future__ import annotations

import json
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from threading import Thread

import pytest

from mardas_folio import gui


@pytest.mark.parametrize(
    "host",
    [
        "127.evil.example:8765",
        "127.0.0.1.evil.example:8765",
        "localhost.evil.example:8765",
        "user@127.0.0.1:8765",
        "127.0.0.1:8765/path",
        "127.0.0.1:8765?query",
        "127.0.0.1:8765#fragment",
        "127.0.0.1:invalid",
        "[::1]junk:8765",
        "[::1]junk",
        "::1",
        "127.0.0.1:",
        "[::1",
        "127.0.0.1 :8765",
    ],
)
def test_local_studio_rejects_rebinding_and_malformed_hosts(host: str) -> None:
    assert not gui._host_header_is_trusted(host, "127.0.0.1")


@pytest.mark.parametrize("host", ["localhost", "localhost:8765", "127.0.0.1:8765", "127.8.4.2", "[::1]:8765"])
def test_local_studio_accepts_loopback_authorities(host: str) -> None:
    assert gui._host_header_is_trusted(host, "127.0.0.1")


def test_rebinding_host_cannot_obtain_studio_token_or_use_api() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), gui.GuiRequestHandler)
    server.studio_bind_host = "127.0.0.1"  # type: ignore[attr-defined]
    server.studio_csrf_token = "private-token-value"  # type: ignore[attr-defined]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        for method, path, body in [("GET", "/", None), ("POST", "/api/render-html", "{}")]:
            connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            try:
                connection.request(
                    method,
                    path,
                    body=body,
                    headers={
                        "Host": f"127.evil.example:{server.server_port}",
                        "Origin": f"http://127.evil.example:{server.server_port}",
                        "Content-Type": "application/json",
                        "X-Mardas-Studio-Token": "private-token-value",
                    },
                )
                response = connection.getresponse()
                raw = response.read()
                assert response.status == 403
                assert json.loads(raw)["code"] == "untrusted_host"
                assert b"private-token-value" not in raw
            finally:
                connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e99999", "9" * 5000])
def test_studio_rejects_nonfinite_or_oversized_json_numbers(number: str) -> None:
    with pytest.raises(gui.StudioRequestError) as error:
        gui._decode_json_payload(('{"value":' + number + "}").encode())
    assert error.value.status == 400
    assert error.value.code == "invalid_json"


def test_studio_deep_json_returns_client_error() -> None:
    with pytest.raises(gui.StudioRequestError) as error:
        gui._decode_json_payload(b'{"value":' + b"[" * 10000 + b"]" * 10000 + b"}")
    assert error.value.code == "invalid_json"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("markdown", 123, "invalid_markdown"),
        ("markdown", None, "invalid_markdown"),
        ("markdown", "\ud800", "invalid_encoding"),
        ("options", [], "invalid_options"),
        ("options", None, "invalid_options"),
        ("assets", {}, "invalid_assets"),
        ("assets", None, "invalid_assets"),
    ],
)
def test_studio_rejects_invalid_payload_fields(field: str, value: object, code: str) -> None:
    payload: dict[str, object] = {"markdown": "# Report"}
    payload[field] = value
    with pytest.raises(gui.StudioRequestError) as error:
        gui._validate_studio_payload(payload)
    assert error.value.status == 400
    assert error.value.code == code

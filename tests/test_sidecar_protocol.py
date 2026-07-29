from __future__ import annotations

import io
import json
import os
import threading
import time
from pathlib import Path

import pytest

from mardas_md2pdf import application, protocol, runtime, sidecar
from mardas_md2pdf.application import EngineError


def _lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line.strip()]


def test_protocol_parses_a_valid_request() -> None:
    request = protocol.parse_request(
        {"jsonrpc": "2.0", "id": "job-1", "method": "system.health", "params": {}}
    )
    assert request.request_id == "job-1"
    assert request.method == "system.health"
    assert request.params == {}


@pytest.mark.parametrize(
    "payload,code",
    [
        ([], protocol.INVALID_REQUEST),
        ({"jsonrpc": "1.0", "id": 1, "method": "x"}, protocol.INVALID_REQUEST),
        ({"jsonrpc": "2.0", "id": None, "method": "x"}, protocol.INVALID_REQUEST),
        ({"jsonrpc": "2.0", "id": 1, "method": "x", "params": []}, protocol.INVALID_PARAMS),
    ],
)
def test_protocol_rejects_invalid_requests(payload: object, code: int) -> None:
    with pytest.raises(protocol.ProtocolError) as caught:
        protocol.parse_request(payload)
    assert caught.value.code == code


def test_runtime_chromium_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = tmp_path / ("chrome.exe" if os.name == "nt" else "chrome")
    executable.write_bytes(b"browser")
    monkeypatch.setenv("MARDAS_CHROMIUM_PATH", str(executable))
    assert runtime.bundled_chromium_path() == executable.resolve()


def test_pdf_options_request_rejects_unknown_fields(tmp_path: Path) -> None:
    source = tmp_path / "doc.md"
    source.write_text("# Title\n", encoding="utf-8")
    with pytest.raises(EngineError) as caught:
        application.pdf_options_from_request(
            input_path=source,
            options={"not_a_real_option": True},
        )
    assert caught.value.code == "MARDAS-INVALID-PARAMS"
    assert caught.value.details["unknown_options"] == ["not_a_real_option"]


def test_pdf_options_request_merges_project_config_and_explicit_values(tmp_path: Path) -> None:
    source = tmp_path / "doc.md"
    source.write_text("# Title\n", encoding="utf-8")
    (tmp_path / "mardas.toml").write_text(
        """schema_version = 1
[output]
toc = true
cover = false
[appearance]
style = "academic"
""",
        encoding="utf-8",
    )
    options = application.pdf_options_from_request(
        input_path=source,
        options={"toc": False, "palette": "green"},
    )
    assert options.toc is False
    assert options.cover is False
    assert options.style == "academic"
    assert options.palette == "green"


def test_sidecar_health_and_shutdown_round_trip() -> None:
    requests = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "system.health", "params": {}}),
            json.dumps(
                {"jsonrpc": "2.0", "id": 2, "method": "system.shutdown", "params": {}}
            ),
        ]
    ) + "\n"
    output = io.StringIO()
    server = sidecar.SidecarServer(stdin=io.BytesIO(requests.encode()), stdout=output)
    assert server.run() == 0
    messages = _lines(output)
    assert messages[0]["method"] == "system.ready"
    assert messages[1]["id"] == 1
    assert messages[1]["result"]["status"] == "ok"
    assert messages[2] == {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {"shutting_down": True},
    }


def test_sidecar_reports_progress_and_result(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeService:
        def health(self) -> dict[str, object]:
            return {"status": "ok"}

        def capabilities(self) -> dict[str, object]:
            return {"methods": []}

        def dispatch(self, method: str, params: object, *, progress=None, cancelled=None):
            assert method == "validate.document"
            assert cancelled is not None and not cancelled()
            progress("Parsing", 0.25)
            progress("Done", 1.0)
            return {"ok": True}

        def close(self) -> None:
            return None

    monkeypatch.setattr(sidecar, "EngineService", FakeService)
    requests = "\n".join(
        [
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "validate-1",
                    "method": "validate.document",
                    "params": {"input_path": "doc.md"},
                }
            ),
        ]
    ) + "\n"
    output = io.StringIO()
    server = sidecar.SidecarServer(stdin=io.BytesIO(requests.encode()), stdout=output)
    assert server.run() == 0
    messages = _lines(output)
    progress = [item for item in messages if item.get("method") == "job.progress"]
    assert [item["params"]["sequence"] for item in progress] == [1, 2]
    result = next(item for item in messages if item.get("id") == "validate-1")
    assert result["result"] == {"ok": True}


def test_sidecar_cancels_an_active_job(monkeypatch: pytest.MonkeyPatch) -> None:
    started = threading.Event()

    class FakeService:
        def health(self) -> dict[str, object]:
            return {"status": "ok"}

        def capabilities(self) -> dict[str, object]:
            return {"methods": []}

        def dispatch(self, method: str, params: object, *, progress=None, cancelled=None):
            started.set()
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                if cancelled is not None and cancelled():
                    from mardas_md2pdf.renderer import RenderCancelledError

                    raise RenderCancelledError("cancelled by test")
                time.sleep(0.005)
            return {"unexpected": True}

        def close(self) -> None:
            return None

    monkeypatch.setattr(sidecar, "EngineService", FakeService)
    read_stream, write_stream = os.pipe()
    stdin = os.fdopen(read_stream, "rb", buffering=0)
    output = io.StringIO()
    server = sidecar.SidecarServer(stdin=stdin, stdout=output)
    thread = threading.Thread(target=server.run)
    thread.start()
    writer = os.fdopen(write_stream, "wb", buffering=0)
    try:
        writer.write(
            (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "render-1",
                        "method": "render.document",
                        "params": {"input_path": "doc.md"},
                    }
                )
                + "\n"
            ).encode()
        )
        assert started.wait(timeout=1)
        writer.write(
            (
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "cancel-1",
                        "method": "job.cancel",
                        "params": {"request_id": "render-1"},
                    }
                )
                + "\n"
            ).encode()
        )
        writer.close()
        thread.join(timeout=3)
        assert not thread.is_alive()
    finally:
        if not writer.closed:
            writer.close()
        stdin.close()
    messages = _lines(output)
    cancellation = next(item for item in messages if item.get("id") == "cancel-1")
    assert cancellation["result"]["cancel_requested"] is True
    failed = next(item for item in messages if item.get("id") == "render-1")
    assert failed["error"]["code"] == protocol.JOB_CANCELLED


@pytest.mark.parametrize(
    "payload,error_fragment",
    [
        (
            {"jsonrpc": "2.0", "id": "health", "method": "system.health", "params": {"x": 1}},
            "Unknown parameters",
        ),
        (
            {
                "jsonrpc": "2.0",
                "id": "shutdown",
                "method": "system.shutdown",
                "params": {"force": "yes"},
            },
            "must be a boolean",
        ),
        (
            {
                "jsonrpc": "2.0",
                "id": "cancel",
                "method": "job.cancel",
                "params": {"request_id": True},
            },
            "requires a string or integer",
        ),
    ],
)
def test_sidecar_rejects_invalid_system_parameters(
    payload: dict[str, object], error_fragment: str
) -> None:
    requests = json.dumps(payload) + "\n"
    output = io.StringIO()
    server = sidecar.SidecarServer(stdin=io.BytesIO(requests.encode()), stdout=output)
    assert server.run() == 0
    response = next(item for item in _lines(output) if item.get("id") == payload["id"])
    assert response["error"]["code"] == protocol.INVALID_PARAMS
    assert error_fragment in response["error"]["message"]


def test_sidecar_drains_an_oversized_request_before_parsing_the_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sidecar, "MAX_REQUEST_BYTES", 96)
    oversized = b"{" + (b"x" * 192) + b"}\n"
    valid = (
        json.dumps(
            {"jsonrpc": "2.0", "id": "health", "method": "system.health", "params": {}}
        ).encode()
        + b"\n"
    )
    output = io.StringIO()
    server = sidecar.SidecarServer(stdin=io.BytesIO(oversized + valid), stdout=output)
    assert server.run() == 0
    messages = _lines(output)
    errors = [item for item in messages if item.get("error")]
    assert len(errors) == 1
    assert errors[0]["error"]["code"] == protocol.PARSE_ERROR
    health = next(item for item in messages if item.get("id") == "health")
    assert health["result"]["status"] == "ok"

from __future__ import annotations

import asyncio
import io
import json
import os
import threading
import time
from pathlib import Path

import pytest

from mardas_folio import application, protocol, runtime, sidecar
from mardas_folio.application import EngineError


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


def test_playwright_probe_never_nests_an_asyncio_event_loop() -> None:
    async def probe() -> Path | None:
        return runtime.playwright_chromium_path()

    assert asyncio.run(probe()) is None


def test_runtime_chromium_resolution_is_cached_and_thread_safe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / ("chrome.exe" if os.name == "nt" else "chrome")
    executable.write_bytes(b"browser")
    bundled_calls = 0
    playwright_calls = 0
    counter_lock = threading.Lock()

    def no_bundled_browser() -> None:
        nonlocal bundled_calls
        with counter_lock:
            bundled_calls += 1
        return None

    def playwright_browser() -> Path:
        nonlocal playwright_calls
        with counter_lock:
            playwright_calls += 1
        time.sleep(0.03)
        return executable

    runtime._clear_chromium_resolution_cache()
    monkeypatch.setattr(runtime, "bundled_chromium_path", no_bundled_browser)
    monkeypatch.setattr(runtime, "playwright_chromium_path", playwright_browser)
    barrier = threading.Barrier(8)
    results: list[Path | None] = [None] * 8

    def resolve(index: int) -> None:
        barrier.wait(timeout=2)
        results[index] = runtime.resolved_chromium_path()

    threads = [threading.Thread(target=resolve, args=(index,)) for index in range(8)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        assert all(not thread.is_alive() for thread in threads)
        assert results == [executable] * len(results)
        assert bundled_calls == 1
        assert playwright_calls == 1
    finally:
        runtime._clear_chromium_resolution_cache()


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
        options={"toc": False, "palette": "emerald"},
    )
    assert options.toc is False
    assert options.cover is False
    assert options.style == "academic"
    assert options.palette == "emerald"




def test_desktop_project_methods_are_allowed_sidecar_jobs() -> None:
    expected = {
        "document.read_text",
        "document.save_text",
        "project.open",
        "project.refresh",
        "project.read",
        "project.save",
        "project.search",
        "bibliography.index",
    }
    assert expected.issubset(sidecar._HEAVY_METHODS)


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
                    from mardas_folio.renderer import RenderCancelledError

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


@pytest.mark.parametrize(
    "invalid_request",
    [
        b'{"jsonrpc":"2.0","id":' + (b"9" * 5_000) + b',"method":"system.health"}\n',
        (b"[" * 10_000) + b"0" + (b"]" * 10_000) + b"\n",
        b'{"jsonrpc":"2.0","id":NaN,"method":"system.health"}\n',
        b'{"jsonrpc":"2.0","id":1e999,"method":"system.health"}\n',
    ],
    ids=["huge-integer", "deep-nesting", "nan", "float-overflow"],
)
def test_sidecar_recovers_from_json_decoder_value_failures(
    invalid_request: bytes,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeService:
        def health(self) -> dict[str, object]:
            return {"status": "ok"}

        def close(self) -> None:
            return None

    monkeypatch.setattr(sidecar, "EngineService", FakeService)
    valid = (
        json.dumps(
            {"jsonrpc": "2.0", "id": "health", "method": "system.health", "params": {}}
        ).encode()
        + b"\n"
    )
    output = io.StringIO()
    server = sidecar.SidecarServer(stdin=io.BytesIO(invalid_request + valid), stdout=output)

    assert server.run() == 0

    messages = _lines(output)
    errors = [item for item in messages if item.get("error")]
    assert len(errors) == 1
    assert errors[0]["error"]["code"] == protocol.PARSE_ERROR
    health = next(item for item in messages if item.get("id") == "health")
    assert health["result"]["status"] == "ok"


def test_json_line_writer_never_emits_non_standard_numbers() -> None:
    output = io.StringIO()
    sidecar._JsonLineWriter(output).write(
        protocol.success_response("preview", {"metadata": {"score": float("nan")}})
    )

    def reject_constant(value: str) -> None:
        raise AssertionError(f"non-standard JSON constant: {value}")

    payload = json.loads(output.getvalue(), parse_constant=reject_constant)
    assert payload["id"] == "preview"
    assert payload["error"]["code"] == protocol.INTERNAL_ERROR


@pytest.mark.parametrize("method", ["document.read", "document.read_text"])
@pytest.mark.parametrize("case", ["missing", "directory"])
def test_sidecar_wraps_document_read_filesystem_failures_as_application_errors(
    tmp_path: Path,
    method: str,
    case: str,
) -> None:
    suffix = ".md" if method == "document.read" else ".txt"
    path = tmp_path / f"document{suffix}"
    if case == "directory":
        path.mkdir()
    request = {
        "jsonrpc": "2.0",
        "id": f"{method}-{case}",
        "method": method,
        "params": {"path": str(path)},
    }
    output = io.StringIO()
    server = sidecar.SidecarServer(
        stdin=io.BytesIO((json.dumps(request) + "\n").encode()),
        stdout=output,
    )

    assert server.run() == 0

    response = next(item for item in _lines(output) if item.get("id") == request["id"])
    assert response["error"]["code"] == protocol.APPLICATION_ERROR
    assert response["error"]["data"]["code"] == "MARDAS-DOCUMENT-READ"
    assert "[Errno" not in response["error"]["message"]


def test_sidecar_wraps_non_utf8_project_save_as_application_error(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "mardas.toml").write_text(
        'schema_version = 1\n\n[project]\ntitle = "Project"\n',
        encoding="utf-8",
    )
    document = root / "chapter.md"
    document.write_text("# Original\n", encoding="utf-8")
    opened = application.EngineService().dispatch(
        "project.read",
        {"project_path": str(root), "relative_path": "chapter.md"},
    )
    request = {
        "jsonrpc": "2.0",
        "id": "project-save-invalid-utf8",
        "method": "project.save",
        "params": {
            "project_path": str(root),
            "relative_path": "chapter.md",
            "content": "\ud800",
            "expected_sha256": opened["sha256"],
        },
    }
    output = io.StringIO()
    server = sidecar.SidecarServer(
        stdin=io.BytesIO((json.dumps(request) + "\n").encode()),
        stdout=output,
    )

    assert server.run() == 0

    response = next(item for item in _lines(output) if item.get("id") == request["id"])
    assert response["error"]["code"] == protocol.APPLICATION_ERROR
    assert response["error"]["data"]["code"] == "MARDAS-INVALID-PROJECT-CONTENT"
    assert response["error"]["message"] == "Project file content must be valid UTF-8 text."
    assert "surrogates not allowed" not in json.dumps(response)
    assert document.read_text(encoding="utf-8") == "# Original\n"


def test_rpc_envelope_covers_worst_case_editor_content_escaping() -> None:
    assert protocol.MAX_REQUEST_BYTES >= application.MAX_DOCUMENT_BYTES * 6 + (1024 * 1024)


def test_sidecar_request_schema_matches_capability_methods() -> None:
    schema = json.loads(
        (Path(__file__).resolve().parents[1] / "schemas" / "sidecar" / "v1" / "request.schema.json")
        .read_text(encoding="utf-8")
    )
    schema_methods = set(schema["properties"]["method"]["enum"])
    capability_methods = set(application.EngineService().capabilities()["methods"])
    assert schema_methods == capability_methods


def test_every_advertised_method_is_actually_routed() -> None:
    """The engine must not advertise a method the transport refuses to route.

    Methods are declared in three places: ``EngineService.capabilities`` says
    what exists, ``EngineService.dispatch`` implements it, and the JSON-RPC
    layer decides whether a request even reaches dispatch. Adding a method to
    the first two and forgetting the third produces the worst possible symptom —
    a client that sees the method offered, calls it, and is told it is unknown.
    """
    control_methods = {
        "system.health",
        "system.capabilities",
        "system.shutdown",
        "job.cancel",
    }
    routed = set(sidecar._HEAVY_METHODS) | control_methods
    advertised = set(application.EngineService().capabilities()["methods"])
    assert advertised - routed == set(), (
        "these methods are advertised but the sidecar refuses to route them"
    )
    assert routed - advertised == set(), (
        "these methods are routed but never advertised"
    )

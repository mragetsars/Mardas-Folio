from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from . import __version__
from .application import EngineError, EngineService
from .protocol import (
    APPLICATION_ERROR,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    JOB_CANCELLED,
    MAX_REQUEST_BYTES,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    PROTOCOL_NAME,
    PROTOCOL_VERSION,
    SERVER_BUSY,
    ProtocolError,
    RpcRequest,
    error_response,
    notification,
    parse_request,
    success_response,
)
from .renderer import RenderCancelledError

LOGGER = logging.getLogger("mardas_md2pdf.sidecar")
_HEAVY_METHODS = {
    "system.support_bundle",
    "document.read",
    "document.save",
    "document.list_assets",
    "document.import_asset",
    "project.open",
    "project.refresh",
    "project.read",
    "project.save",
    "project.search",
    "bibliography.index",
    "book.create",
    "book.add_chapter",
    "book.duplicate_chapter",
    "book.reorder_chapters",
    "book.remove_chapter",
    "book.validate",
    "book.preview",
    "book.export",
    "render.document",
    "render.book",
    "preview.document",
    "preview.document_text",
    "validate.document",
    "validate.document_text",
    "validate.book",
}


@dataclass(slots=True)
class _ActiveJob:
    request: RpcRequest
    cancelled: threading.Event
    future: Future[dict[str, Any]]
    progress_sequence: int = 0


class _JsonLineWriter:
    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def write(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._stream.write(encoded + "\n")
            self._stream.flush()


class SidecarServer:
    """Single-job JSON-RPC sidecar with responsive progress and cancellation."""

    def __init__(self, *, stdin: BinaryIO, stdout: TextIO) -> None:
        self._stdin = stdin
        self._writer = _JsonLineWriter(stdout)
        self._service = EngineService()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mardas-engine")
        self._state_lock = threading.Lock()
        self._active: _ActiveJob | None = None
        self._running = True

    def _send_error(self, error: ProtocolError) -> None:
        self._writer.write(
            error_response(
                error.request_id,
                error.code,
                str(error),
                data=error.data,
            )
        )

    def _progress(self, job: _ActiveJob, message: str, fraction: float) -> None:
        with self._state_lock:
            if self._active is not job:
                return
            job.progress_sequence += 1
            sequence = job.progress_sequence
        self._writer.write(
            notification(
                "job.progress",
                {
                    "request_id": job.request.request_id,
                    "sequence": sequence,
                    "message": str(message),
                    "fraction": max(0.0, min(1.0, float(fraction))),
                },
            )
        )

    def _execute(self, job: _ActiveJob) -> dict[str, Any]:
        return self._service.dispatch(
            job.request.method,
            job.request.params,
            progress=lambda message, fraction: self._progress(job, message, fraction),
            cancelled=job.cancelled.is_set,
        )

    def _complete(self, job: _ActiveJob, future: Future[dict[str, Any]]) -> None:
        try:
            result = future.result()
        except RenderCancelledError as exc:
            payload = error_response(
                job.request.request_id,
                JOB_CANCELLED,
                str(exc) or "Render job was cancelled.",
                data={"application_code": "MARDAS-JOB-CANCELLED"},
            )
        except EngineError as exc:
            code = METHOD_NOT_FOUND if exc.code == "MARDAS-METHOD-NOT-FOUND" else APPLICATION_ERROR
            payload = error_response(
                job.request.request_id,
                code,
                str(exc),
                data=exc.to_dict(),
            )
        except Exception as exc:  # pragma: no cover - defensive process boundary
            LOGGER.exception("Unhandled sidecar job failure")
            data: dict[str, Any] = {"application_code": "MARDAS-INTERNAL-ERROR"}
            if os.environ.get("MARDAS_DEBUG") == "1":
                data["traceback"] = "".join(
                    traceback.format_exception(type(exc), exc, exc.__traceback__)
                )
            payload = error_response(
                job.request.request_id,
                INTERNAL_ERROR,
                "The rendering engine failed unexpectedly.",
                data=data,
            )
        else:
            payload = success_response(job.request.request_id, result)
        finally:
            with self._state_lock:
                if self._active is job:
                    self._active = None
        self._writer.write(payload)

    def _start_job(self, request: RpcRequest) -> None:
        with self._state_lock:
            if self._active is not None:
                self._writer.write(
                    error_response(
                        request.request_id,
                        SERVER_BUSY,
                        "The sidecar is already processing a job.",
                        data={"active_request_id": self._active.request.request_id},
                    )
                )
                return
            cancelled = threading.Event()
            # Submit after creating the job placeholder so immediate progress can
            # resolve the active request without a race.
            placeholder: Future[dict[str, Any]] = Future()
            job = _ActiveJob(request=request, cancelled=cancelled, future=placeholder)
            self._active = job
            future = self._executor.submit(self._execute, job)
            job.future = future
        future.add_done_callback(lambda completed: self._complete(job, completed))

    def _reject_unknown_params(
        self,
        request: RpcRequest,
        *,
        allowed: set[str],
    ) -> bool:
        unknown = sorted(set(request.params) - allowed)
        if not unknown:
            return False
        self._writer.write(
            error_response(
                request.request_id,
                INVALID_PARAMS,
                f"Unknown parameters for {request.method}: {', '.join(unknown)}",
                data={"unknown_params": unknown},
            )
        )
        return True

    def _cancel_job(self, request: RpcRequest) -> None:
        if self._reject_unknown_params(request, allowed={"request_id"}):
            return
        target_id = request.params.get("request_id")
        if isinstance(target_id, bool) or not isinstance(target_id, (str, int)):
            self._writer.write(
                error_response(
                    request.request_id,
                    INVALID_PARAMS,
                    "job.cancel requires a string or integer request_id.",
                )
            )
            return
        with self._state_lock:
            active = self._active
            matched = active is not None and active.request.request_id == target_id
            if matched:
                active.cancelled.set()
        self._writer.write(
            success_response(
                request.request_id,
                {"request_id": target_id, "cancel_requested": matched},
            )
        )

    def _shutdown(self, request: RpcRequest) -> None:
        if self._reject_unknown_params(request, allowed={"force"}):
            return
        force_value = request.params.get("force", False)
        if not isinstance(force_value, bool):
            self._writer.write(
                error_response(
                    request.request_id,
                    INVALID_PARAMS,
                    "system.shutdown force must be a boolean.",
                )
            )
            return
        force = force_value
        with self._state_lock:
            active = self._active
            if active is not None and not force:
                self._writer.write(
                    error_response(
                        request.request_id,
                        SERVER_BUSY,
                        "A job is active; retry shutdown with force=true or cancel it first.",
                        data={"active_request_id": active.request.request_id},
                    )
                )
                return
            if active is not None:
                active.cancelled.set()
            self._running = False
        self._writer.write(success_response(request.request_id, {"shutting_down": True}))

    def _handle(self, request: RpcRequest) -> None:
        if request.method == "system.health":
            if not self._reject_unknown_params(request, allowed=set()):
                self._writer.write(success_response(request.request_id, self._service.health()))
            return
        if request.method == "system.capabilities":
            if not self._reject_unknown_params(request, allowed=set()):
                self._writer.write(
                    success_response(request.request_id, self._service.capabilities())
                )
            return
        if request.method == "system.shutdown":
            self._shutdown(request)
            return
        if request.method == "job.cancel":
            self._cancel_job(request)
            return
        if request.method not in _HEAVY_METHODS:
            self._writer.write(
                error_response(
                    request.request_id,
                    METHOD_NOT_FOUND,
                    f"Unknown method: {request.method}",
                )
            )
            return
        self._start_job(request)

    def run(self) -> int:
        self._writer.write(
            notification(
                "system.ready",
                {
                    "protocol": PROTOCOL_NAME,
                    "protocol_version": PROTOCOL_VERSION,
                    "engine_version": __version__,
                    "pid": os.getpid(),
                },
            )
        )
        try:
            while self._running:
                raw = self._stdin.readline(MAX_REQUEST_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_REQUEST_BYTES:
                    # ``readline(limit)`` leaves the remainder in the pipe. Drain
                    # through the newline so one oversized request cannot be parsed
                    # as multiple follow-up requests.
                    while raw and not raw.endswith(b"\n"):
                        raw = self._stdin.readline(MAX_REQUEST_BYTES + 1)
                    self._send_error(
                        ProtocolError(PARSE_ERROR, "JSON-RPC request exceeds the size limit.")
                    )
                    continue
                if not raw.strip():
                    continue
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    self._send_error(ProtocolError(PARSE_ERROR, f"Invalid JSON: {exc}"))
                    continue
                try:
                    request = parse_request(payload)
                except ProtocolError as exc:
                    self._send_error(exc)
                    continue
                self._handle(request)
        finally:
            with self._state_lock:
                active = self._active
                if active is not None:
                    active.cancelled.set()
            # RenderSession is thread-affine. Queue closure on the same engine
            # worker after any active render has observed cancellation.
            self._executor.submit(self._service.close).result()
            self._executor.shutdown(wait=True, cancel_futures=False)
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mrs-md2pdf-sidecar",
        description="Versioned JSON-RPC sidecar for Mardas Studio desktop clients.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--health",
        action="store_true",
        help="Print one health JSON object and exit without starting the stdio server.",
    )
    parser.add_argument(
        "--capabilities",
        action="store_true",
        help="Print one capabilities JSON object and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("MARDAS_DEBUG") == "1" else logging.WARNING,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    service = EngineService()
    if args.health:
        print(json.dumps(service.health(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.capabilities:
        print(json.dumps(service.capabilities(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    server = SidecarServer(stdin=sys.stdin.buffer, stdout=sys.stdout)
    return server.run()


if __name__ == "__main__":
    raise SystemExit(main())

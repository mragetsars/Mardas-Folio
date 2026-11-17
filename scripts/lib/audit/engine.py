"""Real engine bridge with worker-affine browser sessions and reliable teardown."""

from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

from lib.audit.desktop import QuietHandler
from lib.paths import ROOT

sys.path.insert(0, str(ROOT / "src"))
from mardas_folio.application import EngineError, EngineService  # noqa: E402


@contextmanager
def engine_server(dist: Path):
    service = EngineService()
    worker = ThreadPoolExecutor(max_workers=1)
    calls: list[dict] = []

    def dispatch(method: str, params: dict):
        entry = {"method": method, "params": params}
        calls.append(entry)
        if method == "system.health":
            return service.health()
        if method == "system.capabilities":
            return service.capabilities()
        result = service.dispatch(method, params)
        if method == "book.preview":
            html = result["html"]
            entry["publication_cover"] = 'class="md2pdf-cover ' in html
            entry["publication_watermark"] = 'class="md2pdf-watermark ' in html
        return result

    class Handler(QuietHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            try:
                result = worker.submit(dispatch, request["method"], request["params"]).result()
                payload = {"result": result}
            except EngineError as error:
                payload = {"error": error.to_dict()}
            except Exception as error:
                payload = {"error": {"message": str(error)}}
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(dist)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        worker.submit(service.close).result()
        worker.shutdown()

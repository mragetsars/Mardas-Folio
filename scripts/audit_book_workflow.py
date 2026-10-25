#!/usr/bin/env python3
"""Exercise book preparation and scope in Chromium against the real Python engine."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import partial
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
import threading

from playwright.sync_api import expect, sync_playwright
from pypdf import PdfReader

from audit_desktop_ui import DEFAULT_DIST, QuietHandler

ROOT = Path(__file__).resolve().parents[1]
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


def run_audit(dist: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    checks: list[str] = []
    with tempfile.TemporaryDirectory(prefix="book-fixture-", dir=output) as temporary:
        project = Path(temporary)
        (project / "chapters").mkdir()
        first = project / "chapters/one.md"
        second = project / "chapters/two.md"
        config = project / "mardas.toml"
        first.write_text("# First chapter\n\nOriginal first.\n", encoding="utf-8")
        second.write_text("# Second chapter\n\nOriginal second.\n", encoding="utf-8")
        config.write_text('''schema_version = 1
[project]
title = "Book workflow audit"
direction = "ltr"
[output]
cover = true
toc = true
mathjax = false
[watermark]
text = "PUBLICATION_WATERMARK_ONLY"
[book]
chapters = ["chapters/one.md", "chapters/two.md"]
output = "dist/book.pdf"
''', encoding="utf-8")
        initial = {
            "project": str(project), "second": str(second),
            "pdf": str(project / "dist/reviewed.pdf"),
        }
        fixture = "globalThis.__bookFixture = " + json.dumps(initial) + ";" + r"""
localStorage.setItem('mardas.desktop.locale', 'en');
localStorage.setItem('mardas.desktop.preferences.v1', JSON.stringify({onboardingComplete:true, viewMode:'source', autoPreview:false}));
globalThis.__pdfPickers = 0;
globalThis.__TAURI__ = {
  core:{ invoke:async(command,args={})=>{
    if(command==='take_launch_files') return [];
    if(command==='pick_project_directory') return __bookFixture.project;
    if(command==='pick_markdown_files') return [__bookFixture.second];
    if(command==='pick_pdf_output') {
      __pdfPickers += 1;
      if(globalThis.__cancelNextPdf) { globalThis.__cancelNextPdf=false; return null; }
      return __bookFixture.pdf;
    }
    if(command==='sidecar_cancel') return {cancel_requested:false};
    if(command!=='sidecar_request') return null;
    const payload=await (await fetch('/__engine',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({method:args.method,params:args.params})})).json();
    if(payload.error) throw JSON.stringify(payload.error);
    return payload.result;
  }}, event:{listen:async()=>()=>{}}
};
"""
        with engine_server(dist) as (url, calls), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 960})
            page.set_default_timeout(30_000)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script(fixture)
            page.goto(url, wait_until="networkidle")
            page.locator("#workflow-project").click()
            expect(page.locator("#markdown-editor")).to_have_value(first.read_text(encoding="utf-8"))

            def edit_append(text: str) -> None:
                page.locator(".cm-content").click()
                page.keyboard.press("Control+End")
                page.keyboard.insert_text(text)

            def book_sidebar() -> None:
                if not page.locator("#author-sidebar").is_visible():
                    page.locator("#workspace-toggle-sidebar").click()
                page.locator('[data-sidebar="book"]').click()

            edit_append("\nLATEST_FIRST_CHAPTER\n")
            book_sidebar()
            page.locator("#book-preview").click()
            expect(page.locator("#confirm-modal")).to_be_visible()
            page.locator("#confirm-cancel").click()
            expect(page.locator("#book-preview")).to_be_enabled()
            assert "LATEST_FIRST_CHAPTER" not in first.read_text(encoding="utf-8")
            assert not any(call["method"] == "book.preview" for call in calls)
            checks.append("cancelled book confirmation preserves draft and performs no book read")

            page.locator("#navigator-open").click()
            expect(page.locator("#markdown-editor")).to_have_value(second.read_text(encoding="utf-8"))
            edit_append("\nLATEST_SECOND_DIRECT_OPEN\n")
            page.locator('#navigator-project-files button[title="mardas.toml"]').click()
            expect(page.locator("#markdown-editor")).to_have_value(config.read_text(encoding="utf-8"))
            updated_config = config.read_text(encoding="utf-8").replace(
                'title = "Book workflow audit"', 'title = "Latest saved book settings"'
            ).replace(
                '["chapters/one.md", "chapters/two.md"]',
                '["chapters/two.md", "chapters/one.md"]',
            ) + "\n# LATEST_PROJECT_RESOURCE\n"
            page.locator(".cm-content").click()
            page.keyboard.press("Control+a")
            page.keyboard.insert_text(updated_config)
            editor_before = page.locator("#markdown-editor").input_value()
            mode_before = page.locator("#workspace-view").get_attribute("data-view-mode")
            preview_before = page.locator("#preview-document").inner_text()
            book_sidebar()
            page.locator("#book-preview").click()
            expect(page.locator("#confirm-modal")).to_be_visible()
            page.locator("#confirm-accept").click()
            expect(page.locator("#book-review-modal")).to_be_visible()
            expect(page.locator("#book-review-document")).to_contain_text("LATEST_FIRST_CHAPTER")
            expect(page.locator("#book-review-document")).to_contain_text("LATEST_SECOND_DIRECT_OPEN")
            expect(page.locator("#book-review-project")).to_have_text("Latest saved book settings")
            assert any(call.get("publication_cover") and call.get("publication_watermark") for call in calls)
            expect(page.locator("#book-review-document .md2pdf-cover, #book-review-document .md2pdf-watermark")).to_have_count(0)
            expect(page.locator("#book-review-document")).not_to_contain_text("PUBLICATION_WATERMARK_ONLY")
            expect(page.locator("#book-review-document .md2pdf-toc a")).not_to_have_count(0)
            first_link = page.locator("#book-review-document .md2pdf-toc a").first
            expect(first_link).to_contain_text("Second chapter")
            target = first_link.get_attribute("href")
            assert target and target.startswith("#book-review-")
            expect(page.locator("#book-review-document").locator(target)).to_have_count(1)
            reviewed = page.locator("#book-review-document").inner_text()
            assert reviewed.index("LATEST_SECOND_DIRECT_OPEN") < reviewed.index("LATEST_FIRST_CHAPTER")
            assert "LATEST_PROJECT_RESOURCE" in config.read_text(encoding="utf-8")
            assert "LATEST_FIRST_CHAPTER" in first.read_text(encoding="utf-8")
            assert "LATEST_SECOND_DIRECT_OPEN" in second.read_text(encoding="utf-8")
            checks.append("real whole-book review saves changed chapters, direct-open files and config first")
            checks.append("book content review preserves contents links and omits real publication cover and watermark")
            assert page.locator("#workspace-view").get_attribute("data-view-mode") == mode_before
            assert page.locator("#preview-document").inner_text() == preview_before
            page.screenshot(path=str(output / "book-review.png"), full_page=True)
            page.keyboard.press("Escape")
            expect(page.locator("#book-review-modal")).to_be_hidden()
            expect(page.locator("#book-preview")).to_be_focused()
            assert page.locator("#markdown-editor").input_value() == editor_before
            checks.append("book review has explicit scope and returns to the unchanged active editor")

            page.locator('#open-document-list button').filter(has_text="one.md").click()
            edit_append("\nEXPORTED_LATEST_BUFFER\n")
            book_sidebar()
            page.locator("#book-export").evaluate("button => {button.click();button.click();}")
            expect(page.locator("#confirm-modal")).to_be_visible()
            assert page.evaluate("globalThis.__pdfPickers") == 1
            page.locator("#confirm-accept").click()
            expect(page.locator("#book-output-result")).to_be_visible()
            pdf = Path(initial["pdf"])
            extracted = "\n".join(item.extract_text() for item in PdfReader(pdf).pages)
            assert "EXPORTED_LATEST_BUFFER" in extracted
            assert "LATEST_SECOND_DIRECT_OPEN" in extracted
            assert extracted.index("LATEST_SECOND_DIRECT_OPEN") < extracted.index("EXPORTED_LATEST_BUFFER")
            checks.append("real PDF export includes unsaved chapter edits and double-click opens one picker")

            edit_append("\nREMAINS_AFTER_PICKER_CANCEL\n")
            before_calls = len(calls)
            page.evaluate("globalThis.__cancelNextPdf = true")
            page.locator("#book-export").click()
            expect(page.locator("#book-export")).to_be_enabled()
            assert not page.locator("#confirm-modal").is_visible()
            assert "REMAINS_AFTER_PICKER_CANCEL" not in first.read_text(encoding="utf-8")
            assert not any(call["method"] in {"project.save", "document.save", "book.export"} for call in calls[before_calls:])
            checks.append("cancelled output picker leaves project drafts unsaved and does not export")

            first.write_text("# External edit\n", encoding="utf-8")
            before_preview = sum(call["method"] == "book.preview" for call in calls)
            page.locator("#book-preview").click()
            expect(page.locator("#confirm-modal")).to_be_visible()
            page.locator("#confirm-accept").click()
            expect(page.locator("#book-preview")).to_be_enabled()
            assert not page.locator("#book-review-modal").is_visible()
            assert sum(call["method"] == "book.preview" for call in calls) == before_preview
            assert first.read_text(encoding="utf-8") == "# External edit\n"
            assert "REMAINS_AFTER_PICKER_CANCEL" in page.locator("#markdown-editor").input_value()
            checks.append("external chapter conflict aborts review without overwriting source or draft")
            assert not errors, errors
            browser.close()
    report = {"passed": True, "scope": "Real Chromium interface and real EngineService/file/PDF operations; native pickers use explicit fixture paths.", "checks": checks, "page_errors": errors}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--output", type=Path, default=ROOT / "build/book-workflow-audit")
    arguments = parser.parse_args()
    result = run_audit(arguments.dist.resolve(), arguments.output.resolve())
    print(json.dumps({"passed": result["passed"], "checks": len(result["checks"])}))

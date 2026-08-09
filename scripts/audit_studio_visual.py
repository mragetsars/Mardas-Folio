#!/usr/bin/env python3
"""Capture a Studio browser screenshot for visual QA artifacts."""

from __future__ import annotations

import argparse
import base64
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from visual_qa import ensure_clean_dir, write_json  # noqa: E402

URL_RE = re.compile(r"https?://[^\s]+")


def _studio_process_env() -> dict[str, str]:
    env = os.environ.copy()
    if SRC.is_dir():
        existing = env.get("PYTHONPATH", "")
        parts = [str(SRC), *(part for part in existing.split(os.pathsep) if part)]
        env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(parts))
    return env


def _read_server_url(process: subprocess.Popen[str], timeout: float) -> str:
    deadline = time.monotonic() + timeout
    lines: list[str] = []
    assert process.stdout is not None
    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if line:
            lines.append(line.rstrip())
            match = URL_RE.search(line)
            if match:
                return match.group(0)
        if process.poll() is not None:
            break
    raise RuntimeError("Studio server did not report a URL. Output:\n" + "\n".join(lines))


def _chromium_executable() -> str | None:
    configured = os.environ.get("MARDAS_CHROMIUM_PATH")
    if configured:
        return configured
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        path = shutil.which(name)
        if path:
            return path
    return None



def _open_local_studio_url(
    request: str | urllib.request.Request,
    *,
    timeout: float,
) -> Any:
    """Open a loopback Studio URL without honoring environment proxy settings."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(request, timeout=timeout)  # noqa: S310 - local Studio URL only.


def _fetch_studio_html(url: str, timeout: float) -> str:
    with _open_local_studio_url(url, timeout=timeout) as response:
        html_text = response.read().decode("utf-8")
    base_href = url.rstrip("/") + "/"
    html_text = html_text.replace("<head>", f'<head>\n<base href="{base_href}">', 1)
    asset_url = base_href + "assets/mardas-md2pdf-logo.png"
    try:
        with _open_local_studio_url(asset_url, timeout=timeout) as response:
            logo_data = base64.b64encode(response.read()).decode("ascii")
        html_text = html_text.replace("/assets/mardas-md2pdf-logo.png", f"data:image/png;base64,{logo_data}")
    except Exception:
        pass
    return html_text


def _proxy_local_studio_api(
    url: str,
    request_url: str,
    *,
    method: str,
    body: bytes | None,
    request_headers: dict[str, str],
    timeout: float,
) -> tuple[int, bytes, str, dict[str, str]]:
    parsed = urlsplit(request_url)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    headers: dict[str, str] = {}
    for source, target in (
        ("content-type", "Content-Type"),
        ("x-mardas-studio-token", "X-Mardas-Studio-Token"),
        ("x-mardas-studio-client-id", "X-Mardas-Studio-Client-Id"),
        ("x-mardas-studio-preview-id", "X-Mardas-Studio-Preview-Id"),
    ):
        value = request_headers.get(source)
        if value:
            headers[target] = value
    request = urllib.request.Request(
        url.rstrip("/") + path,
        data=body if method.upper() not in {"GET", "HEAD"} else None,
        headers=headers,
        method=method.upper(),
    )
    try:
        with _open_local_studio_url(request, timeout=timeout) as response:
            return (
                response.status,
                response.read(),
                response.headers.get_content_type(),
                dict(response.headers.items()),
            )
    except urllib.error.HTTPError as exc:
        return (
            exc.code,
            exc.read(),
            exc.headers.get_content_type(),
            dict(exc.headers.items()),
        )
    except Exception as exc:
        return 502, str(exc).encode("utf-8", errors="replace"), "text/plain", {}


def _capture_studio(
    html_text: str,
    url: str,
    screenshot_path: Path,
    timeout_ms: int,
    *,
    project_mode: bool,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - exercised by users without dev/browser deps.
        raise RuntimeError("Playwright is required for Studio visual QA") from exc

    preview_ready_script = """
        () => {
          const status = document.querySelector('#previewStatus')?.textContent || '';
          return /^(?:ready|updated|failed|fast ready|fast preview updated|book ready|text file)$/i.test(status);
        }
    """
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=_chromium_executable())
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)

            def proxy_studio_api(route: Any, request: Any) -> None:
                status, body, content_type, response_headers = _proxy_local_studio_api(
                    url,
                    request.url,
                    method=request.method,
                    body=request.post_data_buffer,
                    request_headers=dict(request.headers),
                    timeout=max(timeout_ms / 1000, 1),
                )
                safe_headers = {
                    key: value
                    for key, value in response_headers.items()
                    if key.lower() in {"content-disposition", "x-content-type-options"}
                }
                route.fulfill(
                    status=status,
                    body=body,
                    content_type=content_type,
                    headers=safe_headers,
                )

            page.route("**/api/**", proxy_studio_api)
            page.set_content(html_text, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_function(preview_ready_script, timeout=timeout_ms)
            except PlaywrightTimeoutError:
                pass
            preview_status = page.locator("#previewStatus").inner_text(timeout=timeout_ms)
            preview_status_box = page.locator("#previewStatus").evaluate(
                "node => ({ text: node.textContent || '', clientWidth: node.clientWidth, scrollWidth: node.scrollWidth })",
                timeout=timeout_ms,
            )
            preview_mode = page.locator("#previewModeInput").input_value(timeout=timeout_ms)
            preview_frame_visible = page.locator("#accuratePreviewFrame").is_visible()
            preview_css_ready_script = """
                () => {
                  const frame = document.querySelector('#accuratePreviewFrame');
                  const doc = frame && frame.contentDocument;
                  return Boolean(doc && doc.querySelector('#mardas-studio-preview-css'));
                }
            """
            try:
                page.wait_for_function(preview_css_ready_script, timeout=timeout_ms)
            except PlaywrightTimeoutError:
                pass
            preview_css_loaded = page.evaluate(preview_css_ready_script)
            preview_status = page.locator("#previewStatus").inner_text(timeout=timeout_ms)
            preview_status_box = page.locator("#previewStatus").evaluate(
                "node => ({ text: node.textContent || '', clientWidth: node.clientWidth, scrollWidth: node.scrollWidth })",
                timeout=timeout_ms,
            )
            page_guides_removed = page.evaluate(
                """
                () => {
                  const frame = document.querySelector('#accuratePreviewFrame');
                  const doc = frame && frame.contentDocument;
                  return Boolean(doc && !doc.querySelector('.md2pdf-preview-page-guides'));
                }
                """
            )
            page.screenshot(path=str(screenshot_path), full_page=True)
            line_number_check = page.evaluate(
                """
                () => {
                  const editor = document.querySelector('#editor');
                  const content = document.querySelector('#lineNumberContent') || document.querySelector('#lineNumbers');
                  if (!editor || !content || typeof syncLineNumbers !== 'function') {
                    return { ok: false, visibleTail: '', renderedLineNumbers: 0, wrap: '' };
                  }
                  editor.value = Array.from({ length: 3005 }, (_, index) => 'line ' + (index + 1)).join(String.fromCharCode(10));
                  editor.dispatchEvent(new Event('input', { bubbles: true }));
                  editor.scrollTop = editor.scrollHeight;
                  editor.dispatchEvent(new Event('scroll'));
                  syncLineNumbers();
                  const rows = Array.from(content.querySelectorAll('.line-number-row'))
                    .map(row => row.textContent.trim())
                    .filter(Boolean);
                  const fallbackRows = content.textContent.trim() ? [content.textContent.trim()] : [];
                  const visibleRows = rows.length ? rows : fallbackRows;
                  const visibleTail = visibleRows.slice(-12).join(' ');
                  return {
                    ok: visibleRows.includes('3005') && editor.getAttribute('wrap') === 'off',
                    visibleTail,
                    renderedLineNumbers: visibleRows.length,
                    editorScrollTop: editor.scrollTop,
                    wrap: editor.getAttribute('wrap') || '',
                  };
                }
                """
            )
            pdf_like_scroll_sync_check = page.evaluate(
                """
                () => ({
                  removedFrameSync: typeof syncFramePreviewScroll === 'undefined',
                  fastOnlyGuard: typeof schedulePreviewScrollSync === 'function' && String(schedulePreviewScrollSync).includes("activePreviewMode() !== 'fast'"),
                })
                """
            )
            preview_scrollbar_check = page.evaluate(
                """
                () => {
                  const frame = document.querySelector('#accuratePreviewFrame');
                  const doc = frame && frame.contentDocument;
                  const root = doc && doc.documentElement;
                  return {
                    hasDarkClass: Boolean(root && root.classList.contains('md2pdf-preview-dark')),
                    scrollbarColor: root ? getComputedStyle(root).scrollbarColor : '',
                  };
                }
                """
            )
            ui_polish_check = page.evaluate(
                """
                () => ({
                  toastRegion: Boolean(document.querySelector('#toastRegion')),
                  commandPaletteNavigation: typeof setCommandPaletteActive === 'function' && typeof activeCommandPaletteId === 'function',
                  exportQueueHelpers: typeof runQueuedExport === 'function' && typeof exportJobStatus === 'function' && typeof cancelActiveExport === 'function',
                  cancelExportButton: Boolean(document.querySelector('#cancelExportBtn')),
                  previewStatusUnclipped: (() => {
                    const node = document.querySelector('#previewStatus');
                    return Boolean(node && node.scrollWidth <= node.clientWidth + 1);
                  })(),
                })
                """
            )
            project_checks = page.evaluate(
                """
                () => ({
                  sectionVisible: Boolean(document.querySelector('#projectWorkspaceSection') && !document.querySelector('#projectWorkspaceSection').hidden),
                  problemsVisible: Boolean(document.querySelector('#problemsSection') && !document.querySelector('#problemsSection').hidden),
                  fileCount: document.querySelectorAll('#projectFileTree [data-project-path]').length,
                  activePath: document.querySelector('#activeProjectPath')?.textContent || '',
                  saveButtonPresent: Boolean(document.querySelector('#saveProjectFileBtn')),
                  validateButtonPresent: Boolean(document.querySelector('#validateProjectBtn')),
                  previewBookButtonPresent: Boolean(document.querySelector('#previewBookBtn')),
                  exportBookButtonPresent: Boolean(document.querySelector('#exportBookBtn')),
                })
                """
            )
            checks = {
                "title": page.title(),
                "export_button_visible": page.locator("#exportPdfBtn").is_visible(),
                "document_section_visible": page.locator("#titleInput").is_visible(),
                "appearance_section_visible": page.locator('[data-choice-group="style"]').count() > 0,
                "branding_section_visible": page.locator('[data-choice-group="branding"]').count() > 0,
                "publication_quality_section_present": page.locator("#publicationQualitySection").count() > 0,
                "settings_badge": page.locator("#appearanceName").inner_text(),
                "preview_status": preview_status,
                "preview_status_unclipped": bool(preview_status_box.get("scrollWidth", 0) <= preview_status_box.get("clientWidth", 0) + 1),
                "preview_mode": preview_mode,
                "preview_failed": "failed" in preview_status.lower(),
                "preview_frame_visible": preview_frame_visible,
                "pdf_like_preview_loaded": preview_status.strip().lower() in {"ready", "updated", "book ready"},
                "pdf_like_preview_css_loaded": preview_css_loaded,
                "pdf_like_page_guides_removed": page_guides_removed,
                "long_editor_line_numbers_ok": bool(line_number_check.get("ok")),
                "long_editor_line_number_tail": line_number_check.get("visibleTail"),
                "long_editor_rendered_line_numbers": line_number_check.get("renderedLineNumbers"),
                "long_editor_wrap": line_number_check.get("wrap"),
                "pdf_like_scroll_sync_removed": bool(pdf_like_scroll_sync_check.get("removedFrameSync")),
                "fast_scroll_sync_guarded": bool(pdf_like_scroll_sync_check.get("fastOnlyGuard")),
                "pdf_like_scrollbar_color": preview_scrollbar_check.get("scrollbarColor"),
                "toast_region_present": bool(ui_polish_check.get("toastRegion")),
                "command_palette_navigation": bool(ui_polish_check.get("commandPaletteNavigation")),
                "export_queue_helpers": bool(ui_polish_check.get("exportQueueHelpers")),
                "cancel_export_button_present": bool(ui_polish_check.get("cancelExportButton")),
                "preview_status_unclipped_live": bool(ui_polish_check.get("previewStatusUnclipped")),
                "project_mode_requested": project_mode,
                "project_section_visible": bool(project_checks.get("sectionVisible")),
                "project_problems_visible": bool(project_checks.get("problemsVisible")),
                "project_file_count": int(project_checks.get("fileCount") or 0),
                "project_active_path": str(project_checks.get("activePath") or ""),
                "project_save_button_present": bool(project_checks.get("saveButtonPresent")),
                "project_validate_button_present": bool(project_checks.get("validateButtonPresent")),
                "project_preview_book_button_present": bool(project_checks.get("previewBookButtonPresent")),
                "project_export_book_button_present": bool(project_checks.get("exportBookButtonPresent")),
            }
        finally:
            browser.close()
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("build/visual-qa/studio"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=30, help="Seconds to wait for the Studio server")
    parser.add_argument("--browser-timeout-ms", type=int, default=60_000)
    parser.add_argument("--clean", action="store_true", help="Delete output directory before capturing")
    parser.add_argument(
        "--project",
        type=Path,
        help="Launch Studio against a mardas.toml project workspace.",
    )
    args = parser.parse_args(argv)

    if args.clean:
        ensure_clean_dir(args.output_dir)
    else:
        args.output_dir.mkdir(parents=True, exist_ok=True)

    env = _studio_process_env()
    env["PYTHONUNBUFFERED"] = "1"
    command = [
        sys.executable,
        "-m",
        "mardas_md2pdf.gui",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--no-open",
    ]
    if args.project is not None:
        command.extend(["--project", str(args.project)])
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    try:
        url = _read_server_url(process, timeout=args.timeout)
        screenshot_path = args.output_dir / ("studio-project.png" if args.project else "studio-default.png")
        html_text = _fetch_studio_html(url, timeout=args.timeout)
        checks = _capture_studio(
            html_text,
            url,
            screenshot_path,
            timeout_ms=args.browser_timeout_ms,
            project_mode=args.project is not None,
        )
        payload = {
            "url": url,
            "screenshot": screenshot_path.name,
            "checks": checks,
        }
        write_json(args.output_dir / "manifest.json", payload)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    if checks.get("title") != "Mardas MD2PDF Studio":
        raise SystemExit("unexpected Studio page title")
    for key in [
        "export_button_visible",
        "document_section_visible",
        "appearance_section_visible",
        "branding_section_visible",
        "publication_quality_section_present",
    ]:
        if not checks.get(key):
            raise SystemExit(f"Studio visual check failed: {key}")
    if checks.get("preview_mode") != "accurate":
        raise SystemExit("unexpected Studio preview mode")
    if checks.get("preview_failed"):
        raise SystemExit(f"Studio preview check failed: {checks.get('preview_status')}")
    if not checks.get("preview_frame_visible"):
        raise SystemExit("Studio preview frame is not visible")
    if not checks.get("pdf_like_preview_css_loaded"):
        raise SystemExit("Studio PDF-like preview CSS was not injected")
    if not checks.get("pdf_like_page_guides_removed"):
        raise SystemExit("Studio PDF-like preview still contains deprecated page guides")
    if not checks.get("long_editor_line_numbers_ok"):
        raise SystemExit("Studio editor line-number virtualization failed for long documents")
    if not checks.get("pdf_like_scroll_sync_removed") or not checks.get("fast_scroll_sync_guarded"):
        raise SystemExit("Studio PDF-like preview still has editor-to-frame scroll synchronization")
    if not checks.get("toast_region_present"):
        raise SystemExit("Studio toast status region is missing")
    if not checks.get("command_palette_navigation"):
        raise SystemExit("Studio command palette keyboard navigation helpers are missing")
    if not checks.get("export_queue_helpers") or not checks.get("cancel_export_button_present"):
        raise SystemExit("Studio queued-export progress or cancellation controls are missing")
    if not checks.get("preview_status_unclipped") or not checks.get("preview_status_unclipped_live"):
        raise SystemExit("Studio preview status is visually clipped")
    if args.project is not None:
        required_project_checks = [
            "project_section_visible",
            "project_problems_visible",
            "project_save_button_present",
            "project_validate_button_present",
            "project_preview_book_button_present",
            "project_export_book_button_present",
        ]
        for key in required_project_checks:
            if not checks.get(key):
                raise SystemExit(f"Studio project visual check failed: {key}")
        if int(checks.get("project_file_count") or 0) < 1:
            raise SystemExit("Studio project file tree is empty")
        if not str(checks.get("project_active_path") or "").strip():
            raise SystemExit("Studio project did not open an active file")
    print(f"Studio screenshot written to {screenshot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

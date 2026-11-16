"""Isolated HTTP fixture, native bridge stub, and shared desktop interactions."""
from __future__ import annotations
import contextlib
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from lib.paths import ROOT

DEFAULT_DIST = ROOT / "apps" / "desktop" / "dist"

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return


@contextlib.contextmanager
def serve(directory: Path):
    handler = partial(QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


INIT_SCRIPT = r"""
globalThis.__TAURI__ = {
  core: {
    invoke: async (command, args = {}) => {
      if (command === "take_launch_files") return [];
      if (command === "sidecar_request") {
        if (args.method === "system.health") {
          return {engine_version: "desktop-ui-audit", runtime: {platform: "browser-smoke"}};
        }
        if (args.method === "project.open") {
          return {project: {
            path: "/qa/book",
            name: "Book QA",
            config: "mardas.toml",
            files: [],
            book: {enabled: true, title: "Book QA", output: "dist/book.pdf", chapter_count: 1, chapters: []}
          }};
        }
        if (args.method === "document.read") {
          return {content: "# Export preview fixture\n\nA readable preview page."};
        }
        if (args.method === "preview.document_text") {
          if (args.params?.input_path === "/qa/sample.md") {
            return {
              body_html: "<h1 id='export-fixture-heading'>Export preview fixture</h1><p>A readable preview page.</p>",
              source_map: [{id: "export-fixture-heading", line: 1, level: 1, title: "Export preview fixture"}],
              diagnostics: []
            };
          }
          return {
            body_html: "<style>body{display:none}</style><form><button>spoof</button></form><img src='https://example.invalid/tracker.png' srcset='https://example.invalid/tracker-2.png 2x' onerror='globalThis.__previewXss=true' style='position:fixed'><h1 id='preview-heading' data-source-line='1'>Preview</h1>",
            source_map: [{id: "preview-heading", line: 1, level: 1, title: "Preview"}],
            diagnostics: []
          };
        }
        if (args.method === "validate.document_text") return {diagnostics: [], valid: true};
        return {};
      }
      if (command === "pick_project_directory") return "/qa/book";
      if (command === "pick_markdown_file") return "/qa/sample.md";
      if (command.startsWith("pick_")) return null;
      return null;
    }
  },
  event: {listen: async () => () => {}}
};
"""


def _visible(page: Any, selector: str) -> bool:
    return bool(page.locator(selector).evaluate("(node) => !node.classList.contains('hidden')"))


def select_settings_section(page: Any, section: str) -> None:
    page.locator(f'.settings-nav button[aria-controls="settings-{section}"]').click()


def open_settings(page: Any, section: str = "appearance") -> None:
    """Use the single global utility, including its compact disclosure."""
    if page.locator("#exit-focus-mode").is_visible():
        page.locator("#exit-focus-mode").click()
    if not page.locator("#settings-button").is_visible():
        page.locator(".app-utilities > summary").click()
    page.locator("#settings-button").click()
    if section != "appearance":
        select_settings_section(page, section)


def run_workspace_command(page: Any, command_id: str) -> None:
    page.keyboard.press("Control+Shift+P")
    page.locator("#command-query").fill(command_id.replace("-", " "))
    page.locator(f'[data-command-id="{command_id}"]').click()


def open_workspace_export(page: Any, selector: str | None = "#workspace-export") -> None:
    """Open the output format chooser through its normal Workspace entry."""
    if page.locator("#exit-focus-mode").is_visible():
        page.locator("#exit-focus-mode").click()
    if selector is None:
        run_workspace_command(page, "export-file")
    else:
        page.locator(selector).click()
    page.locator("#export-format-pdf").click()


def open_template(page: Any, template_id: str) -> None:
    template = page.locator(f'[data-template-id="{template_id}"]')
    if not template.is_visible():
        page.locator(".workspace-empty-templates > summary").click()
    template.click()


def click_workspace_layout_control(page: Any, selector: str) -> None:
    target = page.locator(selector)
    if not target.is_visible():
        page.locator("#workspace-layout-button").click()
    target.click()
    if page.locator("#workspace-layout-menu").is_visible():
        page.keyboard.press("Escape")



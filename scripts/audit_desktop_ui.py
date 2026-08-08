#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST = ROOT / "apps" / "desktop" / "dist"
DEFAULT_OUTPUT = ROOT / "build" / "desktop-ui-audit"


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
        if (args.method === "preview.document_text") {
          return {html: "<h1 data-source-line='1'>Preview</h1>", source_map: []};
        }
        if (args.method === "validate.document_text") return {diagnostics: [], valid: true};
        return {};
      }
      if (command.startsWith("pick_")) return null;
      return null;
    }
  },
  event: {listen: async () => () => {}}
};
"""


def _visible(page: Any, selector: str) -> bool:
    return bool(page.locator(selector).evaluate("(node) => !node.classList.contains('hidden')"))


def run_audit(
    dist: Path,
    output_dir: Path,
    *,
    executable_path: str | None = None,
    timeout_ms: int = 30_000,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    checks: dict[str, object] = {}
    page_errors: list[str] = []
    with serve(dist) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=executable_path,
        )
        context = browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.set_default_timeout(timeout_ms)
        page.add_init_script(INIT_SCRIPT)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.goto(url, wait_until="networkidle")

        checks["onboarding_visible"] = _visible(page, "#onboarding-modal")
        checks["background_inert"] = page.locator(".shell").evaluate("(node) => node.inert")
        checks["onboarding_focus"] = page.evaluate(
            "document.activeElement?.getAttribute('data-onboarding-action')"
        )
        page.locator("#skip-onboarding").click()
        checks["onboarding_closed"] = not _visible(page, "#onboarding-modal")
        checks["background_restored"] = not page.locator(".shell").evaluate("(node) => node.inert")

        page.locator("[data-template-id='report']").click()
        checks["workspace_active"] = page.locator("#workspace-view").evaluate(
            "(node) => node.classList.contains('active')"
        )
        editor = page.locator("#markdown-editor")
        checks["template_content"] = "# Executive Summary" in editor.input_value()

        page.locator("#settings-button").click()
        checks["settings_visible"] = _visible(page, "#settings-modal")
        page.locator("#setting-theme").select_option("dark")
        page.locator("#setting-motion").select_option("reduce")
        page.locator("#settings-form button[type='submit']").click()
        checks["dark_theme"] = page.locator("html").get_attribute("data-theme") == "dark"
        checks["reduced_motion"] = (
            page.locator("html").get_attribute("data-reduced-motion") == "reduce"
        )

        page.keyboard.press("Control+Shift+P")
        checks["command_palette_visible"] = _visible(page, "#command-modal")
        page.locator("#command-query").fill("help")
        page.keyboard.press("Enter")
        checks["help_visible"] = _visible(page, "#help-modal")
        page.locator("#help-done").click()

        page.locator("#settings-button").click()
        page.locator("#setting-locale").select_option("fa")
        page.locator("#settings-form button[type='submit']").click()
        checks["rtl_locale"] = page.locator("html").get_attribute("dir") == "rtl"
        page.screenshot(path=str(output_dir / "desktop-fa-dark.png"), full_page=True)

        checks["page_errors"] = page_errors
        browser.close()

    required = {
        key: value
        for key, value in checks.items()
        if key not in {"page_errors", "onboarding_focus"}
    }
    passed = all(value is True for value in required.values()) and not page_errors
    payload = {
        "schema_version": 1,
        "status": "passed" if passed else "failed",
        "checks": checks,
    }
    (output_dir / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = ["# Desktop UI Smoke", "", f"Status: **{payload['status'].upper()}**", ""]
    lines.extend(f"- {key}: `{value}`" for key, value in checks.items())
    (output_dir / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not passed:
        raise RuntimeError(f"Desktop UI smoke failed: {checks}")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run browser-backed smoke checks for desktop UI workflows.")
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--executable-path")
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    args = parser.parse_args(argv)
    payload = run_audit(
        args.dist.resolve(strict=True),
        args.output_dir.resolve(strict=False),
        executable_path=args.executable_path,
        timeout_ms=args.timeout_ms,
    )
    print(f"Desktop UI smoke: {payload['status'].upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Look at every Markdown construct the engine can publish, in the real editor.

The editor's live preview hides syntax marks and styles what they governed, so
the only way to know a construct renders correctly is to put it in the editor
and look. This drives the built frontend with a stubbed ``__TAURI__`` bridge,
loads a corpus that covers GFM plus everything the engine adds on top
(callouts, footnotes, math, mermaid, fence attributes), and captures the
editing surface in overlapping slices.

    python scripts/build_desktop_frontend.py
    python scripts/audit_editor_markdown.py --out build/editor-audit

``--mode write`` is the live preview; ``--mode source`` is the raw buffer, and
comparing the two is how you tell "the decoration is wrong" from "the parse is
wrong".
"""
from __future__ import annotations

import argparse
import contextlib
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST = ROOT / "apps" / "desktop" / "dist"
DEFAULT_CORPUS = ROOT / "tests" / "fixtures" / "markdown-corpus.md"
DEFAULT_OUTPUT = ROOT / "build" / "editor-audit"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return


@contextlib.contextmanager
def _serve(directory: Path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(_QuietHandler, directory=str(directory)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


INIT_SCRIPT = """
globalThis.__TAURI__ = {
  core: {
    invoke: async (command, args = {}) => {
      if (command === "take_launch_files") return [];
      if (command === "sidecar_request") {
        if (args.method === "system.health") {
          return {engine_version: "editor-audit", runtime: {platform: "editor-audit"}};
        }
        if (args.method === "preview.document_text") {
          return {body_html: "<h1 id='h'>Preview</h1>", source_map: [], diagnostics: []};
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

# What the live preview is expected to have done to the buffer. Each entry is a
# CSS selector plus the least number of matches that means "this construct is
# being handled at all"; the screenshots say whether it is handled *well*.
EXPECTATIONS: list[tuple[str, str, int]] = [
    ("heading line", ".cm-md-heading", 8),
    ("h1", ".cm-md-h1", 1),
    ("h6", ".cm-md-h6", 1),
    ("list line", ".cm-md-list-line", 12),
    ("list marker", ".cm-md-list-mark", 8),
    ("task checkbox", ".cm-md-task", 3),
    ("quote line", ".cm-quote-line", 3),
    ("callout", ".cm-md-callout", 5),
    ("callout: note", ".cm-md-callout-note", 1),
    ("callout: warning", ".cm-md-callout-warning", 1),
    ("callout: tip", ".cm-md-callout-tip", 1),
    ("callout: important", ".cm-md-callout-important", 1),
    ("callout: caution", ".cm-md-callout-caution", 1),
    ("code line", ".cm-code-line", 12),
    ("code fence language chip", ".cm-md-code-info", 4),
    ("table widget", ".cm-md-table", 2),
    ("horizontal rule widget", ".cm-md-rule", 3),
    ("front matter widget", ".cm-md-frontmatter", 0),
    # An image only becomes a widget once its path resolves, which needs a
    # saved document to resolve against; in this harness the buffer has never
    # been written to disk, so the markup correctly stays as source.
    ("image widget", ".cm-md-image", 0),
    # Counts are the running maximum over one viewport, and the corpus never
    # puts two inline spans on the same screen.
    ("inline code", ".cm-md-inline-code", 1),
    ("math", ".cm-md-math", 2),
    ("footnote reference", ".cm-md-footnote", 2),
]

MEASURE_JS = """(selectors) => {
  const out = {};
  for (const [label, selector] of selectors) {
    out[label] = document.querySelectorAll(selector).length;
  }
  const view = document.querySelector(".cm-editor");
  out.__mode = view ? view.getAttribute("data-editor-mode") : null;
  const scroller = document.querySelector(".cm-scroller");
  out.__scroll_height = scroller ? Math.round(scroller.scrollHeight) : 0;
  out.__client_height = scroller ? Math.round(scroller.clientHeight) : 0;
  // Any line still showing raw syntax that should have been hidden, other
  // than the one the caret is on.
  return out;
}"""


def run(dist: Path, corpus: Path, output: Path, *, mode: str, theme: str) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    output.mkdir(parents=True, exist_ok=True)
    text = corpus.read_text(encoding="utf-8")
    report: dict[str, Any] = {"mode": mode, "theme": theme}

    with _serve(dist) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 1000}, device_scale_factor=2
        )
        page = context.new_page()
        page.set_default_timeout(30_000)
        page.add_init_script(INIT_SCRIPT)
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
        # CodeMirror catches an exception thrown by a view plugin, disables the
        # plugin and reports it with console.error. Without this listener the
        # audit sees every decoration missing and no error at all.
        page.on(
            "console",
            lambda message: errors.append(f"console.{message.type}: {message.text}")
            if message.type == "error"
            else None,
        )
        page.goto(url, wait_until="networkidle")

        skip = page.locator("#skip-onboarding")
        with contextlib.suppress(Exception):
            skip.wait_for(state="visible", timeout=4000)
            skip.click()
        page.wait_for_timeout(200)

        if theme != "light":
            page.locator("#settings-button").click()
            page.wait_for_timeout(200)
            page.locator("#setting-theme").select_option(theme)
            page.locator("#settings-form button[type='submit']").click()
            page.wait_for_timeout(300)

        page.locator("[data-template-id='blank']").click()
        page.locator(".codemirror-mount .cm-editor").wait_for(state="visible")
        page.wait_for_timeout(300)
        # Typed in, not assigned. Setting the mirror textarea's value looks
        # like it works and does nothing: the CodeMirror adapter owns the
        # document and only syncs the textarea outward, so an audit that
        # assigns to it silently measures whatever template was already open.
        page.locator(".cm-content").click()
        page.keyboard.press("Control+A")
        page.keyboard.press("Delete")
        page.wait_for_timeout(150)
        page.keyboard.insert_text(text)
        page.wait_for_timeout(1000)
        loaded = page.evaluate("() => document.querySelector('#markdown-editor').value")
        if loaded != text:
            raise RuntimeError(
                f"the corpus did not load verbatim ({len(loaded)} of {len(text)} chars)"
            )
        page.locator(f'button[data-view-mode="{mode}"]').click()
        page.wait_for_timeout(700)
        # Park the caret at the very end so no construct is expanded for editing.
        page.locator(".cm-content").click()
        page.keyboard.press("Control+End")
        page.wait_for_timeout(500)

        # CodeMirror only builds decorations for the viewport, so a count taken
        # at one scroll position measures one screenful. The sweep below takes
        # the running maximum per construct: "was this ever decorated".
        pane = page.locator(".editor-pane")
        selectors = [[label, selector] for label, selector, _ in EXPECTATIONS]
        totals: dict[str, int] = {}
        page.evaluate("document.querySelector('.cm-scroller').scrollTop = 0")
        page.wait_for_timeout(300)
        step = 700
        shots: list[str] = []
        for index in range(30):
            page.wait_for_timeout(280)
            seen = page.evaluate(MEASURE_JS, selectors)
            for key, value in seen.items():
                if isinstance(value, int) and not key.startswith("__"):
                    totals[key] = max(totals.get(key, 0), value)
                else:
                    totals.setdefault(key, value)
            path = output / f"{theme}-{mode}-{index:02d}.png"
            pane.screenshot(path=str(path))
            shots.append(path.name)
            moved = page.evaluate(
                """(step) => {
                    const s = document.querySelector('.cm-scroller');
                    const before = s.scrollTop;
                    s.scrollTop = before + step;
                    return s.scrollTop - before;
                }""",
                step,
            )
            if moved < 10:
                break
        report["counts"] = totals
        report["shots"] = shots
        report["page_errors"] = errors
        browser.close()

    (output / f"report-{theme}-{mode}.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--mode", default="write", choices=("write", "source", "split"))
    parser.add_argument("--theme", default="light", choices=("light", "dark"))
    args = parser.parse_args(argv)

    report = run(
        args.dist.resolve(strict=True),
        args.corpus.resolve(strict=True),
        args.out.resolve(strict=False),
        mode=args.mode,
        theme=args.theme,
    )
    counts = report["counts"]
    print(f"editor mode: {counts.get('__mode')}   slices: {len(report['shots'])}")
    missing = []
    for label, selector, minimum in EXPECTATIONS:
        found = counts.get(label, 0)
        flag = "ok " if found >= minimum else "GAP"
        if found < minimum:
            missing.append(label)
        print(f"{flag} {found:4}/{minimum:<4} {label:32} {selector}")
    if report["page_errors"]:
        print("\npage errors:")
        for error in report["page_errors"][:5]:
            print(" ", error)
    print(f"\n{len(missing)} construct(s) with no decoration: {', '.join(missing) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

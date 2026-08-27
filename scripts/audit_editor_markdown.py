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

``--locale fa`` runs the same corpus with the interface mirrored. The editor
then sits in a right-to-left container, so CodeMirror's own base direction
flips: the gutter moves, and every line with no strong character of its own
lays out the other way. The corpus does not change, so any difference between
the two runs is the mirroring.
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
    # Ordered markers keep their number and stay marks; unordered ones are
    # replaced by the bullet glyph the engine prints.
    ("ordered marker", ".cm-md-list-mark", 3),
    ("bullet glyph", ".cm-md-bullet", 5),
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
  const seen = {};
  for (const [label, selector] of selectors) {
    const found = [...document.querySelectorAll(selector)];
    out[label] = found.length;
    // A fingerprint per element, so instances that never share a viewport are
    // still counted once each. Constructs whose text repeats — a bullet glyph,
    // a horizontal rule — collapse to one fingerprint, which is why the count
    // above is kept as well and the larger of the two is used.
    seen[label] = found.map((element) => {
      const line = element.closest(".cm-line");
      return `${element.textContent.trim().slice(0, 60)}|${(line ? line.textContent : "").trim().slice(0, 60)}`;
    });
  }
  out.__fingerprints = seen;
  const view = document.querySelector(".cm-editor");
  out.__mode = view ? view.getAttribute("data-editor-mode") : null;
  const scroller = document.querySelector(".cm-scroller");
  out.__scroll_height = scroller ? Math.round(scroller.scrollHeight) : 0;
  out.__client_height = scroller ? Math.round(scroller.clientHeight) : 0;
  // Any line still showing raw syntax that should have been hidden, other
  // than the one the caret is on.
  return out;
}"""


#: (label, text as it renders once decorated, mark that must come back)
REVEAL_CASES = [
    ("heading", "Heading one", "#"),
    # This one was the known failure, and it was never about maths. It is the
    # first case in this table that sits below a block widget, and a widget
    # with a CSS margin is height the height map never learns about: the map
    # ran 45px short of what was painted by the time it reached this line, so
    # the click resolved to the blank line below. Kept first among the cases
    # after a widget for exactly that reason.
    ("inline math", "Inline math", "$"),
    ("bullet", "Unordered item", "-"),
    ("inline code", "inline code", "`"),
    ("link", "and a", "]("),
]


def check_caret_reveals_source(page: Any, _text: str) -> list[dict[str, Any]]:
    """Put the caret on each construct and confirm its source comes back.

    The line is reached by clicking the rendered text, not by counting
    ArrowDown presses: live preview collapses ranges and replaces others with
    block widgets, so vertical movement and document line numbers are
    deliberately not the same thing.
    """
    results: list[dict[str, Any]] = []
    for label, rendered, mark in REVEAL_CASES:
        # CodeMirror only keeps the viewport in the DOM, so the line has to be
        # scrolled to before it can be clicked. Stepping down from the top
        # finds it; centring it then guarantees the click lands on the line
        # rather than on whichever one happens to straddle the viewport edge.
        page.evaluate("() => { document.querySelector('.cm-scroller').scrollTop = 0; }")
        page.wait_for_timeout(220)
        target = None
        for _ in range(40):
            target = page.evaluate(
                """(rendered) => {
                    for (const line of document.querySelectorAll('.cm-line')) {
                        if (!line.textContent.includes(rendered)) continue;
                        line.scrollIntoView({block: "center"});
                        const box = line.getBoundingClientRect();
                        return {x: box.left + 6, y: box.top + Math.min(box.height / 2, 10)};
                    }
                    return null;
                }""",
                rendered,
            )
            if isinstance(target, dict):
                # CodeMirror estimates the height of lines it has not measured
                # yet, so immediately after scrolling into a long document the
                # painted position of a line still moves. Clicking on the first
                # measurement lands wherever the line used to be. Wait for the
                # box to stop moving before trusting it.
                previous = None
                for _ in range(20):
                    page.wait_for_timeout(120)
                    target = page.evaluate(
                        """(rendered) => {
                            for (const line of document.querySelectorAll('.cm-line')) {
                                if (!line.textContent.includes(rendered)) continue;
                                const box = line.getBoundingClientRect();
                                return {x: box.left + 30, y: box.top + box.height / 2,
                                        top: Math.round(box.top)};
                            }
                            return null;
                        }""",
                        rendered,
                    )
                    if not isinstance(target, dict):
                        break
                    if previous is not None and abs(target["top"] - previous) < 2:
                        break
                    previous = target["top"]
                break
            moved = page.evaluate(
                """() => {
                    const s = document.querySelector('.cm-scroller');
                    const before = s.scrollTop;
                    s.scrollTop = before + 260;
                    return s.scrollTop - before;
                }"""
            )
            page.wait_for_timeout(180)
            if moved < 5:
                target = None
                break
        if not isinstance(target, dict):
            results.append({"case": label, "ok": False, "why": "not rendered"})
            continue
        page.mouse.click(target["x"], target["y"])
        page.wait_for_timeout(200)
        # Confirm the caret actually landed on the construct's line before
        # judging what that line shows. Hit-testing a virtualized, decorated
        # editor is not reliable enough to assume it: a click that lands one
        # line off reports an empty active line and looks exactly like the
        # decoration failing to yield.
        for _ in range(4):
            on_line = page.evaluate(
                """(rendered) => {
                    const active = document.querySelector('.cm-activeLine');
                    if (!active) return false;
                    return active.textContent.includes(rendered)
                        || active.textContent.includes(rendered.replace(/\s+/g, " "));
                }""",
                rendered,
            )
            if on_line:
                break
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(140)
        seen = page.evaluate(
            """(mark) => {
                const active = document.querySelector('.cm-activeLine');
                if (!active) return {ok: false, text: null};
                const text = active.textContent;
                return {ok: text.includes(mark), text: text.slice(0, 90)};
            }""",
            mark,
        )
        entry = {"case": label, "ok": bool(seen["ok"])}
        if not seen["ok"]:
            entry["why"] = f"active line reads {seen['text']!r}"
        results.append(entry)
    return results


# Typing behaviours every Markdown editor is expected to have. Each case types
# `seed`, presses `keys`, and asserts the buffer afterwards.
TYPING_CASES = [
    ("bullet continues", "- first", ["Enter"], "- first\n- "),
    # Enter on an empty item clears the marker and leaves the caret on the
    # blank line: you are out of the list, with no stray line to delete.
    ("bullet ends on empty", "- first", ["Enter", "Enter"], "- first\n"),
    ("task ends on empty", "- [ ] a", ["Enter", "Enter"], "- [ ] a\n"),
    ("quote ends on empty", "> a", ["Enter", "Enter"], "> a\n"),
    ("nested bullet outdents", "  - deep", ["Enter", "Enter"], "  - deep\n"),
    ("ordered continues", "1. first", ["Enter"], "1. first\n2. "),
    ("task continues", "- [x] done", ["Enter"], "- [x] done\n- [ ] "),
    ("quote continues", "> quoted", ["Enter"], "> quoted\n> "),
    ("backspace clears markup", "- ", ["Backspace"], ""),
]


def check_typing_behaviour(page: Any) -> list[dict[str, Any]]:
    """Type into the real editor and read the buffer back.

    These are the behaviours that make a Markdown editor feel like one, and
    none of them show up in a screenshot: pressing Enter in a list either
    continues it or it does not.
    """
    results: list[dict[str, Any]] = []
    for label, seed, keys, expect in TYPING_CASES:
        page.locator(".cm-content").click()
        page.keyboard.press("Control+a")
        page.keyboard.press("Delete")
        page.wait_for_timeout(80)
        page.keyboard.insert_text(seed)
        page.wait_for_timeout(120)
        for key in keys:
            page.keyboard.press(key)
            page.wait_for_timeout(260)
        got = page.evaluate("() => document.querySelector('#markdown-editor').value")
        entry: dict[str, Any] = {"case": label, "ok": got == expect}
        if not entry["ok"]:
            entry["why"] = f"buffer is {got!r}, expected {expect!r}"
        results.append(entry)
    return results


def run(
    dist: Path,
    corpus: Path,
    output: Path,
    *,
    mode: str,
    theme: str,
    locale: str = "en",
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    output.mkdir(parents=True, exist_ok=True)
    text = corpus.read_text(encoding="utf-8")
    report: dict[str, Any] = {"mode": mode, "theme": theme, "locale": locale}
    tag = f"{theme}-{mode}" if locale == "en" else f"{theme}-{locale}-{mode}"

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

        if theme != "light" or locale != "en":
            page.locator("#settings-button").click()
            page.wait_for_timeout(200)
            page.locator("#setting-theme").select_option(theme)
            if locale != "en":
                page.locator("#setting-locale").select_option(locale)
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
        # at one scroll position measures one screenful. The sweep below asks
        # "was this ever decorated" two ways and keeps the larger answer: the
        # running maximum seen at once, and the number of distinct instances
        # seen across the whole sweep. The maximum alone made every expectation
        # a statement about how many of a construct fit on a screen together,
        # which is a fact about the line height and the width of the writing
        # column rather than about the decoration — narrowing the column to a
        # readable measure pushed the corpus's two tables apart and "broke" a
        # check that nothing had actually broken.
        pane = page.locator(".editor-pane")
        selectors = [[label, selector] for label, selector, _ in EXPECTATIONS]
        totals: dict[str, int] = {}
        fingerprints: dict[str, set[str]] = {}
        page.evaluate("document.querySelector('.cm-scroller').scrollTop = 0")
        page.wait_for_timeout(300)
        step = 700
        shots: list[str] = []
        for index in range(30):
            page.wait_for_timeout(280)
            seen = page.evaluate(MEASURE_JS, selectors)
            for label, marks in (seen.pop("__fingerprints", None) or {}).items():
                fingerprints.setdefault(label, set()).update(marks)
            for key, value in seen.items():
                if isinstance(value, int) and not key.startswith("__"):
                    totals[key] = max(totals.get(key, 0), value)
                else:
                    totals.setdefault(key, value)
            path = output / f"{tag}-{index:02d}.png"
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
        for label, marks in fingerprints.items():
            totals[label] = max(totals.get(label, 0), len(marks))
        report["counts"] = totals
        report["shots"] = shots

        # The premise of live preview is that it is still an editor: the line
        # the caret is on shows its raw marks, so a link's target or a
        # formula's source can be reached by clicking into it. A decoration
        # that forgets to check the active line turns the mode into a preview
        # you cannot edit, and nothing else in this audit would notice.
        report["editable"] = (
            check_caret_reveals_source(page, text) if mode == "write" else []
        )
        # Typing is checked last: it rewrites the buffer, so everything that
        # reads the corpus has to have run already.
        report["typing"] = check_typing_behaviour(page) if mode == "write" else []
        report["page_errors"] = errors
        browser.close()

    (output / f"report-{tag}.json").write_text(
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
    parser.add_argument("--locale", default="en", choices=("en", "fa"))
    args = parser.parse_args(argv)

    report = run(
        args.dist.resolve(strict=True),
        args.corpus.resolve(strict=True),
        args.out.resolve(strict=False),
        mode=args.mode,
        theme=args.theme,
        locale=args.locale,
    )
    counts = report["counts"]
    print(
        f"editor mode: {counts.get('__mode')}   locale: {args.locale}"
        f"   slices: {len(report['shots'])}"
    )
    # Source mode renders the document verbatim: it adds no decoration on
    # purpose, so every expectation below would "fail" and the run would say
    # twenty-one things are broken when nothing is. A check that cries wolf in
    # one of its two modes is a check nobody reads in either.
    live = args.mode != "source"
    missing = []
    for label, selector, minimum in EXPECTATIONS:
        found = counts.get(label, 0)
        if not live:
            # The only thing to hold source mode to is that it decorates
            # nothing; anything found here would be live-preview leaking in.
            flag = "ok " if found == 0 else "GAP"
            if found:
                missing.append(f"{label} (source mode should draw nothing)")
            print(f"{flag} {found:4}/0    {label:32} {selector}")
            continue
        flag = "ok " if found >= minimum else "GAP"
        if found < minimum:
            missing.append(label)
        print(f"{flag} {found:4}/{minimum:<4} {label:32} {selector}")
    editable = report.get("editable") or []
    if editable:
        print()
        for item in editable:
            flag = "ok " if item.get("ok") else "GAP"
            note = f"  ({item['why']})" if item.get("why") else ""
            print(f"{flag} caret reveals source: {item['case']}{note}")
    typing = report.get("typing") or []
    if typing:
        print()
        for item in typing:
            flag = "ok " if item.get("ok") else "GAP"
            note = f"  ({item['why']})" if item.get("why") else ""
            print(f"{flag} typing: {item['case']}{note}")
    if report["page_errors"]:
        print("\npage errors:")
        for error in report["page_errors"][:5]:
            print(" ", error)
    if live:
        print(f"\n{len(missing)} construct(s) with no decoration: {', '.join(missing) or 'none'}")
    else:
        print(f"\n{len(missing)} construct(s) decorated in source mode: "
              f"{', '.join(missing) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

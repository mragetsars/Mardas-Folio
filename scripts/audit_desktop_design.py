#!/usr/bin/env python3
"""Look at the desktop interface, and measure what looking at it cannot tell you.

Two jobs, one browser session:

``shoot``
    Capture every major surface — start centre, settings, onboarding, the
    workspace in each view mode, the command palette — across light/dark and
    en/fa.  A redesign is not reviewable from a diff; it is reviewable from
    these.

``measure``
    Report the numbers a screenshot hides.  The one that matters is
    ``document_share``: the fraction of the window that is the document rather
    than chrome around it.  The workspace once stacked seven horizontal bars
    between the title bar and the first line of text and spent 248px of a
    900px window on them, two of those bars restating what the bar above them
    already said.  That is invisible in a screenshot and obvious in a number.

Both run against ``apps/desktop/dist`` with a stubbed ``__TAURI__`` bridge, so
they need no sidecar, no Rust build and no network.  Build the frontend first:

    python scripts/build_desktop_frontend.py
    python scripts/audit_desktop_design.py measure
    python scripts/audit_desktop_design.py shoot --out build/desktop-design
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST = ROOT / "apps" / "desktop" / "dist"
DEFAULT_OUTPUT = ROOT / "build" / "desktop-design"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        return


@contextlib.contextmanager
def _serve(directory: Path):
    handler = partial(_QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


# A document with enough range to expose the decisions: headings, emphasis,
# a quote, a fenced block, a table, and a Persian section so RTL is never
# reviewed as an afterthought.
SAMPLE = """---
title: Mardas Folio
lang: en
toc: true
---

# Mardas Folio

A desktop authoring and publishing tool for technical documents that mix
Persian and English. The engine renders Markdown through Chromium, and the
[user guide](docs/guides/GUIDE.en.md) describes what it publishes.

## Typography

Paragraph text sits on a measured column. **Bold**, *italic*, and `inline code`
all take the surrounding rhythm.

- A list item, with a second line long enough to wrap under its own text
- [x] A finished task
- [ ] One still to do

> A quotation is inset and ruled, not boxed and tinted.

> [!NOTE]
> A callout names its kind and keeps the rest of the line as prose.

```python
def render(document):
    return chromium.print_to_pdf(document)
```

## فارسی

این متن فارسی است و باید از راست به چپ خوانده شود. اعداد مثل ۱۲۳۴ و
واژه‌های انگلیسی مثل Markdown در میان متن قرار می‌گیرند.

| Option  | Default |
| ------- | ------- |
| palette | neutral |
| mode    | light   |
"""

PREVIEW_HTML = (
    "<h1 id='p-h1' data-source-line='1'>Mardas Folio</h1>"
    "<p>A desktop authoring and publishing tool for technical documents that mix "
    "Persian and English. The engine renders Markdown through Chromium.</p>"
    "<h2 id='p-h2' data-source-line='10'>Typography</h2>"
    "<p>Paragraph text sits on a measured column. <strong>Bold</strong>, <em>italic</em>, "
    "and <code>inline code</code> all take the surrounding rhythm.</p>"
    "<blockquote><p>A pull quote carries the accent rule on its leading edge.</p></blockquote>"
    "<pre><code>def render(document):\n    return chromium.print_to_pdf(document)</code></pre>"
    "<h2 id='p-h3' data-source-line='23'>فارسی</h2>"
    "<p dir='rtl'>این متن فارسی است و باید از راست به چپ خوانده شود.</p>"
    "<table><thead><tr><th>Option</th><th>Default</th></tr></thead>"
    "<tbody><tr><td>palette</td><td>teal</td></tr></tbody></table>"
)

INIT_SCRIPT = """
globalThis.__TAURI__ = {
  core: {
    invoke: async (command, args = {}) => {
      if (command === "take_launch_files") return [];
      if (command === "sidecar_request") {
        if (args.method === "system.health") {
          return {engine_version: "design-audit", runtime: {platform: "design-audit"}};
        }
        if (args.method === "preview.document_text") {
          return {
            body_html: __PREVIEW__,
            source_map: [
              {id: "p-h1", line: 1, level: 1, title: "Mardas Folio"},
              {id: "p-h2", line: 10, level: 2, title: "Typography"},
              {id: "p-h3", line: 23, level: 2, title: "فارسی"}
            ],
            diagnostics: []
          };
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
""".replace("__PREVIEW__", json.dumps(PREVIEW_HTML))


MEASURE_JS = """() => {
  const h = (el) => (el && el.offsetParent !== null)
    ? Math.round(el.getBoundingClientRect().height) : 0;
  const q = (s) => document.querySelector(s);
  const heights = {
    topbar: h(q('.topbar')),
    author_toolbar: h(q('.author-toolbar')),
    tab_bar: h(q('.tab-bar')) || h(q('.document-tabs')),
    editor_pane_header: h(q('.editor-pane .pane-header')),
    format_bar: h(q('.format-bar')),
    editor_status: h(q('.editor-status')),
    app_footer: h(q('.app-footer')),
  };
  const chrome = Object.values(heights).reduce((a, b) => a + b, 0);
  const doc = h(q('.codemirror-mount .cm-scroller')) || h(q('.editor-surface'));
  const win = window.innerHeight;
  const bars = Object.entries(heights).filter(([, v]) => v > 0).map(([k]) => k);

  const gutter = q('.cm-gutters');
  const content = q('.cm-content');
  const number = q('.cm-lineNumbers .cm-gutterElement');
  const rulers = (gutter && content) ? {
    gutter_width: Math.round(gutter.getBoundingClientRect().width),
    gap_number_to_text: number
      ? Math.round(content.getBoundingClientRect().left - number.getBoundingClientRect().right)
      : null,
  } : null;

  // Every distinct corner radius and every distinct border colour in the
  // visible tree: a design system has few of each, a grown one has many.
  const radii = new Set(), borders = new Set(), fonts = new Set();
  for (const el of document.querySelectorAll('.shell *')) {
    if (el.offsetParent === null) continue;
    const cs = getComputedStyle(el);
    const r = cs.borderTopLeftRadius;
    if (r && r !== '0px') radii.add(r);
    for (const side of ['Top', 'Right', 'Bottom', 'Left']) {
      if ((parseFloat(cs['border' + side + 'Width']) || 0) > 0) {
        borders.add(cs['border' + side + 'Color']);
      }
    }
    fonts.add(cs.fontSize);
  }
  return {
    heights, bars, bar_count: bars.length, chrome_total: chrome,
    document_px: doc, window_px: win,
    document_share: +(doc / win).toFixed(3),
    rulers,
    distinct_radii: [...radii].sort(),
    distinct_border_colours: [...borders].sort(),
    distinct_font_sizes: [...fonts].sort((a, b) => parseFloat(a) - parseFloat(b)),
  };
}"""


CONTRAST_JS = """() => {
  // Effective background: walk up until an ancestor paints something opaque,
  // and start above anything the browser is compositing at less than full
  // strength — a faded group's own background is faded with it, so what is
  // actually behind the text is whatever is behind the group.
  const bgOf = (el) => {
    let node = el;
    while (node && node !== document.documentElement) {
      const style = getComputedStyle(node);
      if (parseFloat(style.opacity) >= 0.999) {
        const m = style.backgroundColor.match(/rgba?\\(([^)]+)\\)/);
        if (m) {
          const parts = m[1].split(',').map(s => parseFloat(s));
          const alpha = parts.length > 3 ? parts[3] : 1;
          if (alpha >= 0.95) return [parts[0], parts[1], parts[2]];
        }
      }
      node = node.parentElement;
    }
    const body = getComputedStyle(document.body).backgroundColor.match(/rgba?\\(([^)]+)\\)/);
    return body ? body[1].split(',').map(s => parseFloat(s)).slice(0, 3) : [255, 255, 255];
  };

  // `opacity` on any ancestor fades the text with everything else in the
  // group, and the computed `color` does not say so. Reading the colour alone
  // meant focus mode — which drops two toolbars to 0.3 — measured as though
  // nothing had changed.
  const alphaOf = (el) => {
    let alpha = 1;
    let node = el;
    while (node && node !== document.documentElement) {
      alpha *= parseFloat(getComputedStyle(node).opacity);
      node = node.parentElement;
    }
    return alpha;
  };

  // WCAG exempts inactive components, and this interface says so in the DOM.
  const inactive = (el) => !!el.closest(
    ':disabled, [aria-disabled="true"], [data-inactive="true"], .hidden');
  const lin = (c) => { c /= 255; return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  const lum = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  const ratio = (a, b) => {
    const la = lum(a), lb = lum(b);
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  };
  const name = (el) => {
    const id = el.id ? '#' + el.id : '';
    const cls = (el.className && typeof el.className === 'string')
      ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '';
    return el.tagName.toLowerCase() + id + cls;
  };

  const failures = [];
  const seen = new Set();
  for (const el of document.querySelectorAll('body *')) {
    if (el.offsetParent === null && getComputedStyle(el).position !== 'fixed') continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) continue;
    // Only elements that render their own text.
    const text = [...el.childNodes]
      .filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join('');
    if (!text) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || parseFloat(cs.opacity) < 0.1) continue;
    const fg = cs.color.match(/rgba?\\(([^)]+)\\)/);
    if (!fg) continue;
    const parts = fg[1].split(',').map(s => parseFloat(s));
    if (parts.length > 3 && parts[3] < 0.5) continue;
    if (inactive(el)) continue;
    const size = parseFloat(cs.fontSize);
    const weight = parseInt(cs.fontWeight, 10) || 400;
    // WCAG large text: 18.66px bold, or 24px.
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    const need = large ? 3.0 : 4.5;
    const background = bgOf(el);
    // Composite the text over what is behind it at the strength it is
    // actually painted with.
    const alpha = Math.max(0, Math.min(1, alphaOf(el) * (parts.length > 3 ? parts[3] : 1)));
    const foreground = parts.slice(0, 3).map(
      (channel, index) => channel * alpha + background[index] * (1 - alpha));
    const r = ratio(foreground, background);
    if (r < need) {
      const key = name(el) + '|' + Math.round(r * 100);
      if (seen.has(key)) continue;
      seen.add(key);
      failures.push({
        element: name(el), ratio: +r.toFixed(2), need,
        color: cs.color, font_size: cs.fontSize,
        painted_alpha: +alpha.toFixed(2),
        sample: text.slice(0, 42),
      });
    }
  }
  return failures.sort((a, b) => a.ratio - b.ratio);
}"""


def _dismiss_onboarding(page: Any) -> None:
    """Onboarding shows on first run only, and recovery can pre-empt it."""
    skip = page.locator("#skip-onboarding")
    try:
        skip.wait_for(state="visible", timeout=4000)
    except Exception:  # noqa: BLE001 - absence is a valid state, not a failure
        return
    skip.click()
    page.wait_for_timeout(200)


def _open_workspace(page: Any) -> None:
    _dismiss_onboarding(page)
    page.locator("[data-template-id='report']").click()
    page.locator(".codemirror-mount .cm-editor").wait_for(state="visible")
    page.wait_for_timeout(400)
    page.evaluate(
        """(doc) => {
            const ta = document.querySelector('#markdown-editor');
            const set = Object.getOwnPropertyDescriptor(
                HTMLTextAreaElement.prototype, 'value').set;
            set.call(ta, doc);
            ta.dispatchEvent(new Event('input', {bubbles: true}));
        }""",
        SAMPLE,
    )
    page.wait_for_timeout(700)


def _apply(page: Any, theme: str, locale: str) -> None:
    page.locator("#settings-button").click()
    page.wait_for_timeout(200)
    page.locator("#setting-theme").select_option(theme)
    if locale != "en":
        page.locator("#setting-locale").select_option(locale)
    page.locator("#settings-form button[type='submit']").click()
    page.wait_for_timeout(400)


LAUNCHER_JS = """() => {
  const view = document.querySelector('#start-view');
  if (!view || view.offsetParent === null) return null;
  const visible = [...view.querySelectorAll('*')].filter((el) => el.offsetParent !== null);
  const top = Math.min(...visible.map((el) => el.getBoundingClientRect().top));
  const bottom = Math.max(...visible.map((el) => el.getBoundingClientRect().bottom));
  // How much of a card is below the last thing written in it. A card with a
  // floor set by something other than its own content carries dead space.
  const cards = [...document.querySelectorAll('.template-card')].map((card) => {
    const box = card.getBoundingClientRect();
    const last = card.querySelector('small');
    return {
      width: Math.round(box.width),
      dead: last ? Math.round(box.bottom - last.getBoundingClientRect().bottom) : null,
    };
  });
  return {
    window_px: window.innerHeight,
    block_px: Math.round(bottom - top),
    above_px: Math.round(top),
    below_px: Math.round(window.innerHeight - bottom),
    cards,
  };
}"""


def measure(dist: Path, *, view_mode: str = "split") -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    with _serve(dist) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        page.set_default_timeout(30_000)
        page.add_init_script(INIT_SCRIPT)
        page.goto(url, wait_until="networkidle")
        _dismiss_onboarding(page)
        page.wait_for_timeout(300)
        # The launcher, before anything is opened. It is a small block in a
        # large window, and the numbers that matter are how the room left over
        # is distributed and whether any card has a floor its content does not
        # reach.
        launcher = page.evaluate(LAUNCHER_JS)
        _open_workspace(page)
        page.locator(f'button.view-mode[data-view-mode="{view_mode}"]').click()
        page.wait_for_timeout(500)
        result = page.evaluate(MEASURE_JS)
        result["launcher"] = launcher
        browser.close()
    return result



def contrast(dist: Path) -> dict[str, Any]:
    """Every visible run of text, measured against what is actually behind it.

    Static review cannot do this: a colour only fails once it lands on a
    particular surface, and the surface is decided by whichever ancestor last
    painted something opaque. Migrating the interface onto design tokens moved
    several values onto the wrong role — greys that were text in one theme and
    a surface in the other — and this is what found them.
    """
    from playwright.sync_api import sync_playwright

    report: dict[str, Any] = {}
    for theme in ("light", "dark"):
        surfaces: dict[str, Any] = {}
        with _serve(dist) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
            page.set_default_timeout(30_000)
            page.add_init_script(INIT_SCRIPT)
            page.goto(url, wait_until="networkidle")
            _dismiss_onboarding(page)
            _apply(page, theme, "en")
            surfaces["start"] = page.evaluate(CONTRAST_JS)
            _open_workspace(page)
            page.locator('[data-view-mode="split"]').click()
            page.wait_for_timeout(800)
            surfaces["workspace"] = page.evaluate(CONTRAST_JS)
            page.locator("#settings-button").click()
            page.wait_for_timeout(300)
            surfaces["settings"] = page.evaluate(CONTRAST_JS)
            # Focus mode is where this check earns the opacity arithmetic: the
            # bars around the document step back, and the first way that was
            # written faded them to 0.3, which took their labels down to
            # 1.5:1 without changing a single computed colour.
            page.locator("label:has(#setting-focus-mode)").click()
            page.locator("#settings-form button[type='submit']").click()
            page.wait_for_timeout(600)
            surfaces["focus mode"] = page.evaluate(CONTRAST_JS)
            browser.close()
        report[theme] = surfaces
    return report


# The window sizes the product claims to support. 720x620 is the shell's own
# declared minimum (`min-width`/`min-height` in styles.css).
VIEWPORTS = [(720, 620), (1024, 768), (1280, 900), (1440, 900), (1920, 1080)]

RESPONSIVE_JS = """() => {
  const doc = document.documentElement;
  const problems = [];

  if (doc.scrollWidth > doc.clientWidth + 1) {
    problems.push(`page scrolls horizontally by ${doc.scrollWidth - doc.clientWidth}px`);
  }

  // Every control the user needs to keep working must be on screen and big
  // enough to hit. 24px is the floor WCAG 2.2 AA sets for a pointer target.
  const required = {
    "#workspace-save": "save",
    "#workspace-export": "create PDF",
    "#workspace-validate": "check document",
    "#settings-button": "settings",
    "#command-button": "command palette",
    "#workspace-toggle-sidebar": "sidebar toggle",
  };
  for (const [selector, label] of Object.entries(required)) {
    const el = document.querySelector(selector);
    if (!el) { problems.push(`${label} is missing`); continue; }
    const box = el.getBoundingClientRect();
    if (box.width < 1 || box.height < 1) { problems.push(`${label} is not rendered`); continue; }
    if (box.right < 1 || box.left > doc.clientWidth - 1
        || box.bottom < 1 || box.top > doc.clientHeight - 1) {
      problems.push(`${label} is off screen`);
      continue;
    }
    if (box.height < 24 || box.width < 24) {
      problems.push(`${label} is ${Math.round(box.width)}x${Math.round(box.height)}, under the 24px floor`);
    }
  }

  // The formatting strip is one row inside the editor sheet and holds
  // nineteen controls. When the sheet is narrow they do not fit, and what a
  // user loses is not always something a box measurement can see: the strip's
  // trailing group is sticky and paints its own background, so a control it
  // covers is still inside the strip's box, still the right size, and still
  // impossible to click. The question is therefore asked the way a pointer
  // would ask it — what is actually at the middle of this control?
  const bar = document.querySelector(".format-bar");
  if (bar) {
    const strip = bar.getBoundingClientRect();
    for (const button of bar.querySelectorAll("button")) {
      const box = button.getBoundingClientRect();
      if (box.width < 1 || box.height < 1) continue;
      const name = button.id || button.dataset.editorCommand || "a format control";
      if (box.right > strip.right + 0.5 || box.left < strip.left - 0.5) {
        problems.push(`${name} is clipped out of the format bar`);
        continue;
      }
      const at = document.elementFromPoint(
        Math.round(box.left + box.width / 2),
        Math.round(box.top + box.height / 2),
      );
      if (!at || (at !== button && !button.contains(at))) {
        problems.push(`${name} is covered in the format bar`);
      }
    }
  }

  // A pane track that has collapsed to nothing takes the document with it.
  const editor = document.querySelector(".editor-pane");
  if (editor) {
    const box = editor.getBoundingClientRect();
    if (box.width < 240) problems.push(`editor pane is only ${Math.round(box.width)}px wide`);
  }

  // Anything painted past the right edge is clipped rather than reflowed.
  for (const el of document.querySelectorAll(".shell *")) {
    if (el.offsetParent === null) continue;
    const box = el.getBoundingClientRect();
    if (box.width < 4 || box.height < 4) continue;
    if (box.left >= doc.clientWidth) {
      const name = el.id ? "#" + el.id : (el.className || el.tagName).toString().slice(0, 40);
      problems.push(`${name} starts past the right edge`);
      break;
    }
  }
  return problems;
}"""


def responsive(dist: Path, *, locale: str = "en", theme: str = "light") -> dict[str, Any]:
    """Check that nothing the user needs is clipped, shrunk away or unreachable.

    Desktop software still has to survive a small window. The failure this
    catches is not cosmetic: a control that has scrolled off the edge or
    collapsed under the pointer-target floor cannot be used at all.
    """
    from playwright.sync_api import sync_playwright

    findings: dict[str, Any] = {}
    with _serve(dist) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for width, height in VIEWPORTS:
            page = browser.new_context(viewport={"width": width, "height": height}).new_page()
            page.set_default_timeout(30_000)
            page.add_init_script(INIT_SCRIPT)
            page.goto(url, wait_until="networkidle")
            _dismiss_onboarding(page)
            if theme != "light" or locale != "en":
                _apply(page, theme, locale)
            page.locator("[data-template-id='report']").click()
            page.locator(".codemirror-mount .cm-editor").wait_for(state="visible")
            page.wait_for_timeout(500)
            # Split view is where the workbench is tightest: the editor sheet
            # gives half its width to the preview, and a strip that fits in
            # write view no longer does.
            for view in ("write", "split"):
                page.locator(f'button.view-mode[data-view-mode="{view}"]').click()
                page.wait_for_timeout(500)
                key = f"{width}x{height}" if view == "write" else f"{width}x{height} split"
                findings[key] = page.evaluate(RESPONSIVE_JS)
            page.close()
        browser.close()
    return findings


def shoot(dist: Path, output: Path, *, only: str | None = None) -> list[Path]:
    from playwright.sync_api import sync_playwright

    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    combos = [("light", "en"), ("dark", "en"), ("light", "fa"), ("dark", "fa")]
    for theme, locale in combos:
        label = f"{theme}-{locale}"
        if only and only != label:
            continue
        with _serve(dist) as url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900}, device_scale_factor=2
            )
            page = context.new_page()
            page.set_default_timeout(30_000)
            page.add_init_script(INIT_SCRIPT)
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url, wait_until="networkidle")

            def snap(name: str) -> None:
                path = output / f"{label}-{name}.png"
                page.screenshot(path=str(path))
                written.append(path)

            snap("01-onboarding")
            _dismiss_onboarding(page)
            _apply(page, theme, locale)
            snap("02-start")
            page.locator("#settings-button").click()
            page.wait_for_timeout(300)
            snap("03-settings")
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)

            page.locator("[data-template-id='report']").click()
            page.locator(".codemirror-mount .cm-editor").wait_for(state="visible")
            page.wait_for_timeout(400)
            # Through the editor, not around it. Writing the textarea's value
            # and firing `input` reaches the preview, which reads the buffer,
            # but never reaches CodeMirror, which owns the document: every
            # write-mode shot was of the empty template while the preview
            # beside it showed this sample. Selecting all and inserting text is
            # what a person does, and it goes through the same transaction.
            page.locator(".cm-content").click()
            page.keyboard.press("Control+a")
            page.keyboard.insert_text(SAMPLE)
            page.wait_for_timeout(900)
            # Scroll to the top without moving the caret. Ctrl+Home would put
            # it inside the front matter, whose whole point is that it stays
            # collapsed until asked for — the shot would be of the one state
            # the design deliberately avoids opening in.
            page.evaluate("() => { document.querySelector('.cm-scroller').scrollTop = 0; }")
            page.wait_for_timeout(400)
            snap("04-write")
            page.locator('[data-view-mode="split"]').click()
            page.wait_for_timeout(1100)
            snap("05-split")
            page.keyboard.press("Control+Shift+P")
            page.wait_for_timeout(300)
            snap("06-command-palette")
            page.keyboard.press("Escape")
            page.wait_for_timeout(200)
            if errors:
                print(f"  {label}: page errors {errors[:2]}", file=sys.stderr)
            browser.close()
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("measure", "shoot", "contrast", "responsive"))
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--only", default=None, help="one of light-en, dark-en, light-fa, dark-fa")
    parser.add_argument("--view-mode", default="split", choices=("write", "source", "split"))
    parser.add_argument("--label", default="")
    parser.add_argument("--locale", default="en", choices=("en", "fa"))
    parser.add_argument("--theme", default="light", choices=("light", "dark"))
    args = parser.parse_args(argv)

    dist = args.dist.resolve(strict=True)
    if args.mode == "measure":
        payload = measure(dist, view_mode=args.view_mode)
        if args.label:
            print(f"--- {args.label}")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if args.mode == "responsive":
        findings = responsive(dist, locale=args.locale, theme=args.theme)
        total = 0
        for size, problems in findings.items():
            if not problems:
                print(f"ok   {size}")
                continue
            for problem in problems:
                total += 1
                print(f"FAIL {size:10} {problem}")
        print(f"\n{total} problem(s) across {len(findings)} window sizes")
        return 1 if total else 0

    if args.mode == "contrast":
        report = contrast(dist)
        total = 0
        for theme, surfaces in report.items():
            for surface, failures in surfaces.items():
                for item in failures:
                    total += 1
                    print(
                        f"{theme:5} {surface:9} {item['ratio']:5.2f} "
                        f"(need {item['need']}) {item['element']:44} {item['sample']!r}"
                    )
        print(f"\n{total} text runs below the WCAG AA floor")
        return 1 if total else 0

    written = shoot(dist, args.out.resolve(strict=False), only=args.only)
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Check the export destination dock against clipping and scroll overlap.

Run after build_desktop_frontend.py. This exercises the real frontend in an
isolated browser context with deterministic file/engine bridge fixtures; it
does not launch the installed application, use a native file dialog, or render
a PDF. Zoom cases reduce the CSS viewport and increase device scale together.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import expect, sync_playwright

from audit_desktop_ui import DEFAULT_DIST, ROOT, serve

DEFAULT_OUTPUT = ROOT / "build" / "export-layout-audit"
SOURCE_PATH = r"E:\Downloads\اسناد آزمایشی\Markdown\گزارش تجربه کاربری.md"
OUTPUT_PATH = (
    r"E:\Downloads\Browser.Chrome\اسناد آزمایشی و گزارش‌های انتشار"
    r"\podcast_8_episodes_proofread_v5_نسخه نهایی بررسی تجربه کاربری.pdf"
)

BRIDGE = r"""
globalThis.__exportAudit = {requests: [], pending: null, outputPath: __OUTPUT__};
globalThis.__TAURI__ = {
  core: {invoke: async (command, args = {}) => {
    const audit = globalThis.__exportAudit;
    if (command === 'take_launch_files') return [];
    if (command === 'pick_markdown_file') return __SOURCE__;
    if (command === 'pick_pdf_output') return audit.outputPath;
    if (command === 'sidecar_cancel') {
      audit.requests.push({method: 'cancel', request_id: args.request_id});
      if (audit.pending) {
        audit.pending.reject(new Error('Audit operation cancelled'));
        audit.pending = null;
      }
      return true;
    }
    if (command !== 'sidecar_request') return null;
    if (args.method === 'system.health') {
      return {engine_version: 'layout-fixture', runtime: {platform: 'isolated-browser'}};
    }
    if (args.method === 'system.capabilities') return {methods: ['preview.document_page']};
    if (args.method === 'document.read') {
      return {path: args.params.path, content: '# Layout audit\n\nمتن فارسی و English.',
        kind: 'markdown', read_only: false, revision: 'fixture'};
    }
    if (args.method === 'preview.document_page') {
      return {title: 'Layout audit', lang: 'fa', direction: 'rtl', page: {},
        css: {}, body_classes: '', watermark_html: '', cover: null,
        footer: {enabled: false, html: ''}, math: {expressions: 0},
        content_html: '<h1>پیش‌نمایش آزمایشی</h1>' +
          Array.from({length: 45}, (_, i) => `<p>${i + 1}. متن فارسی و English برای آزمون اسکرول.</p>`).join('')};
    }
    if (['validate.document', 'render.document'].includes(args.method)) {
      audit.requests.push({method: args.method, params: args.params, request_id: args.request_id});
      return new Promise((resolve, reject) => {audit.pending = {resolve, reject};});
    }
    return {};
  }},
  event: {listen: async () => () => {}}
};
""".replace("__SOURCE__", json.dumps(SOURCE_PATH)).replace("__OUTPUT__", json.dumps(OUTPUT_PATH))

# Measure without focusing, clicking, or scrolling a control into view. A
# centre-only hit test misses the partial overlap reported by the user.
DOCK_CHECK = r"""() => {
  const problems = [];
  const rect = node => {
    const box = node.getBoundingClientRect();
    return {left: box.left, top: box.top, right: box.right, bottom: box.bottom,
      width: box.width, height: box.height};
  };
  const visible = node => node && node.getClientRects().length &&
    getComputedStyle(node).visibility !== 'hidden';
  const content = document.querySelector('#export-content');
  const dock = document.querySelector('.export-dock');
  if (!content || !dock) return {problems: ['reserved content/dock regions are missing']};
  const contentBox = rect(content), dockBox = rect(dock);
  if (contentBox.bottom > dockBox.top + 0.75) problems.push('settings scroll area overlaps destination dock');
  if (contentBox.height < 48) problems.push('settings scroll area has less than 48px usable height');
  if (dockBox.bottom > innerHeight + 0.75 || dockBox.top < 0) problems.push('destination dock is outside viewport');
  const controls = {};
  for (const selector of ['#output-path', '#choose-output', '#validate-button', '#export-button', '#cancel-button']) {
    const node = document.querySelector(selector);
    if (!visible(node)) {
      if (selector !== '#cancel-button') problems.push(`${selector} is not visible`);
      continue;
    }
    const box = rect(node);
    controls[selector] = box;
    if (box.width < 24 || box.height < 24) problems.push(`${selector} is smaller than 24px`);
    if (box.left < -0.75 || box.right > innerWidth + 0.75 || box.top < -0.75 || box.bottom > innerHeight + 0.75) {
      problems.push(`${selector} is not wholly inside viewport`);
    }
    // Sample the painted control, including rounded/pill-shaped actions.
    // A bounding-box corner outside the border radius correctly hits its
    // parent and is not evidence that another surface covers the button.
    const style = getComputedStyle(node);
    const radius = Math.min(box.width / 2, box.height / 2,
      Math.max(...['borderTopLeftRadius', 'borderTopRightRadius', 'borderBottomLeftRadius', 'borderBottomRightRadius']
        .map(name => parseFloat(style[name]) || 0)));
    const inset = Math.max(3, Math.ceil(radius * (1 - Math.SQRT1_2)) + 1);
    for (const x of [box.left + inset, (box.left + box.right) / 2, box.right - inset]) {
      for (const y of [box.top + inset, (box.top + box.bottom) / 2, box.bottom - inset]) {
        const hit = document.elementFromPoint(x, y);
        if (!hit || (hit !== node && !node.contains(hit))) {
          problems.push(`${selector} is covered at ${Math.round(x)},${Math.round(y)} by ${hit?.id || hit?.className || 'viewport'}`);
        }
      }
    }
    // Noninteractive toast overlays allow hit tests through to a button, but
    // can still paint over its label and destination text.
    for (const toast of document.querySelectorAll('.toasts .toast')) {
      if (!visible(toast) || Number(getComputedStyle(toast).opacity) === 0) continue;
      const cover = rect(toast);
      if (Math.min(box.right, cover.right) > Math.max(box.left, cover.left) + 1 &&
          Math.min(box.bottom, cover.bottom) > Math.max(box.top, cover.top) + 1) {
        problems.push(`${selector} is visually covered by a toast`);
      }
    }
  }
  const output = document.querySelector('#output-path');
  if (getComputedStyle(output).direction !== 'ltr') problems.push('Windows destination path is not LTR isolated');
  const button = document.querySelector('#export-button');
  if (button.form !== document.querySelector('#export-form') || button.type !== 'submit') {
    problems.push('Create PDF no longer submits export-form');
  }
  if (document.documentElement.scrollWidth > innerWidth + 1 ||
      document.querySelector('#app-main').scrollWidth > document.querySelector('#app-main').clientWidth + 1) {
    problems.push('export page scrolls horizontally');
  }
  return {problems: [...new Set(problems)], content: contentBox, dock: dockBox, controls,
    contentScrollTop: content.scrollTop, contentScrollMax: content.scrollHeight - content.clientHeight};
}"""

FOCUS_CHECK = r"""() => {
  const control = document.activeElement;
  const target = control.closest('.tri-toggle') || control.closest('.toggle') || control;
  const box = target.getBoundingClientRect();
  const content = document.querySelector('#export-content').getBoundingClientRect();
  const pane = document.querySelector('#option-pane').getBoundingClientRect();
  const problems = [];
  if (box.top < Math.max(content.top, pane.top) - 1 ||
      box.bottom > Math.min(content.bottom, pane.bottom) + 1) {
    problems.push('keyboard-focused metadata control is vertically clipped');
  }
  const style = getComputedStyle(target);
  const radius = Math.min(box.width / 2, box.height / 2,
    Math.max(...['borderTopLeftRadius', 'borderTopRightRadius', 'borderBottomLeftRadius', 'borderBottomRightRadius']
      .map(name => parseFloat(style[name]) || 0)));
  const inset = Math.max(3, Math.ceil(radius * (1 - Math.SQRT1_2)) + 1);
  for (const x of [box.left + inset, box.right - inset]) {
    for (const y of [box.top + inset, box.bottom - inset]) {
      const hit = document.elementFromPoint(x, y);
      if (!hit || (hit !== target && !target.contains(hit))) {
        problems.push(`keyboard-focused metadata control is covered by ${hit?.id || hit?.className || 'viewport'}`);
      }
    }
  }
  return {problems: [...new Set(problems)], active: control.id || control.name || control.tagName,
    paneScrollTop: document.querySelector('#option-pane').scrollTop};
}"""


def _matrix() -> list[tuple[int, int, float]]:
    base = [(1920, 1080, 1.0), (1280, 800, 1.0), (840, 640, 1.0), (720, 620, 1.0)]
    return base + [(width, height, zoom) for width, height in [(1280, 800), (840, 640)]
                   for zoom in [1.25, 1.5]]


def _snapshot(page: Any) -> dict[str, Any]:
    page.wait_for_timeout(40)
    return page.evaluate(DOCK_CHECK)


def _keyboard_metadata(page: Any) -> dict[str, Any]:
    tab = page.locator('.option-rail-item[data-group="document"]')
    tab.click()
    controls = page.locator("#option-pane input, #option-pane select, #option-pane button")
    indexes = controls.evaluate_all("""nodes => nodes.flatMap((node, index) =>
      node.tabIndex >= 0 && !node.disabled && node.getClientRects().length ? [index] : [])""")
    if not indexes:
        return {"problems": ["metadata has no keyboard controls"]}
    controls.nth(indexes[0]).focus()
    reached_last = False
    last = controls.nth(indexes[-1])
    for _ in range(len(indexes) + 3):
        if last.evaluate("node => document.activeElement === node"):
            reached_last = True
            break
        page.keyboard.press("Tab")
    result = page.evaluate(FOCUS_CHECK)
    if not reached_last:
        result["problems"].append("Tab did not reach final metadata control")
    return result


def run_audit(dist: Path, output: Path, *, executable_path: str | None = None,
              check_scrollbars: bool = False) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "scope": "Real frontend layout; isolated Tauri/file/render bridge fixtures, no native engine or dialogs",
        "zoom_method": "CSS viewport divided by zoom, device scale multiplied by zoom",
        "scenarios": {},
    }
    with serve(dist) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=executable_path)
        for locale in ["en", "fa"]:
            for theme in ["light", "dark"]:
                for width, height, zoom in _matrix():
                    key = f"{locale}-{theme}-{width}x{height}-{round(zoom * 100)}pct"
                    scenario: dict[str, Any] = {"problems": [], "samples": {}}
                    report["scenarios"][key] = scenario
                    context = browser.new_context(
                        viewport={"width": round(width / zoom), "height": round(height / zoom)},
                        device_scale_factor=zoom, locale="fa-IR" if locale == "fa" else "en-US",
                    )
                    page = context.new_page()
                    page.set_default_timeout(15_000)
                    page.on("pageerror", lambda error, target=scenario: target["problems"].append(str(error)))
                    page.add_init_script(BRIDGE)
                    page.add_init_script(
                        "localStorage.setItem('mardas.desktop.locale', " + json.dumps(locale) + ");"
                        "localStorage.setItem('mardas.desktop.preferences.v1', JSON.stringify("
                        + json.dumps({"theme": theme, "onboardingComplete": True, "reducedMotion": "reduce"}) + "));"
                    )
                    try:
                        page.goto(url, wait_until="networkidle")
                        page.locator("#workflow-quick").click()
                        page.locator("#choose-source").click()
                        page.locator("#choose-output").click()
                        expect(page.locator("#output-path")).to_have_value(OUTPUT_PATH)
                        page.locator("#export-preview iframe").wait_for(state="attached")
                        for position, fraction in [("top", 0), ("middle", 0.5), ("bottom", 1)]:
                            page.locator("#export-content").evaluate(
                                "(node, fraction) => { node.scrollTop = (node.scrollHeight - node.clientHeight) * fraction; }", fraction)
                            scenario["samples"][position] = _snapshot(page)
                            if position == "middle":
                                page.screenshot(path=str(output / f"{key}.png"))
                        scenario["samples"]["metadata-keyboard"] = _keyboard_metadata(page)
                        for action, method in [("#validate-button", "validate.document"), ("#export-button", "render.document")]:
                            page.locator(action).click()
                            expect(page.locator("#cancel-button")).to_be_visible()
                            scenario["samples"][method] = _snapshot(page)
                            received = page.evaluate("method => __exportAudit.requests.filter(request => request.method === method)", method)
                            if len(received) != 1 or received[0]["params"]["output_path"] != OUTPUT_PATH:
                                scenario["problems"].append(f"{method} did not receive current long destination path once")
                            page.locator("#cancel-button").click()
                            expect(page.locator("#cancel-button")).to_be_hidden()
                            scenario["samples"][f"{method}-cancelled"] = _snapshot(page)
                        if width == 1920 or (width == 840 and zoom == 1.25):
                            page.screenshot(path=str(output / f"{key}-cancelled.png"))
                        if width == 1920:
                            # Keep the notifications alive while the dock changes
                            # height. Fresh contexts alone cannot verify that its
                            # ResizeObserver updates the notification boundary.
                            for resized_width, resized_height in [(840, 640), (720, 620), (1920, 1080)]:
                                page.set_viewport_size({"width": resized_width, "height": resized_height})
                                scenario["samples"][f"live-resize-{resized_width}x{resized_height}"] = _snapshot(page)
                            page.locator("#settings-button").click()
                            page.locator("#setting-locale").select_option("fa" if locale == "en" else "en")
                            page.locator('#settings-form button[type="submit"]').click()
                            scenario["samples"]["live-locale-change"] = _snapshot(page)
                        if check_scrollbars:
                            scrollbars = page.evaluate("""() => {
                              const nodes = [document.querySelector('#export-content'), document.querySelector('#option-pane'),
                                document.querySelector('#export-preview iframe')?.contentDocument?.documentElement];
                              return nodes.map(node => node ? {color: getComputedStyle(node).scrollbarColor,
                                width: getComputedStyle(node).scrollbarWidth} : null);
                            }""")
                            scenario["scrollbars"] = scrollbars
                            if any(not item or item["color"] in ["auto", ""] for item in scrollbars):
                                scenario["problems"].append("application or preview scrollbar still uses native colors")
                    except Exception as error:
                        scenario["problems"].append(f"{type(error).__name__}: {error}")
                        page.screenshot(path=str(output / f"{key}-failure.png"))
                    finally:
                        for name, sample in scenario["samples"].items():
                            scenario["problems"].extend(f"{name}: {problem}" for problem in sample.get("problems", []))
                        context.close()
        browser.close()
    report["passed"] = not any(scenario["problems"] for scenario in report["scenarios"].values())
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--executable-path")
    parser.add_argument("--check-scrollbars", action="store_true")
    args = parser.parse_args()
    report = run_audit(args.dist.resolve(), args.out.resolve(), executable_path=args.executable_path,
                       check_scrollbars=args.check_scrollbars)
    failures = {key: scenario["problems"] for key, scenario in report["scenarios"].items() if scenario["problems"]}
    print(json.dumps({"passed": report["passed"], "scenarios": len(report["scenarios"]), "failures": failures,
                      "report": str(args.out.resolve() / "report.json")}, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

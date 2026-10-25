#!/usr/bin/env python3
"""Exercise document width and text size in the real desktop frontend.

Uses isolated browser storage and deterministic file/preview bridge fixtures.
The installed Windows application and personal documents are never opened.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from audit_desktop_editor_ux import BRIDGE_SCRIPT, FIXTURE_B, mode, replace_content
from audit_desktop_ui import DEFAULT_DIST, INIT_SCRIPT, ROOT, open_settings, serve


SAMPLE = "# سند آزمایشی Document\n\n" + "\n\n".join(
    f"{index}. متن فارسی و English برای بررسی آزادی فضای نوشتن و اندازهٔ متن. " * 8
    for index in range(1, 70)
)


def measure(page):
    return page.evaluate("""() => {
      const rect = selector => document.querySelector(selector).getBoundingClientRect().toJSON();
      const size = selector => parseFloat(getComputedStyle(document.querySelector(selector)).fontSize);
      return {width: innerWidth, zoom: Number(document.documentElement.dataset.documentZoom),
        writingWidth: document.documentElement.dataset.writingWidth,
        pane: rect('.editor-pane'), content: rect('.cm-content'),
        reader: rect('#reading-document'),
        proseSize: size('.cm-content'), readerSize: size('#reading-document'),
        previewSize: size('#preview-document'), uiSize: size('.document-identity strong'),
        horizontalOverflow: document.documentElement.scrollWidth > innerWidth + 1};
    }""")


def check_scroll_sync(page, output: Path, locale: str, theme: str):
    wrapped = "متن فارسی و English با چندین سطرِ پیچیده برای بررسی پیمایش. " * 300
    content = f"# Start section\n\n{wrapped}\n\n## Next section\n\n{wrapped}\n\n## Final section\n\nTail."
    mode(page, "source")
    replace_content(page, content)
    mode(page, "split")
    expect(page.locator("#preview-document")).to_contain_text("Next section")
    page.wait_for_timeout(400)
    page.locator("#document-zoom-reset").click()
    for _ in range(10):
        page.locator("#document-zoom-in").click()
    page.locator(".cm-scroller").evaluate("node => {node.scrollTop = 1500}")

    def visible_source():
        return page.evaluate(r"""() => {
          const scroller = document.querySelector('.cm-scroller').getBoundingClientRect();
          const raw = document.querySelector('#markdown-editor').value.split('\n');
          const first = [...document.querySelectorAll('.cm-line')].find(node => {
            const rect = node.getBoundingClientRect();
            return rect.bottom > scroller.top + 1 && rect.top < scroller.bottom;
          });
          const line = raw.indexOf(first?.textContent) + 1;
          const headings = raw.map((text, index) => /^#{1,6} /.test(text) ? index + 1 : 0).filter(Boolean);
          return {line, expected: headings.filter(heading => heading <= line).at(-1) || headings[0],
            active: Number(document.querySelector('#preview-document .source-active')?.dataset.sourceLine)};
        }""")

    page.wait_for_timeout(250)
    first = visible_source()
    assert first["line"] == 3, first  # One source line spans many visual rows.
    assert first["active"] == first["expected"] == 1, first
    page.keyboard.press("Control+Shift+o")
    page.locator("#navigation-query").fill("Next section")
    page.keyboard.press("Enter")
    expect(page.locator("#navigation-modal")).to_be_hidden()
    page.wait_for_timeout(250)
    page.locator(".cm-scroller").evaluate("""node => {
      const heading = [...node.querySelectorAll('.cm-line')].find(line => line.textContent === '## Next section');
      if (!heading) throw new Error('Navigation did not reveal the next source section');
      node.scrollTop += heading.getBoundingClientRect().top - node.getBoundingClientRect().top + 5;
    }""")
    page.wait_for_timeout(250)
    second = visible_source()
    assert second["line"] == 5, second
    assert second["active"] == second["expected"] == 5, second
    assert page.locator("#markdown-editor").input_value() == content
    page.screenshot(path=str(output / f"{locale}-{theme}-wrapped-scroll-sync.png"))
    return [first, second]


def run(dist: Path, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    scenarios = []
    with serve(dist) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for locale, theme in (("en", "light"), ("fa", "light"), ("en", "dark"), ("fa", "dark")):
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = context.new_page()
            page.set_default_timeout(10_000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script(INIT_SCRIPT)
            page.add_init_script(BRIDGE_SCRIPT)
            page.add_init_script(
                "if (!localStorage.getItem('document-view-audit')) {"
                "localStorage.setItem('document-view-audit', 'ready');"
                f"localStorage.setItem('mardas.desktop.locale', {json.dumps(locale)});"
                "localStorage.setItem('mardas.desktop.preferences.v1', JSON.stringify("
                f"{{theme:{json.dumps(theme)},onboardingComplete:true,viewMode:'write',writingWidth:'comfortable'}}));}}"
            )
            page.goto(url, wait_until="networkidle")
            page.evaluate("([path, content]) => {globalThis.__auditFiles[path] = content}", [FIXTURE_B, SAMPLE])
            page.locator("#workflow-open").click()
            expect(page.locator(".cm-content")).to_be_visible()
            for region, close in (("#file-navigator", "#navigator-close"), ("#author-sidebar", "#inspector-close")):
                if page.locator(region).is_visible():
                    page.locator(close).click()
            before = measure(page)
            assert before["writingWidth"] == "full", before
            assert before["content"]["width"] >= before["pane"]["width"] - 20, before
            assert before["content"]["width"] > 1800, before
            original = page.locator("#markdown-editor").input_value()
            checks = ["legacy-default-migrates-to-full-width", "closed-panels-release-full-canvas"]

            page.locator("#document-toggle-width").click()
            expect(page.locator("html")).to_have_attribute("data-writing-width", "readable")
            assert measure(page)["content"]["width"] <= 761
            page.screenshot(path=str(output / f"{locale}-{theme}-readable.png"))
            page.locator("#document-toggle-width").click()
            expect(page.locator("html")).to_have_attribute("data-writing-width", "full")
            checks.append("readable-column-is-an-explicit-reversible-choice")

            # A growing side panel reduces the canvas, and closing it reclaims
            # the same space rather than leaving an invisible reading column.
            page.locator("#workspace-toggle-files").click()
            with_files = measure(page)
            assert with_files["content"]["width"] >= with_files["pane"]["width"] - 20, with_files
            assert with_files["pane"]["width"] < before["pane"]["width"] - 200
            page.locator("#navigator-close").click()
            checks.append("open-panel-and-closed-panel-both-use-available-width")

            measurements = []
            for view in ("write", "source", "read", "split"):
                mode(page, view)
                if view == "read":
                    expect(page.locator("#reading-document")).to_contain_text("سند آزمایشی")
                if view == "split":
                    expect(page.locator("#preview-document")).to_contain_text("سند آزمایشی")
                # Mode changes legitimately schedule their first comparison
                # preview. Settle that request before counting size changes.
                page.wait_for_timeout(400)
                page.locator("#document-zoom-reset").click()
                for zoom, direction, count in ((60, "out", 4), (100, "in", 4), (200, "in", 10)):
                    requests_before = page.evaluate("__auditPreviewRequests.length")
                    for _ in range(count):
                        page.locator(f"#document-zoom-{direction}").click()
                    expect(page.locator("html")).to_have_attribute("data-document-zoom", str(zoom))
                    current = measure(page)
                    expected_size = (18 if view in ("write", "read") else 14) * zoom / 100
                    actual_size = current["readerSize"] if view == "read" else current["proseSize"]
                    assert abs(actual_size - expected_size) < .1, (view, zoom, current)
                    if view == "split":
                        assert abs(current["previewSize"] - 18 * zoom / 100) < .1, current
                    assert current["uiSize"] == before["uiSize"], current
                    assert not current["horizontalOverflow"], current
                    assert page.locator("#markdown-editor").input_value() == original
                    # Text-only changes must not regenerate the reader/engine.
                    assert page.evaluate("__auditPreviewRequests.length") == requests_before
                    measurements.append({"view": view, "zoom": zoom, "textSize": actual_size})
                expect(page.locator("#document-zoom-in")).to_be_disabled()
                checks.append(f"{view}-60-100-200-percent-document-only-and-no-engine-rerender")

            mode(page, "write")
            page.locator(".cm-content").focus()
            page.keyboard.press("Control+0")
            expect(page.locator("#document-zoom-reset")).to_have_text("100%")
            page.keyboard.press("Control+-")
            expect(page.locator("#document-zoom-reset")).to_have_text("90%")
            page.keyboard.press("Control+=")
            expect(page.locator("#document-zoom-reset")).to_have_text("100%")
            page.keyboard.press("Control+Shift+=")
            expect(page.locator("#document-zoom-reset")).to_have_text("110%")
            page.keyboard.press("Control+0")
            checks.append("editor-keyboard-plus-minus-and-reset")
            page.screenshot(path=str(output / f"{locale}-{theme}-full-width.png"))

            scroll_positions = check_scroll_sync(page, output, locale, theme)
            checks.append("200-percent-soft-wrapped-source-scroll-selects-the-visible-section-without-editing")
            mode(page, "write")
            page.locator("#document-zoom-reset").click()

            open_settings(page)
            page.locator("#setting-document-zoom").fill("85")
            page.keyboard.press("Control+-")
            expect(page.locator("html")).to_have_attribute("data-document-zoom", "100")
            page.locator("#settings-form").evaluate("form => form.requestSubmit()")
            expect(page.locator("html")).to_have_attribute("data-document-zoom", "85")
            page.reload(wait_until="networkidle")
            expect(page.locator("html")).to_have_attribute("data-document-zoom", "85")
            expect(page.locator("html")).to_have_attribute("data-writing-width", "full")
            checks.append("settings-input-does-not-zoom-document-and-size-persists-after-reload")

            for width in (840, 390):
                page.set_viewport_size({"width": width, "height": 850})
                for selector in ("#document-toggle-width", "#document-zoom-out", "#document-zoom-reset", "#document-zoom-in"):
                    box = page.locator(selector).bounding_box()
                    assert box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1, (width, selector, box)
                assert not measure(page)["horizontalOverflow"]
                page.screenshot(path=str(output / f"{locale}-{theme}-{width}.png"))
            checks.append("width-and-text-controls-remain-reachable-at-840-and-390")
            assert not errors, errors
            scenarios.append({"locale": locale, "theme": theme, "checks": checks, "sizes": measurements, "scrollPositions": scroll_positions})
            context.close()
        browser.close()
    report = {"status": "passed", "scenarios": scenarios}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "document-view-audit")
    args = parser.parse_args()
    result = run(args.dist, args.output)
    print(f"Document view audit passed: {len(result['scenarios'])} locale/theme scenarios")

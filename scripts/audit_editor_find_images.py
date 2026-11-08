#!/usr/bin/env python3
"""Exercise Find and online-image actions in the real desktop workspace/engine.

Only native file pickers/transport and deterministic HTTPS image bytes are
substituted. Network destinations are intercepted; no external server or user
document/profile is touched.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import traceback

from playwright.sync_api import expect, sync_playwright

from audit_authoring_workspace import BRIDGE
from audit_book_workflow import engine_server
from audit_desktop_ui import DEFAULT_DIST, click_workspace_layout_control

SAMPLE = (
    "# Search and image reference\n\n"
    "Needle and needle and NEEDLE. متن فارسی برای جست‌وجو و انتخاب.\n\n"
    "![First badge](https://images.example.com/first.svg) "
    "![Second badge](https://images.example.com/second.svg)\n\n"
    "![Retry badge](https://retry.example.com/retry.svg)\n\n"
    "Last paragraph.\n"
)
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="24"><rect width="160" height="24" fill="#ff9f00"/><text x="8" y="17">Image fixture</text></svg>'


def run(dist: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "running", "scenarios": []}
    with tempfile.TemporaryDirectory(prefix="find-images-", dir=output) as directory:
        source = Path(directory) / "find-images-reference.md"
        source.write_text(SAMPLE, encoding="utf-8")
        with engine_server(dist) as (url, _calls), sync_playwright() as runtime:
            browser = runtime.chromium.launch()
            for locale, theme, width in [
                ("en", "light", 1440), ("fa", "dark", 1440),
                ("en", "dark", 680), ("fa", "light", 680),
                ("en", "light", 360), ("fa", "dark", 360),
            ]:
                case = {"locale": locale, "theme": theme, "width": width, "checks": []}
                report["scenarios"].append(case)
                context = browser.new_context(viewport={"width": width, "height": 1100})
                context.add_init_script(
                    "globalThis.__writingFixture=" + json.dumps({"pick": str(source)}) + ";"
                    "localStorage.setItem('mardas.desktop.locale'," + json.dumps(locale) + ");"
                    "localStorage.setItem('mardas.desktop.preferences.v1',JSON.stringify("
                    + json.dumps({"theme": theme, "onboardingComplete": True}) + "));" + BRIDGE
                )
                requests: list[dict] = []
                recovery = {"enabled": False}

                def image_route(route):
                    request = route.request
                    requests.append({"url": request.url, "referer": request.headers.get("referer")})
                    if "retry.example.com" in request.url and not recovery["enabled"]:
                        route.fulfill(status=503, body="not available", content_type="text/plain")
                    else:
                        route.fulfill(status=200, body=SVG, content_type="image/svg+xml")

                context.route("https://images.example.com/**", image_route)
                context.route("https://retry.example.com/**", image_route)
                errors: list[str] = []
                page = context.new_page()
                page.set_default_timeout(15_000)
                page.on("pageerror", lambda error: errors.append(str(error)))
                try:
                    page.goto(url, wait_until="networkidle")
                    page.locator("#workflow-open").click()
                    buffer = page.locator("#markdown-editor")
                    editor = page.locator(".cm-content")
                    expect(buffer).to_have_value(SAMPLE)
                    images = page.locator(".cm-content .online-image-control")
                    expect(images).to_have_count(3)
                    assert not requests, requests
                    expect(page.locator(".cm-content img[src^='http']")).to_have_count(0)
                    case["checks"].append("no online image request before a document image action")

                    editor.focus()
                    page.keyboard.press("Control+f")
                    query = page.locator("#find-query")
                    query.fill("")
                    for char in "needle":
                        page.keyboard.type(char)
                        expect(query).to_be_focused()
                    expect(page.locator("#find-count")).to_have_text("1/3")
                    expect(page.locator(".cm-findMatch")).to_have_count(3)
                    expect(page.locator(".cm-findMatch-current")).to_have_count(1)
                    page.keyboard.press("Enter")
                    expect(query).to_be_focused()
                    expect(page.locator("#find-count")).to_have_text("2/3")
                    page.keyboard.press("Shift+Enter")
                    expect(page.locator("#find-count")).to_have_text("1/3")
                    page.keyboard.press("Shift+Enter")
                    expect(page.locator("#find-count")).to_have_text("3/3")
                    page.keyboard.press("Enter")
                    expect(page.locator("#find-count")).to_have_text("1/3")
                    case["checks"].append("query typing retains input focus; all matches paint and Enter/Shift+Enter wrap")

                    query.fill("absent-search-term")
                    expect(page.locator("#find-bar")).to_have_attribute("data-no-results", "true")
                    for selector in ("#find-next", "#find-previous", "#replace-one", "#replace-all"):
                        expect(page.locator(selector)).to_be_disabled()
                    query.evaluate("e=>e.dispatchEvent(new KeyboardEvent('keydown',{key:'ا',code:'KeyH',keyCode:72,ctrlKey:true,bubbles:true,cancelable:true}))")
                    expect(query).to_be_focused()
                    expect(page.locator("#find-replace-row")).to_be_visible()
                    expect(query).to_have_value("absent-search-term")
                    page.locator("#replace-query").focus()
                    page.locator("#replace-query").evaluate("e=>e.dispatchEvent(new KeyboardEvent('keydown',{key:'ب',code:'KeyF',keyCode:70,ctrlKey:true,bubbles:true,cancelable:true}))")
                    expect(query).to_be_focused()
                    query.fill("needle")
                    replacement = page.locator("#replace-query")
                    replacement.fill("thread")
                    find_geometry = page.evaluate("""() => {
                      const bar=document.querySelector('#find-bar').getBoundingClientRect();
                      const canvas=document.querySelector('.editor-surface').getBoundingClientRect();
                      return {bottom:bar.bottom,canvasTop:canvas.top,left:bar.left,right:bar.right,
                        width:innerWidth,scrollY,overflow:document.documentElement.scrollWidth>innerWidth+1};
                    }""")
                    assert find_geometry["bottom"] <= find_geometry["canvasTop"] + 1, find_geometry
                    assert find_geometry["left"] >= -1 and find_geometry["right"] <= width + 1, find_geometry
                    assert not find_geometry["overflow"] and find_geometry["scrollY"] == 0, find_geometry
                    case["find_geometry"] = find_geometry
                    page.screenshot(path=str(output / f"{locale}-{theme}-{width}-find.png"))
                    page.locator("#replace-one").click()
                    expect(buffer).to_have_value(SAMPLE.replace("Needle", "thread", 1))
                    page.keyboard.press("Control+z")
                    expect(buffer).to_have_value(SAMPLE)
                    query.focus()
                    page.keyboard.press("Escape")
                    expect(page.locator("#find-bar")).to_be_hidden()
                    expect(page.locator(".cm-findMatch")).to_have_count(0)
                    case["checks"].append("empty results disable actions; Persian-layout physical Ctrl+H/F work in Find inputs; one Undo restores exact Markdown; Escape clears highlights")

                    backgrounds = []
                    for mode in ("source", "write"):
                        page.locator(f'[data-view-mode="{mode}"]').click()
                        backgrounds.append(page.locator("#format-bar").evaluate("e=>getComputedStyle(e).backgroundColor"))
                    assert backgrounds[0] == backgrounds[1], backgrounds
                    editor.focus()
                    page.keyboard.press("Control+Home")
                    page.keyboard.press("Control+Shift+End")
                    selection = page.locator(".cm-selectionBackground").first
                    expect(selection).to_be_visible()
                    paint = selection.evaluate("e=>getComputedStyle(e).backgroundColor")
                    expected_paint = page.evaluate("""() => {
                      const sample = document.createElement('span');
                      sample.style.backgroundColor = 'var(--cm-selection)';
                      document.body.append(sample);
                      const color = getComputedStyle(sample).backgroundColor;
                      sample.remove();
                      return color;
                    }""")
                    assert paint == expected_paint, (paint, expected_paint)
                    field_paint = page.locator("#find-query").evaluate("e=>getComputedStyle(e,'::selection').backgroundColor")
                    assert field_paint == expected_paint, (field_paint, expected_paint)
                    page.keyboard.press("ArrowLeft")
                    case["selection_paint"] = paint
                    case["field_selection_paint"] = field_paint
                    case["checks"].append("Write/Source toolbar surfaces agree and document selection follows the blue palette")

                    good = page.locator('.cm-content .online-image-control[data-online-image-origin="https://images.example.com"]')
                    good.first.locator("button").click()
                    expect(page.locator('.cm-content .online-image-control[data-online-image-origin="https://images.example.com"][data-online-image-state="loaded"]')).to_have_count(2)
                    assert all(not item["referer"] for item in requests), requests
                    assert not any("retry.example.com" in item["url"] for item in requests), requests
                    expect(buffer).to_have_value(SAMPLE)
                    case["checks"].append("one explicit action loads both same-host images without Referer or Markdown edits")

                    failed = page.locator('.cm-content .online-image-control[data-online-image-origin="https://retry.example.com"]')
                    failed.locator("button").click()
                    expect(failed).to_have_attribute("data-online-image-state", "error")
                    expect(failed.locator("img")).to_have_count(0)
                    recovery["enabled"] = True
                    failed.locator("button").click()
                    expect(failed).to_have_attribute("data-online-image-state", "loaded")
                    case["checks"].append("failed online image offers Retry and recovers without a broken-image glyph")

                    page.locator('[data-view-mode="read"]').click()
                    expect(page.locator('#reading-document .online-image-control[data-online-image-state="loaded"]')).to_have_count(3, timeout=30_000)
                    if width >= 1100:
                        page.locator('[data-view-mode="write"]').click()
                        click_workspace_layout_control(page, "#workspace-toggle-preview")
                        expect(page.locator('#preview-document .online-image-control[data-online-image-state="loaded"]')).to_have_count(3, timeout=30_000)
                        click_workspace_layout_control(page, "#workspace-toggle-preview")
                    else:
                        page.locator('[data-view-mode="write"]').click()
                    expect(buffer).to_have_value(SAMPLE)
                    case["checks"].append("session host grants are shared by Write and Read, plus side preview on desktop")

                    page.locator("#tab-new-document").click()
                    editor.click()
                    page.keyboard.insert_text("![New document image](https://images.example.com/new-document.svg)\n")
                    page.keyboard.press("Control+Home")
                    page.keyboard.press("Control+End")
                    page.keyboard.press("Enter")
                    expect(page.locator('.cm-content .online-image-control')).to_have_attribute("data-online-image-state", "blocked")
                    page.wait_for_timeout(300)
                    assert not any("new-document.svg" in item["url"] for item in requests), requests
                    assert source.read_bytes() == SAMPLE.encode("utf-8")
                    assert not page.evaluate("document.documentElement.scrollWidth>innerWidth+1")
                    assert not errors, errors
                    case["checks"].append("host grants do not leak into another document; original file stays byte-identical")
                    page.screenshot(path=str(output / f"{locale}-{theme}-{width}.png"))
                    case["status"] = "passed"
                except Exception as error:
                    case["status"] = "failed"
                    case["error"] = (str(error) or traceback.format_exc(limit=3))[:3000]
                    page.screenshot(path=str(output / f"{locale}-{theme}-{width}-failure.png"))
                finally:
                    case["page_errors"] = errors
                    case["requests"] = requests
                    context.close()
            browser.close()
    report["status"] = "passed" if all(case["status"] == "passed" for case in report["scenarios"]) else "failed"
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--output", type=Path, default=Path("build/editor-polish/find-images"))
    args = parser.parse_args()
    result = run(args.dist.resolve(), args.output.resolve())
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(result["status"] != "passed")

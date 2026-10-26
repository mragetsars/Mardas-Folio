#!/usr/bin/env python3
"""Real editor/engine acceptance of selection, table rendering and pane controls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import traceback

from playwright.sync_api import expect, sync_playwright

from audit_authoring_workspace import BRIDGE
from audit_book_workflow import engine_server
from audit_desktop_ui import DEFAULT_DIST

SAMPLE = (
    ("متن فارسی برای انتخاب راحت و خواندن طولانی، همراه با English words و عدد ۱۲۳. " * 12)
    + "\n\n# Table reference\n\n"
    + "| `Option` | **Meaning *nested*** | Value |\n"
    + "| :--- | :---: | ---: |\n"
    + "| `--title` | **bold** and *italic* and ~~gone~~ | $E=mc^2$ |\n"
    + r"| a\|b | `x\|y` | [safe](https://example.com) |"
    + "\n"
    + "| short |\n"
    + '| <img src=x onerror="globalThis.__tableInjected=1"> | &amp; \\*literal | ` a ` |\n'
    + "| https://example.com | <https://example.com> | ~sub~ ^sup^ |\n"
    + "\n> | Nested | Value |\n> | --- | --- |\n> | **Nested bold** | `nested code` |\n"
    + "\n![badge](https://example.com/"
    + "long-" * 30
    + ".png)\n"
    + "\n## End\n\nLast paragraph.\n"
)


def run(dist: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "running", "scenarios": []}
    with tempfile.TemporaryDirectory(prefix="interaction-fixture-", dir=output) as directory:
        source = Path(directory) / "interaction-reference.md"
        source.write_text(SAMPLE, encoding="utf-8")
        with engine_server(dist) as (url, _calls), sync_playwright() as runtime:
            browser = runtime.chromium.launch()
            for locale, theme, width in [
                ("en", "light", 1600),
                ("fa", "dark", 1600),
                ("en", "dark", 1108),
                ("fa", "light", 768),
            ]:
                case = {"locale": locale, "theme": theme, "width": width, "checks": []}
                report["scenarios"].append(case)
                context = browser.new_context(viewport={"width": width, "height": 1000})
                context.add_init_script(
                    "globalThis.__writingFixture=" + json.dumps({"pick": str(source)}) + ";"
                    "localStorage.setItem('mardas.desktop.locale'," + json.dumps(locale) + ");"
                    "localStorage.setItem('mardas.desktop.preferences.v1',JSON.stringify("
                    + json.dumps({"theme": theme, "onboardingComplete": True})
                    + "));"
                    + BRIDGE
                )
                errors = []
                page = context.new_page()
                page.set_default_timeout(15000)
                page.on("pageerror", lambda error: errors.append(str(error)))
                try:
                    page.goto(url, wait_until="networkidle")
                    page.locator("#workflow-open").click()
                    buffer = page.locator("#markdown-editor")
                    editor = page.locator(".cm-content")
                    expect(buffer).to_have_value(SAMPLE)
                    expect(page.locator(".cm-md-image-missing")).to_be_visible()
                    assert (
                        page.locator(".cm-md-image-missing code")
                        .get_attribute("title")
                        .startswith("https://example.com/")
                    )
                    assert page.locator('.cm-content img[src^="http"]').count() == 0
                    table = page.locator(".cm-md-table table").first
                    expect(table).to_be_visible()
                    expect(table.locator("th code")).to_have_text("Option")
                    expect(table.locator("th strong em")).to_have_text("nested")
                    expect(table.locator("tbody tr").first.locator("strong")).to_have_text("bold")
                    expect(table.locator("tbody tr").first.locator("em")).to_have_text("italic")
                    expect(table.locator("s")).to_have_text("gone")
                    expect(table.locator("mjx-container svg")).to_be_visible()
                    expect(table.locator("tbody tr").nth(1).locator("td").nth(0)).to_have_text(
                        "a|b"
                    )
                    expect(table.locator("tbody tr").nth(1).locator("code")).to_have_text("x|y")
                    expect(table.locator("tbody tr").nth(2).locator("td")).to_have_count(3)
                    expect(table.locator("tbody tr").last.locator("td").nth(0)).to_have_text(
                        "https://example.com"
                    )
                    expect(table.locator("tbody tr").last.locator("td").nth(1)).to_have_text(
                        "https://example.com"
                    )
                    expect(
                        page.locator(".cm-md-table table").nth(1).locator("strong")
                    ).to_have_text("Nested bold")
                    assert table.locator("img,script,a[href]").count() == 0
                    assert not page.evaluate("Boolean(globalThis.__tableInjected)")
                    assert (
                        table.locator("th").nth(1).evaluate("e=>getComputedStyle(e).textAlign")
                        == "center"
                    )
                    assert (
                        table.locator("th").nth(2).evaluate("e=>getComputedStyle(e).textAlign")
                        == "right"
                    )
                    case["checks"].append(
                        "nested inline formats, math, escaped pipes, ragged rows, alignment and safe HTML in real table widget"
                    )
                    table.locator("tbody code").first.click()
                    expect(page.locator(".cm-md-table table th code")).to_have_count(0)
                    page.keyboard.press("Control+End")
                    expect(table).to_be_visible()
                    expect(buffer).to_have_value(SAMPLE)
                    case["checks"].append(
                        "click opens table source and leaving rerenders without rewriting Markdown"
                    )

                    editor.focus()
                    page.keyboard.press("Control+Home")
                    for _ in range(4):
                        page.keyboard.press("Shift+ArrowDown")
                    expect(page.locator(".cm-selectionBackground").first).to_be_visible()
                    paint = editor.evaluate("""e=>({native:getComputedStyle(e,'::selection').backgroundColor,
                      child:getComputedStyle(e.querySelector('.cm-line'),'::selection').backgroundColor,
                      focused:getComputedStyle(document.querySelector('.cm-selectionBackground')).backgroundColor,
                      active:[...document.querySelectorAll('.cm-activeLine')].map(n=>getComputedStyle(n).backgroundColor)})""")
                    assert paint["native"] == paint["child"] == "rgba(0, 0, 0, 0)", paint
                    assert all(color == "rgba(0, 0, 0, 0)" for color in paint["active"]), paint
                    page.screenshot(path=str(output / f"{locale}-{theme}-{width}-selection.png"))
                    page.keyboard.press("Control+b")
                    page.keyboard.press("Control+z")
                    expect(buffer).to_have_value(SAMPLE)
                    case["selection"] = paint
                    case["checks"].append(
                        "single selection paint layer over wrapped RTL text, no active-line tint, formatting and Undo preserve source"
                    )

                    preview = page.locator("#workspace-toggle-preview")
                    inspector = page.locator("#workspace-toggle-sidebar")
                    assert preview.locator("use").get_attribute("href") != inspector.locator(
                        "use"
                    ).get_attribute("href")
                    preview.click()
                    expect(page.locator("#preview-pane")).to_be_visible()
                    expect(preview).to_have_attribute("aria-expanded", "true")
                    toolbar = page.locator(".cm-selection-toolbar:visible")
                    if toolbar.count():
                        page.wait_for_function("""()=>{
                          const t=document.querySelector('.cm-selection-toolbar');
                          if(!t || !t.getClientRects().length)return true;
                          const a=t.getBoundingClientRect(),b=document.querySelector('.cm-editor').getBoundingClientRect();
                          return a.left>=b.left-1&&a.right<=b.right+1;
                        }""")
                    page.locator(".cm-md-table tbody code").first.click()
                    page.keyboard.type("CELL_ENTRY_")
                    expect(buffer).to_have_value(
                        SAMPLE.replace("| `--title`", "| CELL_ENTRY_`--title`")
                    )
                    page.keyboard.press("Control+z")
                    expect(buffer).to_have_value(SAMPLE)
                    page.keyboard.press("Control+End")
                    case["checks"].append(
                        "selection toolbar stays in its pane; table click replaces a prior range with a precise cell caret"
                    )
                    expect(
                        page.locator(
                            '#preview-document .md2pdf-image-placeholder[data-md2pdf-blocked-reason="remote"]'
                        )
                    ).to_be_visible(timeout=30000)
                    header = page.locator("#preview-pane .content-view-header strong")
                    assert header.evaluate("e=>e.scrollWidth<=e.clientWidth+1"), (
                        "Preview heading is truncated"
                    )
                    placeholder = page.locator(
                        '#preview-document .md2pdf-image-placeholder[data-md2pdf-blocked-reason="remote"]'
                    )
                    assert (
                        placeholder.locator("span").evaluate("e=>getComputedStyle(e).textOverflow")
                        == "ellipsis"
                    )
                    case["checks"].append(
                        "preview and inspector use distinct icons and state; full heading and compact image placeholder"
                    )

                    if width > 1100:
                        handle = page.locator("#preview-resizer")
                        box = handle.bounding_box()
                        assert box
                        before = int(handle.get_attribute("aria-valuenow"))
                        x, y = box["x"] + box["width"] / 2, box["y"] + 120
                        page.mouse.move(x, y)
                        page.mouse.down()
                        page.mouse.move(x + (48 if locale == "fa" else -48), y, steps=4)
                        assert int(handle.get_attribute("aria-valuenow")) != before
                        visual = handle.evaluate(
                            "e=>({background:getComputedStyle(e).backgroundColor,line:getComputedStyle(e,'::before').width,hit:e.getBoundingClientRect().width})"
                        )
                        assert (
                            visual["background"] == "rgba(0, 0, 0, 0)"
                            and float(visual["line"][:-2]) <= 2
                        ), visual
                        assert visual["hit"] >= 10, visual
                        page.keyboard.press("Escape")
                        assert int(handle.get_attribute("aria-valuenow")) == before
                        assert page.locator("html").get_attribute("data-pane-resizing") is None
                        page.mouse.up()
                        handle.focus()
                        page.keyboard.press("Home")
                        assert int(handle.get_attribute("aria-valuenow")) == 340
                        outline = handle.evaluate("""e=>({width:getComputedStyle(e).outlineWidth,
                          visible:e.matches(':focus-visible'), inline:e.style.cssText, rules:[...document.styleSheets].flatMap(s=>[...s.cssRules]
                            .filter(r=>r.selectorText?.includes('focus-visible')&&e.matches(r.selectorText))
                            .map(r=>r.cssText))})""")
                        assert outline["width"] == "0px", outline
                        box = handle.bounding_box()
                        x, y = box["x"] + box["width"] / 2, box["y"] + 120
                        page.mouse.move(x, y)
                        page.mouse.down()
                        page.mouse.move(x + (32 if locale == "fa" else -32), y)
                        handle.evaluate("e=>e.releasePointerCapture(1)")
                        expect(page.locator(".pane-resizer.is-dragging")).to_have_count(0)
                        assert page.locator("html").get_attribute("data-pane-resizing") is None
                        page.mouse.up()
                        case["checks"].append(
                            "wide hit target with subtle 2px divider, pointer drag, Escape restores width, keyboard resizing remains available"
                        )
                    expect(buffer).to_have_value(SAMPLE)
                    assert source.read_text(encoding="utf-8") == SAMPLE
                    assert not errors, errors
                    page.screenshot(path=str(output / f"{locale}-{theme}-{width}-panels.png"))
                    case["status"] = "passed"
                except Exception as error:
                    case["status"] = "failed"
                    case["error"] = (str(error) or traceback.format_exc(limit=2))[:1800]
                    page.screenshot(path=str(output / f"{locale}-{theme}-{width}-failure.png"))
                finally:
                    context.close()
            browser.close()
    report["status"] = (
        "passed" if all(c["status"] == "passed" for c in report["scenarios"]) else "failed"
    )
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--out", type=Path, default=Path("build/interaction-details/acceptance"))
    args = parser.parse_args()
    result = run(args.dist, args.out)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(result["status"] != "passed")

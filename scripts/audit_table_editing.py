#!/usr/bin/env python3
"""Exercise visual table cell editing with the actual CodeMirror adapter."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import traceback

from playwright.sync_api import expect, sync_playwright
from lib.audit.desktop import serve

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = (
    "# Table editor\n\n"
    "| `Option` | **Meaning *nested*** | Value |\n"
    "| :--- | :---: | ---: |\n"
    "| `--title` | **bold** and *italic* | $E=mc^2$ |\n"
    "| a\\|b | ~~removed~~ | [reference](https://example.com) |\n"
    "| short |\n"
    "\n> | Nested | Value |\n> | --- | ---: |\n> | **first** | `nested` |\n"
    "\n## End\n\nLast paragraph.\n"
)

HTML = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="/styles/base.css"><link rel="stylesheet" href="/styles/workspace.css">
<link rel="stylesheet" href="/styles/authoring.css"><link rel="stylesheet" href="/styles/writer-workspace.css">
<link rel="stylesheet" href="/styles/table-editing.css"><link rel="stylesheet" href="/styles/interaction-details.css"></head>
<body data-view="workspace"><button id="outside">Outside</button>
<div class="editor-pane" style="display:block;height:850px;width:100%"><textarea id="source"></textarea></div>
<script type="module">import {createCodeMirrorEditorAdapter} from '/js/vendor/codemirror-editor.bundle.mjs';
window.adapter=createCodeMirrorEditorAdapter(document.querySelector('#source'),{mode:'live',theme:'dark'});
</script></body></html>"""


def run(dist: Path, output: Path, bundle: Path | None) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "running", "scenarios": []}
    with serve(dist) as url, sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        for locale, theme, width in [("en", "light", 1440), ("fa", "dark", 1440), ("en", "dark", 680), ("fa", "light", 360)]:
            case = {"locale": locale, "theme": theme, "width": width, "checks": []}
            report["scenarios"].append(case)
            page = browser.new_page(viewport={"width": width, "height": 1000})
            page.set_default_timeout(10000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/table-fixture.html", lambda route: route.fulfill(body=HTML, content_type="text/html"))
            if bundle:
                page.route("**/js/vendor/codemirror-editor.bundle.mjs", lambda route: route.fulfill(path=str(bundle), content_type="text/javascript"))
            try:
                page.goto(url + "/table-fixture.html")
                page.wait_for_function("Boolean(window.adapter)")
                page.evaluate("v=>{document.documentElement.lang=v.locale;document.documentElement.dir=v.locale==='fa'?'rtl':'ltr';document.documentElement.dataset.theme=v.theme;adapter.value=v.text;adapter.setSelectionRange(v.text.length)}", {"locale": locale, "theme": theme, "text": SAMPLE})
                grid = page.locator(".cm-md-table").first
                cell = grid.locator('[data-table-row="1"][data-table-column="1"]')
                cell.click()
                panel = page.locator(".cm-table-cell-editor")
                value = panel.locator("textarea")
                expect(panel).to_be_visible()
                expect(value).to_have_value("**bold** and *italic*")
                expect(grid.locator("table")).to_be_visible()
                assert not value.evaluate("e=>document.querySelector('.cm-content').contains(e)")
                value.fill("**changed** and a|b")
                expect(panel.locator(".cm-table-cell-preview strong")).to_have_text("changed")
                value.press("Enter")
                expect(panel).to_have_count(0)
                edited = SAMPLE.replace("**bold** and *italic*", "**changed** and a\\|b")
                expect(page.locator("#source")).to_have_value(edited)
                expect(cell.locator("strong")).to_have_text("changed")
                page.evaluate("adapter.runCommand('undo')")
                expect(page.locator("#source")).to_have_value(SAMPLE)
                case["checks"].append("cell editing keeps grid rendered, previews inline formatting, escapes new pipes, one Undo restores exact Markdown")

                cell.click()
                value.fill("DISCARDED")
                value.press("Escape")
                expect(page.locator("#source")).to_have_value(SAMPLE)
                cell.click()
                value.fill("Committed by Tab")
                value.press("Tab")
                expect(value).to_have_value("$E=mc^2$")
                value.press("Shift+Tab")
                expect(value).to_have_value("Committed by Tab")
                value.press("Escape")
                expect(page.locator("#source")).to_have_value(SAMPLE.replace("**bold** and *italic*", "Committed by Tab"))
                page.evaluate("adapter.runCommand('undo')")
                expect(page.locator("#source")).to_have_value(SAMPLE)
                case["checks"].append("Escape cancels draft; Tab/Shift+Tab apply and navigate cells without exposing table pipes")

                cell.click()
                value.fill("Outside commit")
                page.locator("#outside").click()
                expect(panel).to_have_count(0)
                expect(page.locator("#source")).to_have_value(SAMPLE.replace("**bold** and *italic*", "Outside commit"))
                page.evaluate("adapter.runCommand('undo')")
                expect(page.locator("#source")).to_have_value(SAMPLE)

                cell.click()
                add_column = "Add column after" if locale == "en" else "افزودن ستون بعدی"
                panel.get_by_role("button", name=add_column, exact=True).click()
                expect(grid.locator("th")).to_have_count(4)
                expect(value).to_have_value("")
                value.fill("New column")
                value.press("Enter")
                expect(grid.locator("tbody tr").first.locator("td").nth(2)).to_have_text("New column")
                # Cell commit and structural edit are independently undoable.
                page.evaluate("adapter.runCommand('undo');adapter.runCommand('undo')")
                expect(page.locator("#source")).to_have_value(SAMPLE)
                case["checks"].append("outside click applies draft; added empty column preserves its index and alignment, source returns exactly through Undo")

                nested = page.locator(".cm-md-table").nth(1)
                nested.locator('[data-table-row="1"][data-table-column="0"]').click()
                add_row = "Add row below" if locale == "en" else "افزودن ردیف پایین"
                panel.get_by_role("button", name=add_row, exact=True).click()
                value.fill("ردیف تازه")
                value.press("Enter")
                assert "> | ردیف تازه" in page.locator("#source").input_value()
                expect(nested.locator("tbody tr")).to_have_count(2)
                page.evaluate("adapter.runCommand('undo');adapter.runCommand('undo')")
                expect(page.locator("#source")).to_have_value(SAMPLE)

                cell.click()
                value.fill('<img src=x onerror="globalThis.__tableInjected=1">')
                assert page.locator(".cm-table-cell-preview img").count() == 0
                assert page.evaluate("Boolean(globalThis.__tableInjected)") is False
                geometry = panel.bounding_box()
                assert geometry and geometry["x"] >= 0 and geometry["x"] + geometry["width"] <= width + 1, geometry
                page.screenshot(path=str(output / f"{locale}-{theme}-{width}.png"))
                value.press("Escape")
                expect(page.locator("#source")).to_have_value(SAMPLE)
                assert not errors, errors
                case["checks"].append("nested table rows preserve blockquote prefixes; draft preview treats HTML as text; popup remains inside narrow viewport")
                case["status"] = "passed"
            except Exception:
                case["status"] = "failed"
                case["error"] = traceback.format_exc(limit=3)[-2500:]
                page.screenshot(path=str(output / f"{locale}-{theme}-{width}-failure.png"))
            finally:
                page.close()
        browser.close()
    report["status"] = "passed" if all(case["status"] == "passed" for case in report["scenarios"]) else "failed"
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "apps/desktop/frontend")
    parser.add_argument("--output", type=Path, default=ROOT / "build/table-editing/acceptance")
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    result = run(args.dist.resolve(), args.output.resolve(), args.bundle.resolve() if args.bundle else None)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(result["status"] != "passed")

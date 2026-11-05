#!/usr/bin/env python3
"""Measure table identifiers and native source gutters in both UI directions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import traceback

from playwright.sync_api import expect, sync_playwright

from audit_desktop_ui import ROOT, serve

HTML = """<!doctype html><html lang="__LANG__" dir="__DIR__" data-theme="__THEME__"><head><meta charset="utf-8">
<link rel="stylesheet" href="/styles.css"><link rel="stylesheet" href="/workspace.css">
<link rel="stylesheet" href="/authoring.css"><link rel="stylesheet" href="/writer-workspace.css">
<link rel="stylesheet" href="/interaction-details.css"><link rel="stylesheet" href="/code-blocks.css">
<link rel="stylesheet" href="/table-editing.css"><link rel="stylesheet" href="/bidi-layout.css">
<style>body{margin:0;display:block;overflow:hidden}.fixture{display:grid;grid-template-columns:minmax(0,1fr);grid-template-rows:540px minmax(0,1fr);gap:16px;width:100%;height:100vh;box-sizing:border-box;padding:16px}body[data-view=workspace] .fixture>.editor-pane{grid-column:1;grid-row:1;height:540px;min-width:0;width:100%;display:block}#document{grid-column:1;grid-row:2;height:300px;min-width:0;overflow:auto;padding:12px;box-sizing:border-box}.cm-md-table{max-width:100%}</style></head>
<body data-view="workspace"><div class="fixture"><div class="editor-pane"><textarea id="source"></textarea></div>
<article id="document" class="document-content" dir="rtl"><p>عبارت <code>AdaptiveCruiseTest</code> در متن فارسی.</p>
<div class="table-wrap"><table><thead><tr><th>کنترل</th><th>توضیح</th><th>خروجی</th></tr></thead><tbody>
<tr><td><code>AdaptiveCruiseTest</code></td><td><code>BrakeController</code> و یک توضیح فارسی چندکلمه‌ای برای ستون</td><td><code>SteeringController</code></td></tr>
<tr><td><code>AutoDriver</code></td><td>متن فارسی با چند کلمه برای شکستن عادی سطر</td><td><code>brake_command = true</code></td></tr>
</tbody></table></div></article></div><script type="module">
import {createCodeMirrorEditorAdapter} from '/js/vendor/codemirror-editor.bundle.mjs';
window.adapter=createCodeMirrorEditorAdapter(document.querySelector('#source'),{mode:'source',theme:document.documentElement.dataset.theme});
</script></body></html>"""

PERSIAN = "# راهنمای کنترل خودرو\n\n" + ("متن فارسی شامل AdaptiveCruiseTest و عدد ۱۴۰۵ برای بررسی جهت و انتخاب. " * 5) + "\n\n```javascript\nconst controller = 'LTR';\n```\n\nپایان سند.\n"
ENGLISH = "# English source\n\nA short source paragraph and فارسی mixed text.\n\n```javascript\nconst controller = 'LTR';\n```\n"
TABLE = "# Table\n\n| کنترل | توضیح | خروجی |\n| --- | --- | --- |\n| `AdaptiveCruiseTest` | `BrakeController` و متن فارسی | `SteeringController` |\n| `AutoDriver` | متن فارسی | `brake_command = true` |\n\nTail.\n"
INLINE = "متن فارسی قبل از `AutoDriver(value > 1)` و ادامهٔ متن فارسی.\n\nTail.\n"


def run(dist: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "running", "cases": []}
    with serve(dist) as url, sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        for locale, theme, width in [("en", "dark", 1440), ("fa", "dark", 680), ("en", "light", 360), ("fa", "light", 360)]:
            case = {"locale": locale, "theme": theme, "width": width, "checks": []}
            report["cases"].append(case)
            page = browser.new_page(viewport={"width": width, "height": 1000})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            markup = HTML.replace("__LANG__", locale).replace("__DIR__", "rtl" if locale == "fa" else "ltr").replace("__THEME__", theme)
            page.route("**/bidi-layout-fixture.html", lambda route: route.fulfill(body=markup, content_type="text/html"))
            try:
                page.goto(url + "/bidi-layout-fixture.html")
                page.wait_for_function("Boolean(window.adapter)")
                for text, direction in [(PERSIAN, "rtl"), (ENGLISH, "ltr"), ('---\ndir: rtl\n---\n' + ENGLISH, "rtl")]:
                    page.evaluate("text=>{adapter.value=text;adapter.setSelectionRange(text.length)}", text)
                    expect(page.locator(".cm-editor")).to_have_attribute("data-source-direction", direction)
                    page.wait_for_timeout(80)
                    metrics = page.locator(".cm-editor").evaluate("""editor=>{
                      const scroller=editor.querySelector('.cm-scroller'),gutters=editor.querySelector('.cm-gutters');
                      const s=scroller.getBoundingClientRect(),g=gutters.getBoundingClientRect();
                      const code=[...editor.querySelectorAll('.cm-line')].find(e=>e.textContent.startsWith('const controller'));
                      return {scrollerDirection:getComputedStyle(scroller).direction, leftGap:g.left-s.left,rightGap:s.right-g.right,
                        codeDirection:getComputedStyle(code).direction, numberDirection:getComputedStyle(gutters.querySelector('.cm-lineNumbers .cm-gutterElement')).direction};
                    }""")
                    assert metrics["scrollerDirection"] == direction and metrics["numberDirection"] == "ltr", metrics
                    assert abs(metrics["rightGap" if direction == "rtl" else "leftGap"]) <= 2, metrics
                    assert metrics["codeDirection"] == "ltr", metrics
                    if text == PERSIAN:
                        prose_gap = page.locator(".cm-editor").evaluate("""editor=>{
                          const line=[...editor.querySelectorAll('.cm-line')].find(e=>e.textContent.startsWith('متن فارسی'));
                          const walker=document.createTreeWalker(line,NodeFilter.SHOW_TEXT),node=walker.nextNode();
                          const glyph=document.createRange();glyph.setStart(node,0);glyph.setEnd(node,1);
                          return editor.querySelector('.cm-gutters').getBoundingClientRect().left-glyph.getBoundingClientRect().right;
                        }""")
                        assert 0 <= prose_gap <= 44, prose_gap
                        case["rtl_text_gutter_gap"] = prose_gap
                        page.screenshot(path=str(output / f"{locale}-{theme}-{width}-source.png"))
                    page.locator(".cm-content").focus()
                    page.keyboard.press("Control+End")
                    page.keyboard.insert_text(" UNDO_CHECK")
                    expect(page.locator("#source")).to_have_value(text + " UNDO_CHECK")
                    page.keyboard.press("Control+z")
                    expect(page.locator("#source")).to_have_value(text)
                    case.setdefault("gutters", []).append(metrics)
                case["checks"].append("one document-level gutter follows metadata/prose rather than UI locale; numbers and fenced code stay LTR; physical editing and Undo preserve exact Markdown")

                page.evaluate("text=>{adapter.value=text;adapter.setMode('live');adapter.setSelectionRange(text.length)}", TABLE)
                expect(page.locator(".cm-editor")).not_to_have_attribute("data-source-direction", "rtl")
                expect(page.locator(".cm-md-table")).to_have_count(1)
                layout = page.evaluate("""() => {
                  const identifiers=[...document.querySelectorAll('#document table code,.cm-md-table code')].map(code=>{
                    const range=document.createRange();range.selectNodeContents(code);
                    const s=getComputedStyle(code), r=code.getBoundingClientRect();
                    return {text:code.textContent,rows:range.getClientRects().length,direction:s.direction,isolation:s.unicodeBidi,
                      whiteSpace:s.whiteSpace,wordBreak:s.wordBreak,wrap:s.overflowWrap,width:r.width};
                  });
                  return {identifiers,bodyOverflow:document.documentElement.scrollWidth>innerWidth+1,
                    readerScroll:document.querySelector('#document table').scrollWidth>document.querySelector('#document table').clientWidth,
                    writerScroll:document.querySelector('.cm-md-table').scrollWidth>document.querySelector('.cm-md-table').clientWidth};
                }""")
                for identifier in layout["identifiers"]:
                    assert identifier["rows"] == 1 and identifier["direction"] == "ltr" and identifier["isolation"] == "isolate", identifier
                    assert identifier["whiteSpace"] == "pre" and identifier["wordBreak"] == "normal" and identifier["wrap"] == "normal", identifier
                assert not layout["bodyOverflow"], layout
                if width <= 360:
                    assert layout["readerScroll"] and layout["writerScroll"], layout
                case["table_layout"] = layout
                case["checks"].append("Read and Write table identifiers remain atomic LTR isolates and overflow scrolls within the table, never the pane/page")
                expect(page.locator("#source")).to_have_value(TABLE)
                for offset in (2, 8, 15):
                    page.evaluate("text=>{adapter.value=text;adapter.setSelectionRange(text.length)}", INLINE)
                    code = page.locator(".cm-md-inline-code")
                    expect(code).to_be_visible()
                    point = code.evaluate("""(code,offset)=>{
                      const walker=document.createTreeWalker(code,NodeFilter.SHOW_TEXT),node=walker.nextNode();
                      const glyph=document.createRange();glyph.setStart(node,offset);glyph.setEnd(node,offset+1);
                      const rect=glyph.getBoundingClientRect();
                      return {x:rect.left+rect.width*.9,y:(rect.top+rect.bottom)/2};
                    }""", offset)
                    page.mouse.click(point["x"], point["y"])
                    assert page.evaluate("adapter.selectionStart") == INLINE.index("`") + offset + 2, (offset, page.evaluate("adapter.selectionStart"))
                    expect(page.locator("#source")).to_have_value(INLINE)
                case["checks"].append("LTR inline-code isolates in RTL prose share CodeMirror's bidi model; real clicks land on the exact source character while revealing Markdown")
                assert not errors, errors
                page.screenshot(path=str(output / f"{locale}-{theme}-{width}.png"))
                case["status"] = "passed"
            except Exception as error:
                case["status"] = "failed"
                case["error"] = (str(error) or traceback.format_exc(limit=2))[:2500]
                page.screenshot(path=str(output / f"{locale}-{theme}-{width}-failure.png"))
            finally:
                case["page_errors"] = errors
                page.close()
        browser.close()
    report["status"] = "passed" if all(case["status"] == "passed" for case in report["cases"]) else "failed"
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "apps/desktop/frontend")
    parser.add_argument("--output", type=Path, default=ROOT / "build/bidi-layout")
    args = parser.parse_args()
    result = run(args.dist.resolve(), args.output.resolve())
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(result["status"] != "passed")

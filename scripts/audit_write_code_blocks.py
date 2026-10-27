#!/usr/bin/env python3
"""Exercise Write code controls against actual CodeMirror, source bytes and Undo."""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ('# Code writing\n\n```javascript title="listing.js"\n'
          'const text = "فارسی";\nconsole.log(text);\n```\n\n'
          '## Empty block\n\n~~~\n~~~\n\n'
          '## Unclosed code\n\n```python\nprint("tail")')
BODY = 'const text = "فارسی";\nconsole.log(text);\n'
HTML = """<!doctype html><html lang="__LANG__" dir="__DIR__" data-theme="__THEME__"><head><meta charset="utf-8">
<link rel="stylesheet" href="/styles.css"><link rel="stylesheet" href="/workspace.css">
<link rel="stylesheet" href="/authoring.css"><link rel="stylesheet" href="/writer-workspace.css">
<link rel="stylesheet" href="/interaction-details.css"><link rel="stylesheet" href="/code-blocks.css"></head>
<body data-view="workspace"><div class="editor-pane" style="display:block;height:1000px;width:100%">
<textarea id="source"></textarea></div><script type="module">
import {createCodeMirrorEditorAdapter} from '/js/vendor/codemirror-editor.bundle.mjs';
window.adapter=createCodeMirrorEditorAdapter(document.querySelector('#source'),{mode:'live',theme:document.documentElement.dataset.theme});
</script></body></html>"""


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def run(dist: Path, output: Path, bundle: Path | None = None) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(dist)))
    Thread(target=server.serve_forever, daemon=True).start()
    report = {"status": "running", "cases": []}
    try:
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch()
            for locale, theme, width in [("en", "light", 1200), ("fa", "dark", 1200), ("en", "dark", 680), ("fa", "light", 360)]:
                case = {"locale": locale, "theme": theme, "width": width, "checks": []}
                report["cases"].append(case)
                page = browser.new_page(viewport={"width": width, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.add_init_script("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async value=>{globalThis.__copied=value}}})")
                html = HTML.replace("__LANG__", locale).replace("__DIR__", "rtl" if locale == "fa" else "ltr").replace("__THEME__", theme)
                page.route("**/code-block-fixture.html", lambda route: route.fulfill(body=html, content_type="text/html"))
                if bundle:
                    page.route("**/js/vendor/codemirror-editor.bundle.mjs", lambda route: route.fulfill(path=str(bundle), content_type="text/javascript"))
                try:
                    page.goto(f"http://127.0.0.1:{server.server_port}/code-block-fixture.html")
                    page.wait_for_function("Boolean(window.adapter)")
                    page.evaluate("text=>{adapter.value=text;adapter.setSelectionRange(0)}", SAMPLE)
                    headers = page.locator(".cm-code-header")
                    expect(headers).to_have_count(3)
                    expect(page.locator(".cm-code-close")).to_have_count(2)
                    expect(page.locator(".cm-code-unclosed-end")).to_have_count(1)
                    shape = headers.first.evaluate("e=>{const a=e.getBoundingClientRect(),r=e.closest('.cm-line'),s=getComputedStyle(r);return{left:a.left,right:a.right,radius:s.borderTopLeftRadius,border:s.borderTopWidth,indent:s.textIndent}}")
                    assert shape["left"] >= 0 and shape["right"] <= width + 1, shape
                    assert shape["radius"] == "10px" and shape["border"] == "1px" and shape["indent"] == "0px", shape
                    case["checks"].append("language/copy/edit header fits, code boundaries and unclosed final line remain correct")
                    headers.first.locator(".cm-code-copy").click()
                    assert page.evaluate("globalThis.__copied") == BODY
                    assert page.evaluate("adapter.value") == SAMPLE
                    case["checks"].append("Copy contains only exact code body, excludes language/fences, does not edit source")
                    headers.first.locator("select").select_option("python")
                    assert page.evaluate("adapter.value") == SAMPLE.replace("```javascript", "```python", 1)
                    page.keyboard.press("Control+z")
                    assert page.evaluate("adapter.value") == SAMPLE
                    case["checks"].append("language picker preserves attributes, body and delimiters; one Undo restores exact source")
                    headers.first.locator("button").first.click()
                    page.keyboard.insert_text("EDIT_")
                    assert page.evaluate("adapter.value") == SAMPLE.replace("const text", "EDIT_const text", 1)
                    expect(headers).to_have_count(3)
                    page.keyboard.press("Control+z")
                    assert page.evaluate("adapter.value") == SAMPLE
                    case["checks"].append("Edit code places a precise native caret, keeps header visible, typing and Undo preserve source")
                    headers.nth(1).locator("button").first.click()
                    assert page.evaluate("adapter.value") == SAMPLE.replace("~~~\n~~~", "~~~\n\n~~~", 1)
                    page.keyboard.press("Control+z")
                    assert page.evaluate("adapter.value") == SAMPLE
                    case["checks"].append("empty block gets an editable body row with one reversible source transaction")
                    page.evaluate("adapter.setReadOnly(true)")
                    expect(headers.first.locator("select")).to_be_disabled()
                    expect(headers.first.locator("button").first).to_be_disabled()
                    expect(headers.first.locator(".cm-code-copy")).to_be_enabled()
                    page.evaluate("adapter.setReadOnly(false);adapter.setMode('source')")
                    expect(headers).to_have_count(0)
                    assert page.evaluate("adapter.value") == SAMPLE
                    page.evaluate("adapter.setMode('live')")
                    expect(headers).to_have_count(3)
                    assert not errors, errors
                    case["checks"].append("read-only state disables editing and leaves copying; switching Source/Write preserves all bytes")

                    # Container marks belong to Markdown, not copied code.
                    # Editing an empty nested block must create a continuation
                    # row inside that same container, then place its caret
                    # after the prefix rather than before the quote/list.
                    nested = '> ```js\n> console.log(1);\n> ```\n\nAfter.'
                    page.evaluate("text=>{adapter.value=text;adapter.setSelectionRange(text.length)}", nested)
                    headers.first.locator(".cm-code-copy").click()
                    assert page.evaluate("globalThis.__copied") == 'console.log(1);\n'
                    headers.first.locator("button").first.click()
                    page.keyboard.insert_text("EDIT_")
                    assert page.evaluate("adapter.value") == nested.replace('> console.log', '> EDIT_console.log')
                    page.keyboard.press("Control+z")
                    assert page.evaluate("adapter.value") == nested
                    for nested, prefix in [
                        ('> ```\n> ```\n\nAfter.', '> '),
                        ('- ```\n  ```\n\nAfter.', '  '),
                        ('> - ```\n>   ```\n\nAfter.', '>   '),
                    ]:
                        page.evaluate("text=>{adapter.value=text;adapter.setSelectionRange(text.length)}", nested)
                        headers.first.locator("button").first.click()
                        first, rest = nested.split('\n', 1)
                        expected = first + '\n' + prefix + '\n' + rest
                        assert page.evaluate("adapter.value") == expected
                        page.keyboard.insert_text("BODY")
                        assert page.evaluate("adapter.value") == first + '\n' + prefix + 'BODY\n' + rest
                        expect(headers).to_have_count(1)
                        page.keyboard.press("Control+z")
                        page.keyboard.press("Control+z")
                        assert page.evaluate("adapter.value") == nested
                    case["checks"].append("nested quote/list Copy excludes container marks; empty Edit and its caret preserve structural prefixes with exact Undo")
                    page.evaluate("text=>{adapter.value=text;adapter.setSelectionRange(0)}", SAMPLE)
                    page.screenshot(path=str(output / f"{locale}-{theme}-{width}.png"))
                    case["status"] = "pass"
                except Exception as error:
                    case["status"] = "fail"
                    case["error"] = str(error)[:2000]
                    page.screenshot(path=str(output / f"{locale}-{theme}-{width}-failure.png"))
                finally:
                    page.close()
            browser.close()
        report["status"] = "pass" if all(case["status"] == "pass" for case in report["cases"]) else "fail"
        return report
    finally:
        server.shutdown()
        server.server_close()
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "apps/desktop/frontend")
    parser.add_argument("--output", type=Path, default=ROOT / "build/write-code-blocks")
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    result = run(args.dist.resolve(), args.output.resolve(), args.bundle.resolve() if args.bundle else None)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(result["status"] != "pass")

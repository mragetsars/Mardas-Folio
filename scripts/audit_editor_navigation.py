#!/usr/bin/env python3
"""Verify view-only editor scrolling with the real bundled CodeMirror adapter."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from audit_desktop_ui import ROOT, serve

FIXTURE = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="/styles.css"><link rel="stylesheet" href="/workspace.css">
<style>body{margin:0;padding:16px}.codemirror-mount{height:400px;width:640px;max-width:100%}</style>
</head><body data-view="workspace"><textarea id="editor"></textarea></body></html>"""
CONTENT = "\n".join(
    f"## Section {index}" if index % 10 == 1 else
    f"Paragraph {index}: text فارسی English and **formatted prose**. " * 5
    for index in range(1, 121)
)


def run(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    report = {"scenarios": [], "passed": False}
    with serve(ROOT / "apps/desktop/frontend") as url, sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        for locale, mode, zoom in (("en", "source", .6), ("en", "source", 2),
                                   ("fa", "live", 1), ("fa", "live", 2)):
            context = browser.new_context(viewport={"width": 800, "height": 600})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script("Object.freeze(Object.prototype)")
            page.route("**/__editor_navigation.html", lambda route: route.fulfill(body=FIXTURE, content_type="text/html"))
            page.goto(url + "/__editor_navigation.html", wait_until="networkidle")
            page.evaluate("""async ({content, locale, mode, zoom}) => {
              document.documentElement.lang = locale;
              document.documentElement.dir = locale === 'fa' ? 'rtl' : 'ltr';
              document.documentElement.style.setProperty('--document-text-scale', String(zoom));
              const {createCodeMirrorEditorAdapter} = await import('/js/vendor/codemirror-editor.bundle.mjs');
              globalThis.events = {changes:0,selections:0};
              globalThis.adapter = createCodeMirrorEditorAdapter(document.querySelector('#editor'), {
                locale, mode, onChange:()=>events.changes++, onSelectionChange:()=>events.selections++
              });
              adapter.setDocument('navigation-fixture',content);
            }""", {"content": CONTENT, "locale": locale, "mode": mode, "zoom": zoom})
            editor = page.locator(".cm-content")
            editor.click()
            page.keyboard.press("Control+Home")
            page.keyboard.type("edit ")
            page.evaluate("adapter.setSelectionRange(7, 15)")
            before = page.evaluate("""() => ({value:adapter.value,start:adapter.selectionStart,end:adapter.selectionEnd,
              focused:document.activeElement===adapter.element,events:{...events}})""")
            position = page.evaluate("adapter.scrollToLine(80)")
            page.wait_for_function("() => document.querySelector('.cm-scroller').scrollTop > 300")
            after = page.evaluate("""() => ({value:adapter.value,start:adapter.selectionStart,end:adapter.selectionEnd,
              focused:document.activeElement===adapter.element,events:{...events},
              visibleLine:adapter.firstVisibleLine(),scrollTop:adapter.scrollTop})""")
            assert position["line"] == 80
            for key in ("value", "start", "end", "focused", "events"):
                assert after[key] == before[key], f"View-only scrolling changed {key}"
            assert 76 <= after["visibleLine"] <= 80, after
            page.keyboard.press("Control+z")
            expect(page.locator("#editor")).to_have_value(CONTENT)
            resource = "# configuration comment\n- resource text\nvalue = true"
            page.evaluate("content => {adapter.setDocument('resource',content,{kind:'text'}); adapter.setMode('source');}", resource)
            expect(page.locator(".codemirror-mount")).to_have_attribute("data-document-kind", "text")
            assert page.locator(".cm-line").first.evaluate("node => [...node.querySelectorAll('*')].every(child => getComputedStyle(child).fontSize === getComputedStyle(node).fontSize)")
            assert page.evaluate("adapter.runCommand('bold')") is False
            page.evaluate("adapter.setSelectionRange(adapter.value.indexOf('\\nvalue'))")
            editor.focus()
            page.keyboard.press("Enter")
            expect(page.locator("#editor")).to_have_value(resource.replace("\nvalue", "\n\nvalue"))
            page.keyboard.press("Control+z")
            expect(page.locator("#editor")).to_have_value(resource)
            page.evaluate("content => {adapter.setDocument('navigation-fixture',content); adapter.setSelectionRange(0,5);}", CONTENT)
            assert page.evaluate("adapter.runCommand('bold')") is True
            expect(page.locator("#editor")).to_have_value("**" + CONTENT[:5] + "**" + CONTENT[5:])
            page.keyboard.press("Control+z")
            expect(page.locator("#editor")).to_have_value(CONTENT)
            assert not errors, errors
            report["scenarios"].append({"locale": locale, "mode": mode, "zoom": zoom,
                                         "visible_line": after["visibleLine"], "scroll_top": after["scrollTop"],
                                         "selection_preserved": True, "undo_preserved": True, "resource_language_and_commands": True, "page_errors": errors})
            context.close()
        browser.close()
    report["passed"] = True
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "build/editor-navigation-audit")
    arguments = parser.parse_args()
    result = run(arguments.output)
    print(f"Editor navigation audit passed: {len(result['scenarios'])} scenarios")

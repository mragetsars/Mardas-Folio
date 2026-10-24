#!/usr/bin/env python3
"""Exercise overlapping editor, file, export, image and clipboard operations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from audit_desktop_ui import DEFAULT_DIST, INIT_SCRIPT, serve


FIXTURE = r"""
localStorage.setItem('mardas.desktop.locale', 'en');
localStorage.setItem('mardas.desktop.preferences.v1', JSON.stringify({
  onboardingComplete:true, viewMode:'split', autoPreview:true
}));
const baseInvoke = globalThis.__TAURI__.core.invoke;
globalThis.__activeJob = false;
globalThis.__overlaps = [];
globalThis.__calls = [];
globalThis.__holdPreview = true;
globalThis.__scopeCalls = [];
globalThis.__granted = [];
globalThis.__copiedHtml = '';
Object.defineProperty(navigator, 'clipboard', {configurable:true, value:{
  write: async items => { globalThis.__copiedHtml = await (await items[0].getType('text/html')).text(); }
}});
globalThis.__TAURI__.core.convertFileSrc = path => {
  globalThis.__convertedImage = path;
  return 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=';
};
globalThis.__TAURI__.core.invoke = async (command, args = {}) => {
  if (command === 'pick_markdown_output') return '/fixtures/current.md';
  if (command === 'pick_markdown_files') return ['/fixtures/other.md'];
  if (command === 'allow_document_images') {
    globalThis.__scopeCalls.push(args);
    if (globalThis.__holdScope) await new Promise(resolve => { globalThis.__releaseScope = resolve; });
    globalThis.__granted = args.sources;
    return null;
  }
  if (command !== 'sidecar_request' || ['system.health','system.capabilities'].includes(args.method)) return baseInvoke(command,args);
  if (globalThis.__activeJob) {
    globalThis.__overlaps.push(args.method);
    throw JSON.stringify({message:'SERVER_BUSY'});
  }
  globalThis.__activeJob = true;
  globalThis.__calls.push(args.method);
  try {
    if (args.method.startsWith('preview.') && globalThis.__holdPreview) {
      await new Promise(resolve => { globalThis.__releasePreview = () => { globalThis.__holdPreview=false; resolve(); }; });
    }
    if (args.method === 'document.read') return {path:args.params.path, content:'# Other document\n\nOTHER_BUFFER', revision:'r1'};
    if (args.method === 'document.save') return {path:args.params.path, revision:'saved',read_only:false};
    if (args.method.startsWith('preview.')) {
      const safe = String(args.params.content || '').replaceAll('&','&amp;').replaceAll('<','&lt;');
      return {body_html:`<h1 id='current'>${safe}</h1>`, content_html:`<h1>${safe}</h1>`, diagnostics:[], css:{}, page:{}};
    }
    if (args.method === 'render.document') return {output_path:'/fixtures/current.pdf'};
    return {};
  } finally { globalThis.__activeJob = false; }
};
"""


def run_audit(dist: Path, output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    checks: list[str] = []
    with serve(dist) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.set_default_timeout(15_000)
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script(INIT_SCRIPT)
        page.add_init_script(FIXTURE)
        page.goto(url, wait_until="networkidle")
        page.locator('[data-template-id="blank"]').click()
        editor = page.locator(".cm-content")
        mirror = page.locator("#markdown-editor")
        page.wait_for_function("() => typeof globalThis.__releasePreview === 'function'")
        editor.click()
        page.keyboard.press("Control+a")
        page.keyboard.insert_text("# Current\n\nLATEST_BEFORE_SAVE")
        page.locator("#workspace-save").click()
        page.locator("#navigator-open").click()
        page.wait_for_timeout(100)
        assert page.evaluate("globalThis.__calls.filter(method => method === 'document.save').length") == 0
        page.evaluate("globalThis.__releasePreview()")
        expect(mirror).to_have_value("# Other document\n\nOTHER_BUFFER")
        page.wait_for_function("() => globalThis.__calls.includes('document.save')")
        assert not page.evaluate("globalThis.__overlaps")
        checks.append("save and open wait safely behind slow preview; latest document activates")

        page.locator("#workspace-export").click()
        expect(page.locator("#export-view")).to_be_visible()
        page.evaluate("globalThis.__holdPreview = true; globalThis.__releasePreview = null")
        # Schedule a new output preview through a real option change.
        page.locator("#option-search").fill("title")
        page.locator("#option-search").fill("")
        page.locator('[data-preset="technical"]').click()
        page.wait_for_function("() => typeof globalThis.__releasePreview === 'function'")
        page.locator("#export-form").evaluate("form => { form.requestSubmit(); form.requestSubmit(); }")
        expect(page.locator("#export-button")).to_be_disabled()
        expect(page.locator("#choose-output")).to_be_disabled()
        page.evaluate("globalThis.__releasePreview()")
        expect(page.locator("#export-button")).to_be_enabled()
        assert page.evaluate("globalThis.__calls.filter(method => method === 'render.document').length") == 1
        assert not page.evaluate("globalThis.__overlaps")
        checks.append("double export submission claims one job before draining preview")

        page.evaluate("globalThis.__holdPreview = true; globalThis.__releasePreview = null")
        page.locator('[data-preset="general"]').click()
        page.wait_for_function("() => typeof globalThis.__releasePreview === 'function'")
        page.locator("#export-form").evaluate("form => form.requestSubmit()")
        page.locator("#cancel-button").click()
        page.evaluate("globalThis.__releasePreview()")
        expect(page.locator("#export-button")).to_be_enabled()
        assert page.evaluate("globalThis.__calls.filter(method => method === 'render.document').length") == 1
        expect(page.locator("#status-message")).to_have_text("The operation was cancelled.")
        checks.append("cancel before preview drains prevents the export from starting")

        page.locator("#export-back").click()
        page.locator('button[data-view-mode="write"]').click()
        page.evaluate("globalThis.__holdScope = true; globalThis.__releaseScope = null")
        editor.click()
        page.keyboard.press("Control+a")
        image_text = '# Image\n\n![spaces](<assets/Persian chart.png>)\n\n![encoded](assets/chart%20two.png)\n\nAfter images.'
        page.keyboard.insert_text(image_text)
        page.keyboard.press("Control+End")
        page.wait_for_function("() => typeof globalThis.__releaseScope === 'function'")
        assert page.locator(".cm-md-image img").count() == 0
        page.evaluate("globalThis.__holdScope = false; globalThis.__releaseScope()")
        expect(page.locator(".cm-md-image img")).to_have_count(2)
        assert page.evaluate("globalThis.__granted") == ["assets/Persian chart.png", "assets/chart two.png"]
        page.wait_for_function("() => [...document.querySelectorAll('.cm-md-image img')].length === 2 && [...document.querySelectorAll('.cm-md-image img')].every(node => node.complete && node.naturalWidth > 0)")
        expect(mirror).to_have_value(image_text)
        checks.append("new image references wait for exact native grants and load without retry or document edits")

        # Manual preview can be disabled; Copy as HTML must still use the
        # current buffer and retain the selection when its menu is dismissed.
        page.locator('button[data-view-mode="split"]').click()
        page.locator("label:has(#auto-preview)").click()
        expect(page.locator("#auto-preview")).not_to_be_checked()
        editor.click()
        page.keyboard.press("Control+a")
        page.keyboard.insert_text("# FRESH_CLIPBOARD_CONTENT")
        editor.click(button="right")
        menu = page.locator("#editor-context-menu")
        expect(menu).to_be_visible()
        page.keyboard.press("End")
        page.keyboard.press("Home")
        assert page.evaluate("document.activeElement.closest('#editor-context-menu') !== null")
        page.keyboard.press("Escape")
        expect(menu).to_be_hidden()
        expect(editor).to_be_focused()
        editor.click(button="right")
        page.locator('[data-context-action="copyHtml"]').click()
        page.wait_for_function("() => globalThis.__copiedHtml.includes('FRESH_CLIPBOARD_CONTENT')")
        assert not page.evaluate("globalThis.__overlaps")
        checks.extend(["context menu arrow/Home/End/Escape navigation returns focus to editor",
                       "copy HTML renders current unsaved buffer with automatic preview disabled"])
        assert not errors, errors
        browser.close()
    report = {"status": "passed", "checks": checks}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--out", type=Path, default=Path("build/engine-queue-audit"))
    args = parser.parse_args()
    print(json.dumps(run_audit(args.dist, args.out), indent=2))

#!/usr/bin/env python3
"""Exercise overlapping editor, file, export, image and clipboard operations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from lib.audit.desktop import DEFAULT_DIST, INIT_SCRIPT, serve

FIXTURE = r"""
localStorage.setItem('mardas.desktop.locale', 'en');
localStorage.setItem('mardas.desktop.preferences.v1', JSON.stringify({
  onboardingComplete:true, viewMode:'split', autoPreview:true
}));
const baseInvoke = globalThis.__TAURI__.core.invoke;
globalThis.__activeJob = false;
globalThis.__overlaps = [];
globalThis.__calls = [];
globalThis.__requests = [];
globalThis.__holdPreview = true;
globalThis.__scopeCalls = [];
globalThis.__granted = [];
globalThis.__copiedHtml = '';
globalThis.__renderOutcome = null;
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
  globalThis.__requests.push({method:args.method, params:args.params});
  try {
    if (args.method.startsWith('preview.') && globalThis.__holdPreview) {
      await new Promise(resolve => { globalThis.__releasePreview = () => { globalThis.__holdPreview=false; resolve(); }; });
    }
    if (args.method === 'document.read') return {path:args.params.path, content:'# Other document\n\nOTHER_BUFFER', revision:'r1'};
    if (args.method === 'document.save') return {path:args.params.path, revision:'saved',read_only:false};
    if (args.method === 'publication.inspect_output') return {exists: Boolean(globalThis.__outputExists)};
    if (args.method.startsWith('preview.')) {
      const safe = String(args.params.content || '').replaceAll('&','&amp;').replaceAll('<','&lt;');
      return {body_html:`<h1 id='current'>${safe}</h1>`, content_html:`<h1>${safe}</h1>`, diagnostics:[], css:{}, page:{}};
    }
    if (args.method === 'render.document') {
      if (globalThis.__renderOutcome) {
        const outcome = await new Promise(resolve => { globalThis.__resolveRender = resolve; });
        if (outcome === 'cancelled') throw JSON.stringify({message:'Cancelled', data:{application_code:'MARDAS-JOB-CANCELLED'}});
      }
      return {output_path:'/fixtures/current.pdf'};
    }
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
        page.locator("#workspace-export").click()
        expect(page.locator("#export-format-modal")).to_be_visible()
        expect(page.locator("#export-format-pdf")).to_be_focused()
        expect(page.locator("#export-format-modal button:disabled")).to_have_count(2)
        page.keyboard.press("Escape")
        expect(page.locator("#export-format-modal")).to_be_hidden()
        expect(page.locator("#workspace-export")).to_be_focused()
        page.locator("#workspace-export").click()
        page.locator("#export-format-pdf").click()
        expect(page.locator("#export-view")).to_be_visible()
        expect(page.locator("#source-path")).to_have_value("")
        expect(page.locator("#choose-source")).to_be_focused()
        expect(page.locator("#export-button")).to_be_disabled()
        expect(page.locator("#export-source-required")).to_be_visible()
        preset = page.locator("#export-preset")
        expect(preset).to_have_value("general")
        preset.focus()
        page.keyboard.press("ArrowDown")
        expect(preset).to_have_value("academic")
        expect(preset).to_be_focused()
        expect(page.locator("#export-preset-help")).to_contain_text("Strict checks")
        page.locator("#export-back").click()
        expect(page.locator("#workspace-empty")).to_be_visible()
        checks.append("format choice and cancellation work in the workspace with no document")

        page.locator("#workflow-new").click()
        editor = page.locator(".cm-content")
        mirror = page.locator("#markdown-editor")
        editor.click()
        page.keyboard.press("Control+a")
        page.keyboard.insert_text("# Current\n\nLATEST_BEFORE_SAVE")
        page.wait_for_function("() => typeof globalThis.__releasePreview === 'function'")
        page.locator("#workspace-save").click()
        page.locator("#navigator-open").click()
        page.wait_for_timeout(100)
        assert (
            page.evaluate("globalThis.__calls.filter(method => method === 'document.save').length")
            == 0
        )
        page.evaluate("globalThis.__releasePreview()")
        expect(mirror).to_have_value("# Other document\n\nOTHER_BUFFER")
        page.wait_for_function("() => globalThis.__calls.includes('document.save')")
        assert not page.evaluate("globalThis.__overlaps")
        checks.append("save and open wait safely behind slow preview; latest document activates")

        page.locator("#workspace-export").click()
        page.locator("#export-format-pdf").click()
        expect(page.locator("#export-view")).to_be_visible()
        page.evaluate("globalThis.__outputExists = true")
        page.locator("#export-button").click()
        expect(page.locator("#export-feedback")).to_contain_text("already exists")
        expect(page.locator("#choose-output")).to_be_focused()
        assert not page.evaluate("globalThis.__calls.includes('render.document')")
        page.evaluate("globalThis.__outputExists = false")
        checks.append("existing output is reported before rendering and a new name is requested")
        preset.select_option("minimal")
        page.locator("#export-open-settings").click()
        page.locator("#reset-advanced").click()
        page.wait_for_function("""() => globalThis.__requests.some(r =>
          r.method.startsWith('preview.') && r.params.options?.palette === 'neutral')""")
        page.locator("#validate-button").click()
        expect(page.locator("#validate-button")).to_be_enabled()
        page.wait_for_function(
            "() => globalThis.__requests.some(r => r.method === 'validate.document')"
        )
        preview_options = page.evaluate("""() => globalThis.__requests.filter(r =>
          r.method.startsWith('preview.')).at(-1).params.options""")
        validation_options = page.evaluate("""() => globalThis.__requests.filter(r =>
          r.method === 'validate.document').at(-1).params.options""")
        assert preview_options == validation_options, (preview_options, validation_options)
        assert preview_options["toc"] is False
        checks.append(
            "reset keeps the selected preset identical in preview and document validation"
        )
        page.locator("#option-category").select_option("contents")
        toggle = page.locator('[data-option-key="toc"] .tri-toggle-option')
        expect(toggle).to_have_count(3)
        expect(toggle.nth(1)).to_have_attribute("aria-checked", "true")
        toggle.nth(1).focus()
        page.keyboard.press("ArrowLeft")
        expect(toggle.nth(0)).to_be_focused()
        expect(toggle.nth(0)).to_have_attribute("aria-checked", "true")
        expect(page.locator("#preset-summary")).to_contain_text("Inherit")
        page.wait_for_function("""() => globalThis.__requests.some(r =>
          r.method.startsWith('preview.') && !('toc' in r.params.options))""")
        page.locator("#validate-button").click()
        page.wait_for_function("""() => globalThis.__requests.some(r =>
          r.method === 'validate.document' && !('toc' in r.params.options))""")
        page.locator("#export-button").click()
        page.wait_for_function(
            "() => globalThis.__requests.some(r => r.method === 'render.document')"
        )
        render_options = page.evaluate("""() => globalThis.__requests.filter(r =>
          r.method === 'render.document').at(-1).params.options""")
        validation_options = page.evaluate("""() => globalThis.__requests.filter(r =>
          r.method === 'validate.document').at(-1).params.options""")
        assert render_options == validation_options and "toc" not in render_options
        assert (
            page.evaluate("""() => globalThis.__requests.filter(r =>
          r.method === 'render.document').at(-1).params.create_only""")
            is True
        )
        page.evaluate("globalThis.__calls = []")
        checks.append(
            "inherited preset option stays inherited for preview and validation with keyboard focus"
        )
        for outcome in ("cancelled", "completed"):
            page.evaluate("globalThis.__renderOutcome = true; globalThis.__resolveRender = null")
            page.locator("#export-button").click()
            page.wait_for_function("() => typeof globalThis.__resolveRender === 'function'")
            page.locator("#cancel-button").click()
            expect(page.locator("#cancel-button")).to_be_disabled()
            page.evaluate("(outcome) => globalThis.__resolveRender(outcome)", outcome)
            expect(page.locator("#export-button")).to_be_enabled()
            if outcome == "cancelled":
                expect(page.locator("#status-message")).to_have_text("The operation was cancelled.")
            else:
                expect(page.locator("#export-feedback")).to_contain_text("PDF created successfully")
                expect(page.locator("#open-pdf")).to_be_visible()
        page.evaluate("globalThis.__renderOutcome = null; globalThis.__calls = []")
        checks.append(
            "cancellation reports the actual job outcome, including completion after cancel"
        )
        page.evaluate("globalThis.__holdPreview = true; globalThis.__releasePreview = null")
        # Schedule a new output preview through a real option change.
        page.locator("#export-close-settings").click()
        preset.select_option("technical")
        page.wait_for_function("() => typeof globalThis.__releasePreview === 'function'")
        page.locator("#export-form").evaluate(
            "form => { form.requestSubmit(); form.requestSubmit(); }"
        )
        expect(page.locator("#export-button")).to_be_disabled()
        expect(page.locator("#choose-output")).to_be_disabled()
        page.evaluate("globalThis.__releasePreview()")
        expect(page.locator("#export-button")).to_be_enabled()
        assert (
            page.evaluate(
                "globalThis.__calls.filter(method => method === 'render.document').length"
            )
            == 1
        )
        assert not page.evaluate("globalThis.__overlaps")
        expect(page.locator("#export-feedback")).to_contain_text("PDF created successfully")
        expect(page.locator("#export-preview-state")).to_be_empty()
        expect(page.locator("#preview-zoom-in")).to_be_enabled()
        checks.append(
            "double submission claims one job and an interrupted preview refreshes afterwards"
        )

        page.evaluate("globalThis.__holdPreview = true; globalThis.__releasePreview = null")
        preset.select_option("general")
        expect(page.locator("#export-feedback")).to_have_attribute("data-state", "idle")
        expect(page.locator("#export-result")).to_be_hidden()
        page.wait_for_function("() => typeof globalThis.__releasePreview === 'function'")
        page.locator("#export-form").evaluate("form => form.requestSubmit()")
        page.locator("#cancel-button").click()
        page.evaluate("globalThis.__releasePreview()")
        expect(page.locator("#export-button")).to_be_enabled()
        assert (
            page.evaluate(
                "globalThis.__calls.filter(method => method === 'render.document').length"
            )
            == 1
        )
        expect(page.locator("#status-message")).to_have_text("The operation was cancelled.")
        checks.append("cancel before preview drains prevents the export from starting")

        page.locator("#export-back").click()
        page.locator('button[data-view-mode="write"]').click()
        page.evaluate("globalThis.__holdScope = true; globalThis.__releaseScope = null")
        editor.click()
        page.keyboard.press("Control+a")
        image_text = "# Image\n\n![spaces](<assets/Persian chart.png>)\n\n![encoded](assets/chart%20two.png)\n\nAfter images."
        page.keyboard.insert_text(image_text)
        page.keyboard.press("Control+End")
        page.wait_for_function("() => typeof globalThis.__releaseScope === 'function'")
        assert page.locator(".cm-md-image img").count() == 0
        page.evaluate("globalThis.__holdScope = false; globalThis.__releaseScope()")
        expect(page.locator(".cm-md-image img")).to_have_count(2)
        assert page.evaluate("globalThis.__granted") == [
            "assets/Persian chart.png",
            "assets/chart two.png",
        ]
        page.wait_for_function(
            "() => [...document.querySelectorAll('.cm-md-image img')].length === 2 && [...document.querySelectorAll('.cm-md-image img')].every(node => node.complete && node.naturalWidth > 0)"
        )
        expect(mirror).to_have_value(image_text)
        checks.append(
            "new image references wait for exact native grants and load without retry or document edits"
        )

        # Manual preview can be disabled; Copy as HTML must still use the
        # current buffer and retain the selection when its menu is dismissed.
        page.locator('button[data-view-mode="source"]').click()
        if page.locator("#workspace-toggle-preview").get_attribute("aria-pressed") != "true":
            page.locator("#workspace-layout-button").click()
            page.locator("#workspace-toggle-preview").click()
            page.keyboard.press("Escape")
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
        checks.extend(
            [
                "context menu arrow/Home/End/Escape navigation returns focus to editor",
                "copy HTML renders current unsaved buffer with automatic preview disabled",
            ]
        )
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

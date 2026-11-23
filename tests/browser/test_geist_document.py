from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from mardas_folio.application import EngineService

SOURCE = (
    "---\ntitle: Fixtures\n---\n\n"
    "# Example document\n\n"
    "- [ ] Check the figures\n\n"
    "| Name | Value |\n| --- | ---: |\n| فارسی | 1 |\n\n"
    '~~~{.python .numberLines title="main.py" linenostart=10 hl_lines="11"}\nreturn_value = "test"\nprint(42)\n~~~\n\n'
    "~~~diff\n+++ b/main.py\n-old\n+new\n~~~\n\n"
    "<details><summary>More information</summary><p>Additional text</p></details>\n"
)


@pytest.mark.parametrize("locale", ["en", "fa"])
def test_geist_document_controls(
    component_browser, frontend_url, tmp_path: Path, monkeypatch, locale
):
    monkeypatch.setenv("MARDAS_FOLIO_LIBRARY_DIR", str(tmp_path / "profile"))
    engine = EngineService()
    source = tmp_path / "report.md"
    source.write_text(SOURCE, encoding="utf-8")
    html_output = tmp_path / "report.html"
    markdown_output = tmp_path / "report-copy.md"
    json_source = tmp_path / "settings.json"
    json_source.write_text('{"nested": {"enabled": true}}', encoding="utf-8")
    errors = []
    selections = iter([[str(source)], [str(json_source)]])

    def native(command, args):
        if command == "sidecar_request":
            return engine.dispatch(args["method"], args.get("params", {}))
        if command == "take_launch_files":
            return []
        if command == "pick_library_files":
            return next(selections)
        if command == "pick_html_output":
            assert args["suggested_path"].endswith(".html")
            return str(html_output)
        if command == "pick_markdown_output":
            assert args["suggested_path"].endswith("-copy.md")
            return str(markdown_output)
        return None

    with component_browser.new_context(
        viewport={"width": 1440, "height": 900}, color_scheme="light"
    ) as context:
        page = context.new_page()
        page.set_default_timeout(7000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.expose_function("nativeInvoke", native)
        page.add_init_script(
            f"localStorage.setItem('mardas.desktop.locale', '{locale}');"
            """localStorage.setItem('mardas.desktop.preferences.v1',JSON.stringify({
              onboardingComplete:true, autoPreview:true, viewMode:'write'}));
            globalThis.__TAURI__={core:{invoke:(c,a={})=>nativeInvoke(c,a)},
            event:{listen:async()=>()=>{}}};
            Object.freeze(Object.prototype);
            Object.defineProperty(navigator, 'clipboard', {
              value: {writeText: async (value) => { window.copiedCode = value; }}
            });"""
        )
        page.goto(frontend_url)
        import_files = page.locator("#shelf-import")
        expect(import_files).to_have_css("background-color", "rgb(0, 0, 0)")
        expect(page.locator("#library-view")).to_have_css("background-color", "rgb(255, 255, 255)")
        expect(page.locator("[data-i18n=shelfHint]")).to_have_count(0)
        import_files.click()
        expect(page.locator("body")).to_have_attribute("data-view", "workspace")
        write = page.locator('[data-view-mode="write"].view-mode')
        source_mode = page.locator('[data-view-mode="source"].view-mode')
        expect(write).to_have_attribute("aria-checked", "true")
        write.press("ArrowRight")
        expect(source_mode).to_have_attribute("aria-checked", "true")
        write.click()
        expect(write).to_have_attribute("aria-checked", "true")

        editor = page.locator(".cm-editor[data-editor-mode='live']")
        expect(editor.locator(".cm-md-table th")).to_have_count(2)
        expect(editor.locator(".cm-md-table th").nth(1)).to_have_css("border-left-width", "1px")
        cell = editor.locator(".cm-md-table td").first
        expect(cell).to_have_css("direction", "rtl")
        cell.click()
        align = page.locator("[data-column-alignment=left]")
        align.click()
        expect(align).to_have_attribute("aria-pressed", "true")
        expect(cell).to_have_css("text-align", "left")
        expect(page.locator("#markdown-editor")).to_have_value(
            SOURCE.replace("| --- |", "| :--- |")
        )
        page.locator("[data-column-alignment=auto]").click()
        page.keyboard.press("Escape")
        code_line = editor.locator('[data-code-line="10"]')
        filename = editor.locator(".cm-code-filename")
        expect(filename).to_have_text("main.py")
        assert filename.evaluate("element => element.scrollWidth <= element.clientWidth")
        expect(code_line.locator("span", has_text='"test"')).to_have_css(
            "color", "rgb(21, 128, 61)"
        )
        expect(editor.locator(".cm-code-highlighted")).to_have_attribute("data-code-line", "11")
        expect(editor.locator(".cm-code-removed")).to_have_text("-old")
        expect(editor.locator(".cm-code-added")).to_have_text("+new")
        task = editor.locator(".cm-md-task")
        expect(task).to_have_css("width", "16px")
        task.click()
        mirror = page.locator("#markdown-editor")
        expect(mirror).to_have_value(re.compile(r"\[x\]", re.IGNORECASE))
        task.click()
        expect(mirror).to_have_value(SOURCE)
        copy = editor.locator(".cm-code-copy").first
        copy.click()
        expect(copy.locator("use")).to_have_attribute("href", "#icon-check")
        assert page.evaluate("window.copiedCode").strip() == 'return_value = "test"\nprint(42)'
        live_disclosure = editor.locator(".cm-document-disclosure details")
        expect(live_disclosure).to_have_js_property("open", False)
        live_disclosure.locator("summary").press("Enter")
        expect(live_disclosure.locator("p")).to_be_visible()
        live_disclosure.locator("summary").click()
        expect(live_disclosure.locator("p")).to_be_hidden()
        editor.locator(".cm-disclosure-edit").click()
        expect(live_disclosure).to_have_count(0)
        expect(mirror).to_have_value(SOURCE)
        metadata = editor.locator("button.cm-md-frontmatter")
        metadata.press("Enter")
        expect(metadata).to_have_count(0)
        editor.locator(".cm-line", has_text="Example document").click(button="right")
        context_menu = page.locator("#editor-context-menu")
        expect(context_menu).to_be_visible()
        expect(context_menu.locator('[data-context-action="copyHtml"] svg')).to_be_visible()
        page.keyboard.press("End")
        expect(context_menu.locator('[data-context-action="reveal"]')).to_be_focused()
        page.keyboard.press("Escape")
        expect(context_menu).to_be_hidden()

        page.locator("#workspace-layout-button").click()
        page.locator("#workspace-toggle-preview").click()
        preview = page.locator("#preview-document")
        disclosure = preview.locator("details")
        expect(disclosure).to_have_js_property("open", True)
        disclosure.locator("summary").press("Space")
        expect(disclosure).to_have_js_property("open", False)
        expect(preview.get_by_text("Additional text")).to_be_hidden()
        disclosure.locator("summary").click()
        expect(preview.get_by_text("Additional text")).to_be_visible()
        expect(preview.locator(".document-table-scroll table th")).to_have_count(2)
        expect(preview.locator(".document-table-scroll td").last).to_have_css("text-align", "right")
        page.locator("#workspace-layout-button").click()
        page.locator("#workspace-toggle-preview").click()

        trigger = page.locator("#workspace-export-formats")
        menu = page.locator("#workspace-export-menu")
        main_export = page.locator("#workspace-export")
        expect(main_export).to_have_text("خروجی" if locale == "fa" else "Export")
        expect(main_export).to_have_css("height", "32px")
        expect(trigger).to_have_css("height", "32px")
        expect(main_export).to_have_css("border-top-width", "1px")
        trigger.press("ArrowDown")
        expect(menu.locator('[data-export-format="pdf"]')).to_be_focused()
        page.keyboard.press("ArrowDown")
        expect(menu.locator('[data-export-format="html"]')).to_be_focused()
        page.keyboard.press("Escape")
        expect(trigger).to_be_focused()
        expect(menu).to_be_hidden()

        trigger.click()
        menu.locator('[data-export-format="html"]').click()
        toast = page.locator(".toast").filter(has_text="report.html")
        expect(toast).to_be_visible()
        assert "Example document" in html_output.read_text(encoding="utf-8")
        trigger.click()
        menu.locator('[data-export-format="markdown"]').click()
        expect(page.locator(".toast").filter(has_text="report-copy.md")).to_be_visible()
        assert markdown_output.read_text(encoding="utf-8") == SOURCE
        expect(page.locator("body")).to_have_attribute("data-view", "workspace")

        page.locator("#workspace-export").click()
        expect(page.locator("body")).to_have_attribute("data-view", "export")
        expect(page.locator("#source-path")).to_have_value(str(source))
        expect(page.locator("#export-format-modal")).to_be_hidden()
        page.locator("#export-back").click()

        page.locator("#settings-button").click()
        theme = page.locator("#setting-theme")
        expect(theme.locator('input[value="system"]')).to_be_checked()
        theme.locator('label:has(input[value="dark"])').click()
        page.locator("#settings-form button[type='submit']").click()
        expect(page.locator("html")).to_have_attribute("data-theme", "dark")
        page.locator("#settings-button").click()
        expect(theme.locator('input[value="dark"]')).to_be_checked()
        accent = page.locator("#setting-accent")
        expect(accent.locator('input[type="radio"]')).to_have_count(8)
        expect(accent.locator("input[value=gray]")).to_have_count(0)
        get_ends = """() => [...document.querySelectorAll('#setting-theme, #setting-accent')]
          .map(el => { const {left,right}=el.getBoundingClientRect();
             const row = el.closest('.settings-row').getBoundingClientRect();
             return document.dir === 'rtl' ? left-row.left : row.right-right; })"""
        assert page.evaluate(get_ends) == [0, 0]
        accent.locator("label:has(input[value=purple])").click()
        page.locator("#settings-form button[type='submit']").click()
        page.locator("#open-library").click()
        expect(page.locator("#library-view")).to_have_css("background-color", "rgb(0, 0, 0)")
        expect(import_files).to_have_css("background-color", "rgb(126, 58, 184)")
        page.locator("#settings-button").click()
        accent.locator("label:has(input[value=monochrome])").click()
        page.locator("#settings-form button[type='submit']").click()
        expect(import_files).to_have_css("background-color", "rgb(255, 255, 255)")
        import_files.click()
        json_document = page.locator("#json-document")
        json_document.locator("summary", has_text="nested").click()
        json_document.locator(".json-field", has_text="enabled").click()
        form = page.locator("dialog[open] form")
        expect(form.locator('input[value="true"]')).to_be_checked()
        form.locator('input[value="false"]').check()
        form.locator('button[type="submit"]').click()
        expect(json_document.locator(".json-field", has_text="enabled")).to_contain_text("false")
        assert not errors, errors

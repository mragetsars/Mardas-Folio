from __future__ import annotations

import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from mardas_folio.application import EngineService

CODE = 'return_value = "test"\nprint(42)\n# ' + "keep this line visible " * 20

SOURCE = (
    "---\ntitle: Fixtures\n---\n\n"
    "# Example document\n\n"
    "- [ ] Check the figures\n\n"
    "| Name | Value |\n| --- | ---: |\n| فارسی | 1 |\n| Two words | 2 |\n\n"
    '~~~{.python .numberLines title="main.py" linenostart=10 hl_lines="11"}\n'
    f"{CODE}\n~~~\n\n"
    "~~~diff\n+++ b/main.py\n-old\n+new\n~~~\n\n"
    "<details><summary>More information</summary><p>Additional text</p></details>\n\n"
    "~~~mermaid\nflowchart LR\n  A[First node] --> B[Last node]\n~~~\n\n"
    "## Other topic\n\nParagraph under other topic.\n\n"
    "### Nested topic\n\nNested content.\n"
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
        page.on(
            "console",
            lambda message: (
                errors.append(message.text)
                if message.text.startswith("CodeMirror plugin crashed")
                else None
            ),
        )
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
        fold = editor.locator(".cm-section-toggle").first
        expect(fold).to_have_attribute("aria-expanded", "true")
        fold.click()
        expect(fold).to_have_attribute("aria-expanded", "false")
        expect(editor.locator(".cm-md-table")).to_be_hidden()
        fold.click()
        expect(fold).to_have_attribute("aria-expanded", "true")
        expect(editor.locator(".cm-md-table th")).to_have_count(2)
        expect(editor.locator(".cm-md-table th").nth(1)).to_have_css("border-left-width", "1px")
        table = editor.locator(".cm-md-table")
        cell = table.locator("td").first
        panel = page.locator(".cm-table-cell-editor")
        draft = page.locator(".cm-table-cell-input")
        source_text = page.locator("#markdown-editor")
        left = panel.locator("[data-cell-alignment=left]")
        center = panel.locator("[data-cell-alignment=center]")
        expect(cell).to_have_css("direction", "rtl")
        expect(cell).to_have_css("text-align", "center")
        expect(table.locator(".cm-table-handle-active")).to_have_count(0)
        cell.click()
        expect(draft).to_be_focused()
        expect(draft).to_have_text("فارسی")
        expect(table.locator(".cm-table-handle-active")).to_have_count(2)
        draft.press("Control+b")
        expect(draft.locator("b, strong")).to_have_text("فارسی")
        draft.press("Enter")
        expect(source_text).to_have_value(SOURCE.replace("| فارسی", "| **فارسی**"))
        page.keyboard.press("Control+z")
        expect(source_text).to_have_value(SOURCE)
        cell.click()

        draft.press("End")
        page.keyboard.type(" test")
        expect(draft).to_have_text("فارسی test")
        expect(source_text).to_have_value(SOURCE)
        draft.press("Escape")
        expect(draft).to_have_count(0)
        cell.click()
        expect(panel.locator("[data-cell-format]")).to_have_count(0)
        expect(panel.locator(".cm-table-cell-structure")).to_be_hidden()
        left.click()
        expect(cell).to_have_css("text-align", "left")
        expect(source_text).to_have_value(
            SOURCE.replace("| فارسی", "| <!--folio-align:left--> فارسی")
        )
        expect(table.locator("td").nth(2)).to_have_css("text-align", "start")
        draft.press("Enter")
        page.keyboard.press("Control+z")
        expect(source_text).to_have_value(SOURCE)

        cell.click()
        table.locator("[data-table-select=row]").nth(1).click()
        expect(draft).to_be_hidden()
        expect(panel.locator(".cm-table-cell-structure button:visible")).to_have_count(5)
        expect(table.locator(".cm-table-cell-active")).to_have_count(2)
        left.click()
        expect(source_text).to_have_value(
            SOURCE.replace(
                "| فارسی | 1 |", "| <!--folio-align:left--> فارسی | <!--folio-align:left--> 1 |"
            )
        )
        page.keyboard.press("Control+z")
        expect(source_text).to_have_value(SOURCE)

        table.locator("td").nth(1).click()
        table.locator("[data-table-select=column]").nth(1).press("Enter")
        expect(draft).to_be_hidden()
        expect(panel.locator(".cm-table-cell-structure button:visible")).to_have_count(6)
        expect(table.locator(".cm-table-cell-active")).to_have_count(3)
        panel.locator("[data-cell-alignment=auto]").click()
        expect(table.locator("td").nth(1)).to_have_css("text-align", "center")
        expect(source_text).to_have_value(
            SOURCE.replace("| Value |", "| <!--folio-align:auto--> Value |")
            .replace("| 1 |", "| <!--folio-align:auto--> 1 |")
            .replace("| 2 |", "| <!--folio-align:auto--> 2 |")
        )
        page.keyboard.press("Control+z")
        expect(source_text).to_have_value(SOURCE)

        table.locator("th").first.click()
        table.locator("td").nth(2).click(modifiers=["Shift"])
        expect(table.locator(".cm-table-cell-active")).to_have_count(3)
        page.keyboard.press("Escape")
        table.locator("th").first.click()
        table.locator("td").last.click(modifiers=["Shift"])
        expect(table.locator(".cm-table-cell-active")).to_have_count(6)
        expect(panel.locator(".cm-table-cell-structure")).to_be_hidden()
        page.keyboard.press("Escape")
        table.locator("th").first.click()
        table.locator("td").last.click(modifiers=["Control"])
        expect(table.locator(".cm-table-cell-active")).to_have_count(2)
        center.click()
        expect(source_text).to_have_value(
            SOURCE.replace("| Name |", "| <!--folio-align:center--> Name |").replace(
                "| 2 |", "| <!--folio-align:center--> 2 |"
            )
        )
        page.keyboard.press("Control+z")
        expect(source_text).to_have_value(SOURCE)
        cell.click()
        table.locator("[data-table-select=row]").nth(1).click()
        panel.locator("[data-table-action=move-row-after]").click()
        expect(table.locator("tbody tr").first).to_contain_text("Two words")
        page.keyboard.press("Escape")
        page.keyboard.press("Control+z")
        expect(source_text).to_have_value(SOURCE)
        cell.click()
        table.locator("[data-table-select=column]").first.click()
        panel.locator("[data-table-action=move-column-after]").click()
        expect(table.locator("th").first).to_have_text("Value")
        page.keyboard.press("Escape")
        page.keyboard.press("Control+z")
        expect(source_text).to_have_value(SOURCE)
        resize = table.get_by_role("separator")
        resize.press("Shift+ArrowRight")
        expect(source_text).to_have_value(re.compile(r"<!--folio-width:\d+-->"))
        expect(table.locator("table")).to_have_class("cm-table-sized")
        page.keyboard.press("Control+z")
        expect(source_text).to_have_value(SOURCE)

        table.hover()
        add_column = table.locator('[data-table-extend="column"]')
        add_column.click()
        expect(table.locator("th")).to_have_count(3)
        page.keyboard.press("Control+z")
        expect(source_text).to_have_value(SOURCE)
        table.hover()
        add_row = table.locator('[data-table-extend="row"]')
        box = add_row.bounding_box()
        assert box
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x, y + 31, steps=5)
        page.mouse.up()
        expect(table.locator("tbody tr")).to_have_count(4)
        page.keyboard.press("Control+z")
        expect(source_text).to_have_value(SOURCE)

        table.locator(".cm-table-actions summary").click()
        table.locator(".cm-table-actions button").first.click()
        copied_table = page.evaluate("window.copiedCode")
        assert copied_table.startswith("| Name | Value |")
        assert copied_table.endswith("| Two words | 2 |")
        table.locator(".cm-table-actions button").last.click()
        expect(table).to_have_count(0)
        page.keyboard.press("Control+z")
        expect(source_text).to_have_value(SOURCE)

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
        wrap = editor.locator(".code-wrap-button").first
        expect(wrap).to_have_attribute("aria-pressed", "true")
        wrap.click()
        expect(wrap).to_have_attribute("aria-pressed", "false")
        expect(code_line).to_have_css("white-space", "pre")
        long_line = editor.locator(".cm-code-nowrap", has_text="keep this line visible")
        assert long_line.evaluate("element => element.scrollWidth > element.clientWidth")
        assert (
            long_line.evaluate("element => { element.scrollLeft = 64; return element.scrollLeft; }")
            > 0
        )
        expect(source_text).to_have_value(SOURCE)
        wrap.click()
        expect(code_line).to_have_css("white-space", "pre-wrap")
        copy = editor.locator(".cm-code-copy").first
        copy.click()
        expect(copy.locator("use")).to_have_attribute("href", "#icon-check")
        assert page.evaluate("window.copiedCode").rstrip("\n") == CODE
        live_disclosure = editor.locator(".cm-document-disclosure details")
        expect(live_disclosure).to_have_js_property("open", False)
        live_disclosure.locator("summary").press("Enter")
        expect(live_disclosure.locator("p")).to_be_visible()
        live_disclosure.locator("summary").click()
        expect(live_disclosure.locator("p")).to_be_hidden()
        editor.locator(".cm-disclosure-edit").click()
        expect(editor.locator(".cm-document-disclosure .cm-visual-fields")).to_be_visible()
        expect(mirror).to_have_value(SOURCE)
        metadata = editor.locator("button.cm-md-frontmatter")
        metadata.press("Enter")
        expect(editor.locator(".cm-md-frontmatter-block .cm-visual-fields")).to_be_visible()
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
        preview_code = preview.locator(".code-block").first
        preview_code.locator(".code-wrap-button").click()
        expect(preview_code.locator("td.code pre")).to_have_css("white-space", "pre-wrap")
        expect(preview.locator(".document-table-scroll table th")).to_have_count(2)
        expect(preview.locator(".document-table-scroll td").last).to_have_css("text-align", "right")
        page.locator("#workspace-layout-button").click()
        page.locator("#workspace-toggle-preview").click()

        diagram = editor.locator(".cm-diagram")
        expect(diagram.locator(".md2pdf-mermaid-svg")).to_be_visible()
        assert (
            diagram.locator(".md2pdf-mermaid-bg").evaluate("el => getComputedStyle(el).fill")
            != "rgb(0, 0, 0)"
        )
        diagram.locator("summary").click()
        diagram.locator("input").first.fill("Updated node")
        diagram.locator(".cm-diagram-apply").click()
        expect(diagram.locator("svg")).to_contain_text("Updated node")
        expect(mirror).to_have_value(re.compile(r"Updated node"))
        editor.locator(".cm-content").focus()
        page.keyboard.press("Control+z")
        expect(mirror).to_have_value(SOURCE)

        paragraph = editor.locator(".cm-line", has_text="Paragraph under other topic.")
        nested = editor.locator(".cm-line", has_text="Nested topic")
        paragraph.hover()
        grip = editor.locator(".cm-block-grip")
        expect(grip).to_be_visible()
        box = grip.bounding_box()
        target = nested.bounding_box()
        assert box and target
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(
            target["x"] + target["width"] / 2, target["y"] + target["height"] * 0.8, steps=10
        )
        page.mouse.up()
        expect(mirror).to_have_value(
            SOURCE.replace("Paragraph under other topic.\n\n", "").rstrip()
            + "\n\nParagraph under other topic.\n"
        )
        page.keyboard.press("Control+z")
        expect(mirror).to_have_value(SOURCE)

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

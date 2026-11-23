#!/usr/bin/env python3
"""Exercise table drafts through real workspace tabs, shortcuts and Undo."""

from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path

from audit_table_editing import SAMPLE
from playwright.sync_api import expect, sync_playwright

from lib.audit.desktop import DEFAULT_DIST, click_workspace_layout_control, serve
from lib.audit.editor import CONTENT_A, FIXTURE_B, initialise, replace_content


def run(dist: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "running", "scenarios": []}
    with serve(dist) as url, sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        for locale, theme in (("en", "dark"), ("fa", "light")):
            case = {"locale": locale, "theme": theme, "checks": []}
            report["scenarios"].append(case)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.set_default_timeout(10000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                initialise(page, url, locale, theme, source=False)
                page.locator('[data-area="workspace"]').click()
                page.keyboard.press("Control+o")
                expect(page.locator("#document-tabs .document-tab")).to_have_count(2)
                replace_content(page, SAMPLE)
                page.keyboard.press("Control+End")
                buffer = page.locator("#markdown-editor")
                cell = page.locator(
                    '.cm-md-table [data-table-row="1"][data-table-column="1"]'
                ).first
                panel = page.locator(".cm-table-cell-editor")
                draft = page.locator(".cm-table-cell-input")

                if (
                    page.locator("#workspace-toggle-formatting").get_attribute("aria-pressed")
                    != "true"
                ):
                    click_workspace_layout_control(page, "#workspace-toggle-formatting")
                cell.click()
                draft.fill("CELL_FORMAT_ONLY")
                draft.press("Control+a")
                for selector in (
                    '[data-editor-command="strike"]',
                    '[data-editor-command="link"]',
                    "#heading-menu-button",
                    "#insert-menu-button",
                    "#workspace-import-asset",
                ):
                    expect(page.locator(selector).first).to_be_disabled()
                    page.locator(selector).first.evaluate("e=>e.click()")
                expect(panel).to_be_visible()
                expect(buffer).to_have_value(SAMPLE)
                expect(draft).to_have_value("CELL_FORMAT_ONLY")
                bold = page.locator('#format-bar [data-editor-command="bold"]')
                expect(bold).to_be_enabled()
                bold.click()
                expect(draft).to_have_value("**CELL_FORMAT_ONLY**")
                expect(buffer).to_have_value(SAMPLE)
                # The host refreshes button state after preview/save events.
                page.locator('[data-editor-command="strike"]').first.evaluate("e=>e.disabled=false")
                expect(page.locator('[data-editor-command="strike"]').first).to_be_disabled()
                draft.press("Escape")
                expect(page.locator('[data-editor-command="strike"]').first).to_be_enabled()
                expect(page.locator("#heading-menu-button")).to_be_enabled()
                expect(page.locator("#insert-menu-button")).to_be_enabled()
                case["checks"].append(
                    "unsupported document formatting and insertion are disabled during a cell draft; Bold targets only the cell, refresh preserves the guard, and close restores controls"
                )

                cell.click()
                draft.press("Alt+F10")
                expect(panel.locator('[data-cell-format="bold"]')).to_be_focused()
                focus_paint = panel.locator('[data-cell-format="bold"]').evaluate("""e=>{
                    const style=getComputedStyle(e);
                    return {visible:e.matches(':focus-visible'), width:style.outlineWidth,
                      color:style.outlineColor, style:style.outlineStyle};
                }""")
                case["cell_action_focus"] = focus_paint
                assert (
                    float(focus_paint["width"].removesuffix("px")) >= 2
                    and focus_paint["style"] == "solid"
                ), focus_paint
                page.keyboard.press("Escape")
                expect(draft).to_be_focused()
                draft.press("Escape")
                grid = page.locator(".cm-md-table").first
                grid.locator('[data-table-select="column"]').nth(1).click()
                page.keyboard.press("Home")
                for _ in range(5):
                    page.keyboard.press("ArrowDown")
                add_column = panel.get_by_role(
                    "button",
                    name="Add column after" if locale == "en" else "افزودن ستون بعدی",
                    exact=True,
                )
                expect(add_column).to_be_focused()
                page.keyboard.press("Enter")
                expect(grid.locator("th")).to_have_count(4)
                grid.locator('[data-table-row="1"][data-table-column="2"]').click()
                expect(draft).to_be_focused()
                draft.fill("KEYBOARD_NEW_COLUMN")
                draft.press("Alt+F10")
                page.keyboard.press("End")
                expect(panel.locator(".cm-table-cell-apply")).to_be_focused()
                page.keyboard.press("Enter")
                expect(panel).to_have_count(0)
                assert "KEYBOARD_NEW_COLUMN" in buffer.input_value()
                page.keyboard.press("Control+z")
                page.keyboard.press("Control+z")
                expect(buffer).to_have_value(SAMPLE)
                case["checks"].append(
                    "Alt+F10, Escape, arrows, Home/End and Enter navigate the cell and column actions; two physical Undo steps restore the exact original table"
                )

                cell.click()
                draft.fill("TAB_SWITCH_DRAFT")
                page.locator("#document-tabs .document-tab").nth(0).locator(".tab-activate").click()
                expect(buffer).to_have_value(CONTENT_A)
                expect(panel).to_have_count(0)
                page.locator("#document-tabs .document-tab").nth(1).locator(".tab-activate").click()
                expect(buffer).to_have_value(
                    SAMPLE.replace("**bold** and *italic*", "TAB_SWITCH_DRAFT")
                )
                page.keyboard.press("Control+z")
                expect(buffer).to_have_value(SAMPLE)
                case["checks"].append(
                    "one tab click commits its cell draft and activates the requested document; return retains draft and exact Undo"
                )

                cell.click()
                draft.fill("START_TAB_DRAFT")
                page.locator("#tab-new-document").click()
                expect(page.locator("body")).to_have_attribute("data-view", "library")
                page.locator('[data-area="workspace"]').click()
                expect(buffer).to_have_value(
                    SAMPLE.replace("**bold** and *italic*", "START_TAB_DRAFT")
                )
                page.locator(".cm-content").focus()
                page.keyboard.press("Control+z")
                expect(buffer).to_have_value(SAMPLE)
                cell.click()
                draft.fill("BLOCKED_CELL_DRAFT")
                panel.locator(".cm-table-cell-apply").evaluate("button => button.disabled = true")
                page.locator("#tab-new-document").click()
                expect(panel).to_be_visible()
                expect(draft).to_have_value("BLOCKED_CELL_DRAFT")
                expect(page.locator("body")).to_have_attribute("data-view", "workspace")
                panel.locator(".cm-table-cell-apply").evaluate("button => button.disabled = false")
                draft.press("Escape")
                expect(buffer).to_have_value(SAMPLE)
                case["checks"].append(
                    "opening the document-type chooser commits the draft and stays in the editor when a draft cannot be committed"
                )

                cell.click()
                draft.fill("ENTER_UNDO")
                draft.press("Enter")
                expect(panel).to_have_count(0)
                page.keyboard.press("Control+z")
                expect(buffer).to_have_value(SAMPLE)
                cell.click()
                draft.fill("APPLY_UNDO")
                panel.get_by_role(
                    "button", name="Apply" if locale == "en" else "اعمال", exact=True
                ).click()
                page.keyboard.press("Control+z")
                expect(buffer).to_have_value(SAMPLE)
                case["checks"].append(
                    "physical Ctrl+Z works immediately after Enter and Apply, without adapter command shortcuts"
                )

                cell.click()
                draft.fill("LOCAL_NAVIGATION_ONLY")
                draft.press("Control+ArrowLeft")
                expect(buffer).to_have_value(SAMPLE)
                expect(panel).to_be_visible()
                draft.press("Escape")
                page.wait_for_timeout(80)
                expect(page.locator(".cm-table-cell-active")).to_have_count(0)
                case["checks"].append(
                    "Ctrl+Arrow word navigation does not commit drafts; Escape leaves no stale active-cell decoration"
                )

                cell.click()
                draft.fill("PHYSICAL_LAYOUT")
                draft.press("Control+a")
                draft.evaluate(
                    "e=>e.dispatchEvent(new KeyboardEvent('keydown',{key:'ذ',code:'KeyB',keyCode:66,ctrlKey:true,bubbles:true,cancelable:true}))"
                )
                expect(draft).to_have_value("**PHYSICAL_LAYOUT**")
                expect(buffer).to_have_value(SAMPLE)
                draft.press("Enter")
                expect(buffer).to_have_value(
                    SAMPLE.replace("**bold** and *italic*", "**PHYSICAL_LAYOUT**")
                )
                page.keyboard.press("Control+z")
                expect(buffer).to_have_value(SAMPLE)
                case["checks"].append(
                    "Persian-layout physical Ctrl+B formats only the cell draft; Enter applies once and physical Undo restores Markdown"
                )

                cell.click()
                draft.fill("SAVED_FROM_CELL")
                draft.press("Control+s")
                expected = SAMPLE.replace("**bold** and *italic*", "SAVED_FROM_CELL")
                expect(buffer).to_have_value(expected)
                expect(panel).to_have_count(0)
                page.wait_for_function(
                    "v=>globalThis.__auditFiles[v.path]===v.text",
                    arg={"path": FIXTURE_B, "text": expected},
                )
                case["checks"].append(
                    "Ctrl+S from cell input commits and actually saves the document through the workspace bridge"
                )

                cell.click()
                draft.fill("FIND_FROM_CELL")
                draft.press("Control+f")
                expect(panel).to_have_count(0)
                expect(page.locator("#find-query")).to_be_focused()
                expect(buffer).to_have_value(
                    SAMPLE.replace("**bold** and *italic*", "FIND_FROM_CELL")
                )
                page.keyboard.press("Escape")
                page.keyboard.press("Control+z")
                expect(buffer).to_have_value(expected)
                case["checks"].append(
                    "Ctrl+F commits the draft before opening Find; one Undo restores the prior saved cell"
                )

                cell.click()
                draft.fill("SOURCE_FROM_CELL")
                page.locator('[data-view-mode="source"][role="radio"]').click()
                expect(panel).to_have_count(0)
                expect(page.locator(".editor-pane")).to_have_attribute("data-view-mode", "source")
                expect(buffer).to_have_value(
                    SAMPLE.replace("**bold** and *italic*", "SOURCE_FROM_CELL")
                )
                page.locator(".cm-content").focus()
                page.keyboard.press("Control+z")
                expect(buffer).to_have_value(expected)
                case["checks"].append(
                    "one Source click applies its cell draft before changing mode; physical Undo restores saved cell"
                )

                page.locator('[data-view-mode="write"][role="radio"]').click()
                cell.click()
                draft.fill("WINDOW_CLOSE_RECOVERY")
                page.evaluate("window.dispatchEvent(new Event('beforeunload'))")
                recovered = SAMPLE.replace("**bold** and *italic*", "WINDOW_CLOSE_RECOVERY")
                expect(buffer).to_have_value(recovered)
                entries = page.evaluate(
                    "JSON.parse(localStorage.getItem('mardas.desktop.authoring-recovery.v1') || '[]')"
                )
                assert any(
                    entry["path"] == FIXTURE_B and entry["content"] == recovered
                    for entry in entries
                ), entries
                draft.press("Escape")
                case["checks"].append(
                    "window-close capture commits the cell before the host snapshots exact Markdown recovery"
                )

                assert not errors, errors
                page.screenshot(path=str(output / f"{locale}-{theme}.png"))
                case["status"] = "passed"
            except Exception as error:
                case["status"] = "failed"
                case["error"] = (str(error) or traceback.format_exc(limit=2))[:2200]
                page.screenshot(path=str(output / f"{locale}-{theme}-failure.png"))
            finally:
                case["page_errors"] = errors
                page.close()
        browser.close()
    report["status"] = (
        "passed" if all(case["status"] == "passed" for case in report["scenarios"]) else "failed"
    )
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--output", type=Path, default=Path("build/table-workspace"))
    args = parser.parse_args()
    result = run(args.dist, args.output)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(result["status"] != "passed")

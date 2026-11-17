#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from lib.audit.desktop import (
    INIT_SCRIPT as INIT_SCRIPT,
)
from lib.audit.desktop import (
    QuietHandler as QuietHandler,
)
from lib.audit.desktop import (
    _visible as _visible,
)
from lib.audit.desktop import (
    click_workspace_layout_control as click_workspace_layout_control,
)
from lib.audit.desktop import (
    open_settings as open_settings,
)
from lib.audit.desktop import (
    open_template as open_template,
)
from lib.audit.desktop import (
    open_workspace_export as open_workspace_export,
)
from lib.audit.desktop import (
    run_workspace_command as run_workspace_command,
)
from lib.audit.desktop import (
    select_settings_section as select_settings_section,
)
from lib.audit.desktop import (
    serve as serve,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIST = ROOT / "apps" / "desktop" / "dist"
DEFAULT_OUTPUT = ROOT / "build" / "desktop-ui-audit"


def run_audit(
    dist: Path,
    output_dir: Path,
    *,
    executable_path: str | None = None,
    timeout_ms: int = 30_000,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    checks: dict[str, object] = {}
    page_errors: list[str] = []
    console_issues: list[str] = []
    with serve(dist) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=executable_path,
        )
        context = browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.set_default_timeout(timeout_ms)
        page.add_init_script(INIT_SCRIPT)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: (
                console_issues.append(f"{message.type}: {message.text}")
                if message.type in {"error", "warning"}
                else None
            ),
        )
        page.goto(url, wait_until="networkidle")

        checks["workspace_starts_without_modal"] = _visible(
            page, "#workspace-empty"
        ) and not _visible(page, "#onboarding-modal")
        open_settings(page, "language")
        page.locator("#restart-onboarding").click()
        checks["onboarding_visible"] = _visible(page, "#onboarding-modal")
        checks["background_inert"] = page.locator(".shell").evaluate("(node) => node.inert")
        checks["onboarding_focus"] = page.evaluate(
            "document.activeElement?.getAttribute('data-onboarding-action')"
        )
        page.locator("#skip-onboarding").click()
        checks["onboarding_closed"] = not _visible(page, "#onboarding-modal")
        checks["background_restored"] = not page.locator(".shell").evaluate("(node) => node.inert")

        open_template(page, "report")
        checks["workspace_active"] = page.locator("#workspace-view").evaluate(
            "(node) => node.classList.contains('active')"
        )
        page.locator(".codemirror-mount .cm-editor").wait_for(state="visible")
        checks["professional_editor"] = (
            page.locator(".editor-surface").get_attribute("data-editor") == "codemirror"
        )
        checks["editor_line_numbers"] = (
            page.locator(".cm-lineNumbers .cm-gutterElement").count() > 0
        )
        editor = page.locator("#markdown-editor")
        checks["template_content"] = "# Executive Summary" in editor.input_value()
        # Write mode opens on the document. The caret used to start at offset
        # 0, which is inside the front matter, and live preview reveals the
        # block the caret is in — so the first thing a new document showed was
        # its YAML rather than its title.
        checks["front_matter_collapsed_on_open"] = page.evaluate(
            """() => {
                const active = document.querySelector('.cm-activeLine');
                return !!document.querySelector('.cm-md-frontmatter')
                    && !!active && active.textContent.trim().startsWith('#');
            }"""
        )
        page.locator(".codemirror-mount .cm-content").click()
        page.keyboard.press("Control+End")
        page.keyboard.insert_text("\n\nمتن فارسی and English")
        checks["professional_editor_input"] = "متن فارسی and English" in editor.input_value()
        # Everything that truncates has to carry the whole value somewhere.
        # These three are the ones that hold a file name and a path, in a
        # status bar and a tab strip narrower than either.
        checks["truncated_labels_carry_the_full_value"] = page.evaluate(
            """() => ['#editor-title', '#editor-path', '.document-tab .tab-name']
                .every((selector) => {
                  const el = document.querySelector(selector);
                  return !!el && el.title.trim() === el.textContent.trim() && el.title !== '';
                })"""
        )

        # Five constructs the engine publishes — footnotes, inline and display
        # maths, a Mermaid diagram, a highlight — had no way in from the
        # interface at all. They are behind one pinned menu, and the same
        # commands answer to the palette by name.
        page.locator("#insert-menu-button").click()
        page.wait_for_timeout(300)
        checks["insert_menu_opens"] = page.evaluate(
            """() => {
                const menu = document.querySelector('#insert-menu');
                return !!menu && !menu.classList.contains('hidden')
                    && menu.querySelectorAll('button').length >= 6;
            }"""
        )
        before_footnote = editor.input_value()
        page.locator('#insert-menu [data-editor-command="footnote"]').click()
        page.wait_for_timeout(400)
        after_footnote = editor.input_value()
        checks["footnote_inserts_reference_and_definition"] = (
            "[^1]" in after_footnote
            and "[^1]: " in after_footnote
            and after_footnote != before_footnote
        )

        # Tab indents inside the editor, which makes it a keyboard trap unless
        # something releases it. Escape arms the next Tab to move focus; the
        # press after that has to land somewhere that is not the editor.
        before = editor.input_value()
        page.keyboard.press("Home")
        page.keyboard.press("Tab")
        page.wait_for_timeout(150)
        indented = editor.input_value()
        checks["tab_indents_in_editor"] = indented != before
        page.keyboard.press("Escape")
        page.keyboard.press("Tab")
        page.wait_for_timeout(200)
        checks["escape_then_tab_leaves_editor"] = page.evaluate(
            "() => !document.activeElement?.closest?.('.cm-editor')"
        )
        # And lands on a control this workbench chose, rather than on the page
        # the webview drops focus onto when it answers the Escape itself.
        checks["escape_then_tab_lands_on_a_control"] = page.evaluate(
            """() => {
                const el = document.activeElement;
                return !!el && el !== document.body
                    && !!el.closest('.shell')
                    && (el.matches('a, button, input, select, textarea')
                        || el.tabIndex >= 0);
            }"""
        )
        checks["escape_then_tab_keeps_the_buffer"] = editor.input_value() == indented

        # The case the browser's own release does not cover: with a selection
        # live, CodeMirror claims the Escape, the webview never arms, and the
        # Tab after it indented the document and stayed put.
        page.locator(".cm-content").click()
        page.keyboard.press("End")
        page.keyboard.press("Shift+Home")
        page.wait_for_timeout(120)
        selected = editor.input_value()
        page.keyboard.press("Escape")
        page.keyboard.press("Tab")
        page.wait_for_timeout(250)
        checks["escape_then_tab_leaves_a_selection_alone"] = (
            page.evaluate("() => !document.activeElement?.closest?.('.cm-editor')")
            and editor.input_value() == selected
        )

        # Editing activity and the side pane are independent controls.
        page.locator('[data-view-mode="source"][role="radio"]').click()
        if page.locator("#workspace-toggle-preview").get_attribute("aria-pressed") != "true":
            click_workspace_layout_control(page, "#workspace-toggle-preview")
        page.locator("#preview-preview-heading").wait_for(state="visible")
        checks["split_view_shows_preview"] = page.locator("#preview-pane").is_visible()
        checks["preview_contract"] = (
            page.locator("#preview-preview-heading").inner_text() == "Preview"
        )
        # The compact pane header names its document scope; its accessible
        # description explains that print pagination belongs to export.
        checks["preview_says_what_it_shows"] = page.evaluate(
            """() => {
                const header = document.querySelector('.preview-pane .pane-header');
                const title = header?.querySelector('strong');
                return !!title && title.offsetParent !== null
                    && title.textContent.trim().length > 0
                    && !!header?.title && header.title.includes('PDF');
            }"""
        )
        checks["preview_sanitized"] = page.evaluate(
            """() => {
              const preview = document.querySelector('#preview-document');
              const image = preview?.querySelector('img');
              return !globalThis.__previewXss
                && !preview?.querySelector('style,form,button:not(.document-source-jump)')
                && !!image && !image.hasAttribute('src')
                && !preview?.querySelector('[srcset],[onerror],[style]');
            }"""
        )
        active_tab = page.locator(".document-tab .tab-activate[aria-selected='true']")
        # Closing a document with unsaved work asks in this application's own
        # dialog, focused on the safe answer, rather than in the platform's.
        page.locator(".document-tab .tab-close").first.click()
        page.wait_for_timeout(400)
        checks["own_confirm_dialog"] = page.evaluate(
            """() => {
                const modal = document.querySelector('#confirm-modal');
                return !!modal && !modal.classList.contains('hidden')
                    && document.activeElement?.id === 'confirm-cancel'
                    && document.querySelector('#confirm-accept')?.classList.contains('danger');
            }"""
        )
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        checks["cancelling_keeps_the_document"] = page.locator(".document-tab").count() > 0

        checks["accessible_document_tab"] = (
            active_tab.count() == 1 and active_tab.get_attribute("tabindex") == "0"
        )

        open_settings(page)
        checks["settings_visible"] = _visible(page, "#settings-modal")
        tab_count = page.locator(".document-tab").count()
        page.keyboard.press("Control+N")
        checks["modal_shortcuts_blocked"] = page.locator(".document-tab").count() == tab_count
        page.locator("#setting-theme").select_option("dark")
        select_settings_section(page, "accessibility")
        page.locator("#setting-motion").select_option("reduce")
        page.locator("#settings-form button[type='submit']").click()
        checks["dark_theme"] = page.locator("html").get_attribute("data-theme") == "dark"
        checks["reduced_motion"] = (
            page.locator("html").get_attribute("data-reduced-motion") == "reduce"
        )

        page.keyboard.press("Control+Shift+P")
        checks["command_palette_visible"] = _visible(page, "#command-modal")
        page.locator("#command-query").fill("help")
        page.keyboard.press("Enter")
        checks["help_visible"] = _visible(page, "#help-modal")
        page.locator("#help-done").click()

        open_settings(page, "language")
        page.locator("#setting-locale").select_option("fa")
        page.locator("#settings-form button[type='submit']").click()
        checks["rtl_locale"] = page.locator("html").get_attribute("dir") == "rtl"
        click_workspace_layout_control(page, "#workspace-toggle-sidebar")
        checks["workbench_mirrors"] = page.evaluate(
            """() => {
                const files = document.querySelector('#file-navigator');
                const inspector = document.querySelector('#author-sidebar');
                const editor = document.querySelector('.editor-pane');
                if (!files || !inspector || !editor) return false;
                // File navigation is the leading region and document tools
                // are trailing. In RTL the file navigator sits on the right.
                return files.getBoundingClientRect().left > editor.getBoundingClientRect().left
                    && inspector.getBoundingClientRect().right <= editor.getBoundingClientRect().left;
            }"""
        )
        page.screenshot(path=str(output_dir / "desktop-fa-dark.png"), full_page=True)

        # The export preview draws into an iframe from code, so the sweep that
        # retranslates elements carrying `data-i18n` cannot reach it. It kept
        # whatever language it was first drawn in until it was made to redraw.
        open_workspace_export(page, None)
        page.wait_for_timeout(900)
        page.screenshot(path=str(output_dir / "export-empty-fa-dark.png"), full_page=True)
        checks["export_settings_start_closed"] = page.locator("#export-settings").is_hidden()
        page.locator("#export-open-settings").click()
        # A value the preset supplied is not a value the user overrode, and
        # "reset" on this screen has to mean "back to the preset" — deleting
        # it sends the engine to its own default instead, which is a different
        # PDF from the one the chosen preset describes.
        style_row = '.option-row[data-option-key="style"]'
        checks["preset_value_is_not_marked_as_an_override"] = page.evaluate(
            f"""() => document.querySelector('{style_row}')?.dataset.source === 'preset'"""
        )
        page.select_option("#adv-style", "academic")
        page.wait_for_timeout(400)
        checks["changing_a_value_marks_it_an_override"] = page.evaluate(
            f"""() => document.querySelector('{style_row}')?.dataset.source === 'override'"""
        )
        page.locator(f"{style_row} .option-reset").click()
        page.wait_for_timeout(400)
        checks["reset_returns_the_preset_value"] = page.evaluate(
            """() => document.querySelector('#adv-style')?.value === 'modern'"""
        )

        # Filtered results are named by the search field, not by a previously
        # selected category. Clearing the query restores the category tabpanel.
        page.locator("#option-search").fill("margin")
        checks["option_search_has_its_own_accessible_region"] = page.evaluate(
            """() => {
                const pane = document.querySelector('#option-pane');
                return pane?.getAttribute('role') === 'region'
                    && pane.getAttribute('aria-labelledby') === 'option-search-label'
                    && !!document.querySelector('#option-search-label')?.textContent.trim();
            }"""
        )
        page.locator("#option-search").fill("")
        page.locator("#option-category").focus()
        page.keyboard.press("ArrowDown")
        checks["option_category_keyboard_focus_survives_rendering"] = page.evaluate(
            """() => {
                const pane = document.querySelector('#option-pane');
                const category = document.querySelector('#option-category');
                return document.activeElement === category && category.value !== 'appearance'
                    && pane?.getAttribute('role') === 'region'
                    && pane.getAttribute('aria-labelledby') === 'option-category-title';
            }"""
        )

        # The two buttons the screen exists for have to be on screen without
        # scrolling past eleven categories of publishing options to find them.
        checks["export_actions_in_view"] = page.evaluate(
            """() => ['#validate-button', '#export-button'].every((selector) => {
                const box = document.querySelector(selector)?.getBoundingClientRect();
                return !!box && box.top >= 0 && box.bottom <= window.innerHeight;
            })"""
        )
        checks["preview_note_localised"] = page.evaluate(
            """() => {
                const frame = document.querySelector('#export-preview iframe');
                const note = frame?.contentDocument?.querySelector('.pv-note');
                const text = note ? note.textContent.trim() : '';
                return text.length > 0 && !/[A-Za-z]{4}/.test(text);
            }"""
        )
        checks["empty_preview_has_clear_next_step"] = (
            page.locator("#export-preview-empty").is_visible()
            and page.locator("#preview-zoom-in").is_disabled()
            and page.locator("#preview-fit-width").is_disabled()
        )
        checks["empty_preview_uses_the_interface_surface"] = page.evaluate(
            """() => {
                const empty = document.querySelector('#export-preview-empty');
                const canvas = document.querySelector('#export-preview');
                return !!empty && getComputedStyle(empty).backgroundColor !== 'rgba(0, 0, 0, 0)'
                    && canvas?.getAttribute('aria-hidden') === 'true';
            }"""
        )
        page.locator("#export-close-settings").click()
        page.locator("#choose-source").click()
        page.wait_for_function(
            "() => !!document.querySelector('#export-preview iframe')?.contentDocument?.querySelector('.pv-page')"
        )
        checks["source_selection_replaces_the_empty_preview"] = (
            page.locator("#export-preview-empty").is_hidden()
            and page.locator("#preview-zoom-in").is_enabled()
            and page.locator("#preview-page-count").inner_text() != "—"
        )
        page.locator("#export-open-settings").click()
        page.locator("#option-category").select_option("appearance")
        page.locator("#adv-style").focus()
        page.locator("#adv-style").select_option("academic")
        checks["export_option_keeps_focus_after_update"] = (
            page.evaluate("document.activeElement?.id") == "adv-style"
        )
        page.locator("#option-category").select_option("contents")
        page.locator('[data-option-key="toc"] .tri-toggle-option').nth(1).click()
        checks["dependent_export_option_is_disabled"] = page.locator("#adv-toc-depth").is_disabled()
        page.set_viewport_size({"width": 840, "height": 640})
        page.locator("#export-show-preview").click()
        compact_preview = (
            page.locator("#export-preview-panel").is_visible()
            and page.locator("#export-settings").is_hidden()
            and page.locator("#export-button").is_hidden()
        )
        page.locator("#export-show-setup").click()
        checks["narrow_export_switches_panes_without_losing_settings"] = (
            compact_preview
            and page.locator("#option-category").input_value() == "contents"
            and page.locator("#adv-toc-depth").is_disabled()
            and page.locator("#export-button").is_visible()
        )
        page.set_viewport_size({"width": 1280, "height": 900})
        page.locator("#export-close-settings").click()
        page.screenshot(path=str(output_dir / "export-selected-source-fa-dark.png"), full_page=True)

        # Keep close available in the inspector tab that owns the current
        # workflow, then detach the project without closing open documents.
        page.locator("#export-back").click()
        page.locator("#sidebar-tab-project").click()
        page.locator("#sidebar-open-project").click()
        page.wait_for_function(
            "() => !document.querySelector('#navigator-project-section')?.classList.contains('hidden')"
        )
        checks["book_project_close_action_is_discoverable"] = (
            page.locator("#sidebar-panel-project #close-project").is_visible()
            and page.locator("#sidebar-tab-book").is_visible()
        )
        page.locator("#sidebar-tab-book").click()
        checks["book_close_action_is_visible_in_book_tools"] = page.locator(
            "#close-book-project"
        ).is_visible()
        page.locator("#sidebar-tab-project").click()
        page.screenshot(
            path=str(output_dir / "book-project-close-action-fa-dark.png"), full_page=True
        )
        open_tabs = page.locator(".document-tab").count()
        page.locator("#sidebar-panel-project #close-project").click()
        page.wait_for_function(
            "() => document.querySelector('#navigator-project-section')?.classList.contains('hidden')"
        )
        checks["closing_book_keeps_open_documents"] = page.locator(
            ".document-tab"
        ).count() == open_tabs and _visible(page, "#book-empty")

        # Escaping a book-creation dialog while its native request is pending
        # invalidates that request's intent. Its late result must not reopen
        # the project the user just dismissed.
        page.locator("#sidebar-tab-book").click()
        page.evaluate("""() => {
            const base = globalThis.__TAURI__.core.invoke;
            globalThis.__lateBookCreate = null;
            globalThis.__TAURI__.core.invoke = (command, args = {}) =>
                command === 'sidecar_request' && args.method === 'book.create'
                    ? new Promise(resolve => { globalThis.__lateBookCreate = resolve; })
                    : base(command, args);
        }""")
        page.locator("#sidebar-new-book").click()
        page.locator("#book-project-title-input").fill("Cancelled book")
        page.locator("#choose-book-parent").click()
        page.wait_for_function(
            "() => document.querySelector('#book-project-parent-input')?.value === '/qa/book'"
        )
        page.locator("#book-project-form button[type='submit']").click()
        page.wait_for_function("() => typeof globalThis.__lateBookCreate === 'function'")
        page.keyboard.press("Escape")
        if _visible(page, "#book-project-modal"):
            raise AssertionError("Escape did not cancel the pending book creation dialog")
        page.evaluate("""() => globalThis.__lateBookCreate({project: {
            path: '/qa/cancelled-book', name: 'Cancelled book', config: 'mardas.toml',
            files: [], book: {enabled: true, title: 'Cancelled book', output: 'dist/book.pdf', chapter_count: 0, chapters: []}
        }})""")
        page.wait_for_timeout(80)
        checks["cancelled_book_creation_does_not_reopen_project"] = not _visible(
            page, "#navigator-project-section"
        ) and not _visible(page, "#project-tools")

        # A chapter mutation may finish after the project is closed. Its
        # response belongs to the old project generation and must be ignored.
        page.evaluate("""() => {
            const base = globalThis.__TAURI__.core.invoke;
            globalThis.__lateChapterMutation = null;
            globalThis.__TAURI__.core.invoke = async (command, args = {}) => {
                if (command !== 'sidecar_request') return base(command, args);
                if (args.method === 'project.open') {
                    const result = await base(command, args);
                    result.project.config_sha256 = 'fixture-config';
                    return result;
                }
                if (args.method === 'book.add_chapter') {
                    return new Promise(resolve => { globalThis.__lateChapterMutation = resolve; });
                }
                return base(command, args);
            };
        }""")
        page.locator("#sidebar-tab-project").click()
        page.locator("#sidebar-open-project").click()
        page.wait_for_function(
            "() => !document.querySelector('#project-tools')?.classList.contains('hidden')"
        )
        page.locator("#sidebar-tab-book").click()
        page.locator("#book-add-chapter").click()
        page.locator("#chapter-title-input").fill("Late chapter")
        page.locator("#chapter-form button[type='submit']").click()
        page.wait_for_function("() => typeof globalThis.__lateChapterMutation === 'function'")
        page.keyboard.press("Escape")
        page.locator("#sidebar-tab-project").click()
        page.locator("#close-project").click()
        page.evaluate("""() => globalThis.__lateChapterMutation({project: {
            path: '/qa/book', name: 'Book QA', config: 'mardas.toml', config_sha256: 'late-hash',
            files: [], book: {enabled: true, title: 'Book QA', output: 'dist/book.pdf', chapter_count: 1, chapters: []}
        }})""")
        page.wait_for_timeout(80)
        checks["late_chapter_response_does_not_reopen_closed_project"] = not _visible(
            page, "#navigator-project-section"
        ) and not _visible(page, "#project-tools")

        checks["page_errors"] = page_errors
        checks["console_issues"] = console_issues
        browser.close()

    required = {
        key: value
        for key, value in checks.items()
        if key not in {"page_errors", "console_issues", "onboarding_focus"}
    }
    passed = (
        all(value is True for value in required.values()) and not page_errors and not console_issues
    )
    payload = {
        "schema_version": 1,
        "status": "passed" if passed else "failed",
        "checks": checks,
    }
    (output_dir / "report.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = ["# Desktop UI Smoke", "", f"Status: **{payload['status'].upper()}**", ""]
    lines.extend(f"- {key}: `{value}`" for key, value in checks.items())
    (output_dir / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not passed:
        raise RuntimeError(f"Desktop UI smoke failed: {checks}")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run browser-backed smoke checks for desktop UI workflows."
    )
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--executable-path")
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    args = parser.parse_args(argv)
    payload = run_audit(
        args.dist.resolve(strict=True),
        args.output_dir.resolve(strict=False),
        executable_path=args.executable_path,
        timeout_ms=args.timeout_ms,
    )
    print(f"Desktop UI smoke: {payload['status'].upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

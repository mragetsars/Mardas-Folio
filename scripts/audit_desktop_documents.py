#!/usr/bin/env python3
"""Exercise tab history, caret/scroll restoration and metadata through the editor."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from audit_desktop_ui import DEFAULT_DIST, INIT_SCRIPT, serve


def run_audit(dist: Path, output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    results = []
    with serve(dist) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for locale in ("en", "fa"):
            for theme in ("light", "dark"):
                context = browser.new_context(viewport={"width": 1280, "height": 900})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.add_init_script(INIT_SCRIPT)
                page.add_init_script(
                    f"localStorage.setItem('mardas.desktop.locale', {json.dumps(locale)});"
                    "localStorage.setItem('mardas.desktop.preferences.v1', "
                    f"JSON.stringify({{theme: {json.dumps(theme)}, onboardingComplete: true, viewMode: 'source'}}));"
                )
                page.goto(url, wait_until="networkidle")
                page.locator('[data-template-id="report"]').click()
                editor = page.locator(".cm-content")
                mirror = page.locator("#markdown-editor")
                expect(editor).to_be_visible()
                source = "# History A\n\n" + "\n\n".join(f"Paragraph {index}." for index in range(160))
                editor.click()
                page.keyboard.press("Control+a")
                page.keyboard.insert_text(source)
                # Separate typing groups: the setup transaction must not undo
                # together with the change whose ownership the probe checks.
                page.wait_for_timeout(600)
                page.keyboard.press("Control+End")
                page.keyboard.insert_text("\n\nMARKER_A")
                expect(mirror).to_have_value(source + "\n\nMARKER_A")
                cursor_a = page.locator("#cursor-status").inner_text()
                scroll_a = page.locator(".cm-scroller").evaluate("node => node.scrollTop")

                page.locator("#workspace-new").click()
                expect(page.locator(".document-tab")).to_have_count(2)
                base_b = mirror.input_value()
                editor.click()
                page.keyboard.press("Control+End")
                page.keyboard.insert_text("MARKER_B")
                page.keyboard.press("Control+z")
                expect(mirror).to_have_value(base_b)
                page.keyboard.press("Control+z")
                expect(mirror).to_have_value(base_b)

                page.locator(".tab-activate").first.click()
                expect(mirror).to_have_value(source + "\n\nMARKER_A")
                expect(page.locator("#cursor-status")).to_have_text(cursor_a)
                page.wait_for_function(
                    "expected => Math.abs(document.querySelector('.cm-scroller').scrollTop - expected) < 3",
                    arg=scroll_a,
                )
                page.keyboard.press("Control+z")
                expect(mirror).to_have_value(source)
                page.keyboard.press("Control+Shift+Z")
                expect(mirror).to_have_value(source + "\n\nMARKER_A")

                # Tab navigation must focus the replacement DOM node, even
                # though activating a document rebuilds the entire tab strip.
                page.locator(".tab-activate[aria-selected='true']").focus()
                page.keyboard.press("ArrowLeft" if locale == "fa" else "ArrowRight")
                page.wait_for_function(
                    "document.activeElement?.matches('.tab-activate[aria-selected=\"true\"]')"
                )
                expect(mirror).to_have_value(base_b)
                page.keyboard.press("Home")
                expect(mirror).to_have_value(source + "\n\nMARKER_A")

                yaml = '---\ntitle: >-\n  A long\n  title\nauthor:\n  name: Jane\ncustom:\n  keep: true\n---\n\n# Body\n'
                editor.click()
                page.keyboard.press("Control+a")
                page.keyboard.insert_text(yaml)
                page.locator('[data-sidebar="frontmatter"]').click()
                title = page.locator('#frontmatter-form [name="title"]')
                expect(title).to_have_value("A long title")
                expect(page.locator('#frontmatter-form [name="author"]')).to_be_disabled()
                page.locator('#frontmatter-form button[type="submit"]').click()
                expect(mirror).to_have_value(yaml)
                title.fill("New title")
                page.locator('#frontmatter-form button[type="submit"]').click()
                expect(mirror).to_have_value(yaml.replace("title: >-\n  A long\n  title", 'title: "New title"'))

                shell = page.evaluate("""() => ({
                    scroll: document.scrollingElement.scrollTop,
                    top: document.querySelector('.topbar').getBoundingClientRect().top,
                    overflow: document.documentElement.scrollHeight > window.innerHeight
                })""")
                if errors or shell["scroll"] != 0 or shell["top"] < 0 or shell["overflow"]:
                    raise RuntimeError(f"{locale}/{theme}: errors={errors}, shell={shell}")
                results.append({"locale": locale, "theme": theme, "status": "passed"})
                context.close()
        browser.close()
    results.append(run_delayed_image_scope_audit(dist))
    report = {"status": "passed", "scenarios": results}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def run_delayed_image_scope_audit(dist: Path) -> dict[str, object]:
    """A pending native scope grant must never change the owner of visible text."""
    with serve(dist) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.add_init_script(INIT_SCRIPT)
        page.add_init_script(r"""
            localStorage.setItem('mardas.desktop.preferences.v1', JSON.stringify({
                onboardingComplete: true, viewMode: 'source'
            }));
            const baseInvoke = globalThis.__TAURI__.core.invoke;
            globalThis.__pickedFiles = ['/fixtures/document-b.md'];
            globalThis.__scopeBlocked = true;
            globalThis.__scopeResolvers = [];
            globalThis.__TAURI__.core.invoke = async (command, args = {}) => {
                if (command === 'pick_markdown_files') return globalThis.__pickedFiles;
                if (command === 'allow_document_images' && globalThis.__scopeBlocked) {
                    return new Promise(resolve => globalThis.__scopeResolvers.push(resolve));
                }
                if (command === 'sidecar_request' && args.method === 'document.read') {
                    const path = args.params.path;
                    const name = path.includes('multi-c') ? 'C' : path.includes('multi-d') ? 'D' : 'B';
                    return {path, content: `# Document ${name}\n`,
                        revision: 'fixture-b', kind: 'markdown', read_only: false};
                }
                return baseInvoke(command, args);
            };
        """)
        page.goto(url, wait_until="networkidle")
        page.locator('[data-template-id="report"]').click()
        editor = page.locator(".cm-content")
        mirror = page.locator("#markdown-editor")
        editor.click()
        page.keyboard.press("Control+a")
        page.keyboard.insert_text("# Document A\n")
        page.locator("#workspace-open").click()
        page.wait_for_function("globalThis.__scopeResolvers.length > 0")
        expect(mirror).to_have_value("# Document A\n")
        editor.click()
        page.keyboard.press("Control+End")
        page.keyboard.insert_text("EDIT_A_WHILE_B_OPENS")
        edited_a = "# Document A\nEDIT_A_WHILE_B_OPENS"
        page.evaluate("""() => {
            globalThis.__scopeBlocked = false;
            globalThis.__scopeResolvers.splice(0).forEach(resolve => resolve(null));
        }""")
        expect(mirror).to_have_value("# Document B\n")
        page.locator(".tab-activate").first.click()
        expect(mirror).to_have_value(edited_a)

        # A newer tab/Home intent takes precedence over the earlier grant.
        page.evaluate("globalThis.__scopeBlocked = true")
        page.locator(".tab-activate").last.click()
        page.wait_for_function("globalThis.__scopeResolvers.length > 0")
        page.locator(".tab-activate").first.focus()
        page.keyboard.press("Home")
        page.evaluate("""() => {
            globalThis.__scopeBlocked = false;
            globalThis.__scopeResolvers.splice(0).forEach(resolve => resolve(null));
        }""")
        expect(mirror).to_have_value(edited_a)
        expect(page.locator(".tab-activate").first).to_have_attribute("aria-selected", "true")

        # Several paths must become visible as one completed activation. The
        # first ready grant cannot transfer ownership during the next grant.
        page.evaluate("""() => {
            globalThis.__pickedFiles = ['/fixtures/multi-c.md', '/fixtures/multi-d.md'];
            globalThis.__scopeBlocked = true;
        }""")
        page.locator("#workspace-open").click()
        page.wait_for_function("globalThis.__scopeResolvers.length > 0")
        editor.click()
        page.keyboard.press("Control+End")
        page.keyboard.insert_text("_DURING_C")
        page.evaluate("globalThis.__scopeResolvers.shift()(null)")
        page.wait_for_function("globalThis.__scopeResolvers.length > 0")
        expect(mirror).to_have_value(edited_a + "_DURING_C")
        editor.click()
        page.keyboard.press("Control+End")
        page.keyboard.insert_text("_DURING_D")
        page.evaluate("""() => {
            globalThis.__scopeBlocked = false;
            globalThis.__scopeResolvers.splice(0).forEach(resolve => resolve(null));
        }""")
        expect(mirror).to_have_value("# Document D\n")
        expect(page.locator(".document-tab")).to_have_count(4)
        page.locator(".tab-activate").nth(2).click()
        expect(mirror).to_have_value("# Document C\n")
        page.locator(".tab-activate").first.click()
        edited_a += "_DURING_C_DURING_D"
        expect(mirror).to_have_value(edited_a)

        # Closing an inactive target while its activation is suspended must
        # keep the currently visible document and discard the pending intent.
        page.evaluate("globalThis.__scopeBlocked = true")
        page.locator(".tab-activate").last.click()
        page.wait_for_function("globalThis.__scopeResolvers.length > 0")
        page.locator(".document-tab").last.locator(".tab-close").click()
        page.evaluate("""() => {
            globalThis.__scopeBlocked = false;
            globalThis.__scopeResolvers.splice(0).forEach(resolve => resolve(null));
        }""")
        expect(page.locator(".document-tab")).to_have_count(3)
        expect(page.locator(".tab-activate").first).to_have_attribute("aria-selected", "true")
        expect(mirror).to_have_value(edited_a)

        page.evaluate("globalThis.__scopeBlocked = true")
        page.locator(".tab-activate").nth(1).click()
        page.wait_for_function("globalThis.__scopeResolvers.length > 0")
        page.locator("#workspace-home").click()
        page.evaluate("""() => {
            globalThis.__scopeBlocked = false;
            globalThis.__scopeResolvers.splice(0).forEach(resolve => resolve(null));
        }""")
        expect(page.locator("#start-view")).to_have_class("view active")
        expect(mirror).to_have_value(edited_a)
        context.close()
        browser.close()
    return {"scenario": "delayed-native-image-scope", "status": "passed"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--output-dir", type=Path, default=Path("build/desktop-document-audit"))
    args = parser.parse_args()
    print(json.dumps(run_audit(args.dist, args.output_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

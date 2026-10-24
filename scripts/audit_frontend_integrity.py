#!/usr/bin/env python3
"""Exercise search ownership and competing confirmations in the real editor.

Native file IPC is an isolated in-memory fixture; no user profile or file is read.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from audit_desktop_ui import DEFAULT_DIST, INIT_SCRIPT, serve


def run_audit(dist: Path, output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    scenarios: list[dict[str, object]] = []
    with serve(dist) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for locale, theme in (("en", "light"), ("fa", "dark")):
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script(INIT_SCRIPT)
            page.add_init_script(
                f"localStorage.setItem('mardas.desktop.locale', {json.dumps(locale)});"
                "localStorage.setItem('mardas.desktop.preferences.v1', JSON.stringify("
                f"{{theme: {json.dumps(theme)}, onboardingComplete: true, viewMode: 'source', autoPreview: false}}));"
            )
            page.add_init_script(r"""
              const baseInvoke = globalThis.__TAURI__.core.invoke;
              globalThis.__saves = [];
              globalThis.__TAURI__.core.invoke = async (command, args = {}) => {
                if (command === 'pick_markdown_output') return '/fixtures/search-a.md';
                if (command === 'sidecar_request' && args.method === 'document.save') {
                  globalThis.__saves.push(args.params);
                  if (globalThis.__delayConflict && !args.params.force) {
                    return new Promise((resolve, reject) => {
                      globalThis.__rejectSave = () => reject(JSON.stringify({application_code: 'MARDAS-DOCUMENT-CONFLICT'}));
                    });
                  }
                  return {path: args.params.path, revision: 'saved', read_only: false};
                }
                return baseInvoke(command, args);
              };
            """)
            page.goto(url, wait_until="networkidle")
            page.locator('[data-template-id="blank"]').click()
            editor = page.locator(".cm-content")
            mirror = page.locator("#markdown-editor")

            def replace_text(text: str) -> None:
                editor.click()
                page.keyboard.press("Control+a")
                page.keyboard.insert_text(text)

            replace_text("start cat end")
            page.keyboard.press("Control+h")
            page.locator("#find-query").fill("cat")
            page.locator("#replace-query").fill("dog")
            editor.click()
            page.keyboard.press("Control+Home")
            page.keyboard.insert_text("prefix ")
            page.wait_for_timeout(600)
            page.locator("#replace-one").click()
            expect(mirror).to_have_value("prefix start dog end")
            page.keyboard.press("Control+z")
            expect(mirror).to_have_value("prefix start cat end")
            page.locator("#tab-new-document").click()
            replace_text("cat second")
            page.locator("#replace-one").click()
            expect(mirror).to_have_value("dog second")
            page.keyboard.press("Control+z")
            expect(mirror).to_have_value("cat second")
            replace_text("unrelated")
            expect(page.locator("#find-count")).to_have_text("0/0")
            page.locator("#replace-one").click()
            expect(mirror).to_have_value("unrelated")
            replace_text("cat cat cat")
            page.locator("#find-next").click()
            page.locator("#replace-query").fill("catapult")
            page.locator("#replace-one").click()
            expect(mirror).to_have_value("cat catapult cat")
            expect(page.locator("#find-count")).to_have_text("3/3")
            replace_text("فارسي " * 10_025)
            page.locator("#find-query").fill("فارسی")
            page.locator("#replace-query").fill("text")
            page.locator("#replace-all").click()
            expect(mirror).to_have_value("text " * 10_025)
            page.locator("#close-find").click()

            # A save conflict completes while the user is already answering
            # whether a different dirty tab should be closed.
            page.locator(".tab-activate").first.click()
            page.locator("#workspace-save").click()
            page.wait_for_function("() => globalThis.__saves.length === 1")
            editor.click()
            page.keyboard.press("Control+End")
            page.keyboard.insert_text(" changed")
            page.evaluate("globalThis.__delayConflict = true")
            page.locator("#workspace-save").click()
            page.wait_for_function("() => typeof globalThis.__rejectSave === 'function'")
            page.locator(".tab-close").last.click()
            expect(page.locator("#confirm-modal")).to_be_visible()
            first_title = page.locator("#confirm-title").inner_text()
            page.evaluate("globalThis.__rejectSave()")
            page.wait_for_timeout(100)
            expect(page.locator("#confirm-title")).to_have_text(first_title)
            page.locator("#confirm-cancel").click()
            expect(page.locator("#confirm-modal")).to_be_visible()
            expect(page.locator("#confirm-title")).not_to_have_text(first_title)
            page.locator("#confirm-cancel").click()
            expect(page.locator("#confirm-modal")).to_be_hidden()
            expect(page.locator(".document-tab")).to_have_count(2)
            assert not any(item.get("force") for item in page.evaluate("globalThis.__saves"))
            assert not errors, errors
            scenarios.append({"locale": locale, "theme": theme, "status": "passed", "checks": [
                "search offsets after typing", "search ownership after tab switch", "replace undo",
                "no-match replacement", "replace advances past inserted text", "replace all beyond 10000",
                "late conflict keeps separate close confirmation", "cancel never forces disk overwrite",
            ]})
            context.close()
        browser.close()
    report = {"status": "passed", "scenarios": scenarios}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--out", type=Path, default=Path("build/frontend-integrity-audit"))
    args = parser.parse_args()
    print(json.dumps(run_audit(args.dist, args.out), indent=2))

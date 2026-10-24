#!/usr/bin/env python3
"""Check pre-install document safety with isolated native IPC fixtures."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from audit_desktop_ui import DEFAULT_DIST, INIT_SCRIPT, open_settings, serve


UPDATE_FIXTURE = r"""
localStorage.setItem('mardas.desktop.locale', 'en');
localStorage.setItem('mardas.desktop.preferences.v1', JSON.stringify({
  onboardingComplete: true, viewMode: 'source', autoPreview: false
}));
const baseInvoke = globalThis.__TAURI__.core.invoke;
globalThis.__saved = [];
globalThis.__installs = [];
globalThis.__pickerCancelled = false;
globalThis.__pickIndex = 0;
globalThis.__TAURI__.core.invoke = async (command, args = {}) => {
  if (command === 'updater_status') return {configured: true, current_version: '2.1.0', channel: 'stable'};
  if (command === 'updater_check') return {available: true, version: '2.2.0'};
  if (command === 'updater_install') {
    globalThis.__installs.push(args);
    return new Promise(resolve => { globalThis.__completeInstall = resolve; });
  }
  if (command === 'pick_markdown_output') {
    return globalThis.__pickerCancelled ? null : `/fixtures/draft-${++globalThis.__pickIndex}.md`;
  }
  if (command === 'sidecar_request' && args.method === 'document.save') {
    const params = args.params;
    globalThis.__saved.push(params);
    const result = {path: params.path, revision: 'saved', read_only: false};
    if (globalThis.__delayNextSave) {
      globalThis.__delayNextSave = false;
      return new Promise(resolve => { globalThis.__completeSave = () => resolve(result); });
    }
    if (globalThis.__conflict && !params.force) {
      throw JSON.stringify({application_code: 'MARDAS-DOCUMENT-CONFLICT'});
    }
    return result;
  }
  return baseInvoke(command, args);
};
"""


def run_audit(dist: Path, output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    checks: list[str] = []
    with serve(dist) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for scenario in ("cancel", "large-and-delayed", "conflict"):
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            page.set_default_timeout(30_000)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script(INIT_SCRIPT)
            page.add_init_script(UPDATE_FIXTURE)
            page.goto(url, wait_until="networkidle")
            page.locator('[data-template-id="blank"]').click()
            editor = page.locator(".cm-content")
            editor.click()
            page.keyboard.press("Control+a")
            content = "draft needing a file"
            if scenario == "large-and-delayed":
                content = "A long draft. " * 72_000  # 1,008,000 chars, beyond per-document recovery.
            page.keyboard.insert_text(content)
            # Disk saving, not recovery storage, is the safety boundary.
            page.evaluate("() => { Storage.prototype.setItem = () => { throw new DOMException('quota', 'QuotaExceededError'); }; }")
            if scenario == "large-and-delayed":
                page.evaluate("globalThis.__delayNextSave = true")
                page.locator("#workspace-save").click()
                page.wait_for_function("() => typeof globalThis.__completeSave === 'function'")
                editor.click()
                page.keyboard.press("Control+End")
                page.keyboard.insert_text("LATEST")
                content += "LATEST"
                for index in range(13):
                    page.locator("#tab-new-document").click()
                    editor.click()
                    page.keyboard.press("Control+a")
                    page.keyboard.insert_text(f"Other draft {index}")
                expect(page.locator(".document-tab")).to_have_count(14)
            elif scenario == "conflict":
                page.locator("#workspace-save").click()
                page.wait_for_function("() => globalThis.__saved.length === 1")
                editor.click()
                page.keyboard.press("Control+End")
                page.keyboard.insert_text(" NEWER")
                content += " NEWER"
                page.evaluate("globalThis.__conflict = true")
            else:
                page.evaluate("globalThis.__pickerCancelled = true")
            open_settings(page)
            page.locator("#check-updates").click()
            expect(page.locator("#install-update")).to_be_visible()
            page.locator("#install-update").click()
            expect(page.locator("#confirm-accept")).to_have_text("Save and install update")
            page.locator("#confirm-accept").click()
            if scenario == "large-and-delayed":
                page.wait_for_timeout(100)
                assert page.evaluate("globalThis.__installs.length") == 0
                page.evaluate("globalThis.__completeSave()")
                page.wait_for_function("() => globalThis.__installs.length === 1")
                saved = page.evaluate("globalThis.__saved.map(item => ({path: item.path, content: item.content}))")
                assert len(saved) == 15, len(saved)  # old pending snapshot + latest first draft + 13 others.
                assert saved[1]["content"] == content
                assert len({item["path"] for item in saved}) == 14
                page.locator("#close-settings").click()
                editor.click()
                page.keyboard.insert_text("MUST_NOT_EDIT_DURING_INSTALL")
                expect(page.locator("#markdown-editor")).to_have_value("Other draft 12")
                page.evaluate("globalThis.__completeInstall({})")
                page.wait_for_function("() => document.querySelector('.cm-content').getAttribute('contenteditable') === 'true'")
                page.keyboard.insert_text(" editable again")
                expect(page.locator("#markdown-editor")).to_have_value("Other draft 12 editable again")
                checks.extend(["14 dirty drafts saved beyond recovery limits", "1M+ draft persisted with unavailable storage",
                               "update waits for pending save and persists newer edits", "editing frozen only during install"])
            else:
                if scenario == "conflict":
                    expect(page.locator("#confirm-accept")).to_have_text("Replace file")
                    page.locator("#confirm-cancel").click()
                expect(page.locator("#install-update")).to_be_enabled()
                assert page.evaluate("globalThis.__installs.length") == 0
                page.locator("#close-settings").click()
                editor.click()
                page.keyboard.press("Control+End")
                page.keyboard.insert_text(" editable again")
                expect(page.locator("#markdown-editor")).to_have_value(content + " editable again")
                checks.append(f"{scenario}: no installer starts, draft remains editable")
            assert not errors, errors
            context.close()
        browser.close()
    report = {"status": "passed", "checks": checks}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--out", type=Path, default=Path("build/update-safety-audit"))
    args = parser.parse_args()
    print(json.dumps(run_audit(args.dist, args.out), indent=2))

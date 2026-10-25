#!/usr/bin/env python3
"""Exercise the Markdown workspace through real CodeMirror user interactions.

The bridge fixture supplies files and deterministic preview HTML; it does not
claim to test the rendering engine. The checks exercise document identity,
keyboard navigation, reading safety, authoring actions and responsive reach.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from playwright.sync_api import expect, sync_playwright

from audit_desktop_ui import DEFAULT_DIST, INIT_SCRIPT, open_settings, serve


FIXTURE_A = "/fixtures/alpha/report.md"
FIXTURE_B = "/fixtures/بتا/report.md"
CONTENT_A = "# Alpha document\n\nAlpha body UNIQUE_ALPHA.\n\n## Second section\n\nA final paragraph.\n"
CONTENT_B = "# سند بتا\n\nمتن فارسی UNIQUE_BETA و Markdown.\n\n## بخش دوم\n\nپاراگراف آخر.\n"

BRIDGE_SCRIPT = r"""
const originalInvoke = globalThis.__TAURI__.core.invoke;
globalThis.__auditFiles = {
  '/fixtures/alpha/report.md': '# Alpha document\n\nAlpha body UNIQUE_ALPHA.\n\n## Second section\n\nA final paragraph.\n',
  '/fixtures/بتا/report.md': '# سند بتا\n\nمتن فارسی UNIQUE_BETA و Markdown.\n\n## بخش دوم\n\nپاراگراف آخر.\n'
};
globalThis.__auditPickedFiles = Object.keys(globalThis.__auditFiles);
globalThis.__auditPreviewHeld = false;
globalThis.__auditPreviewRequests = [];
globalThis.__auditPreviewResolvers = [];
globalThis.__auditSaveHeld = false;
globalThis.__auditSaveResolvers = [];
globalThis.__auditProjectEnabled = false;
globalThis.__auditClipboardHeld = false;
globalThis.__auditClipboardResolvers = [];
Object.defineProperty(navigator, 'clipboard', {configurable:true, value: {
  readText: async () => globalThis.__auditClipboardHeld
    ? new Promise(resolve => globalThis.__auditClipboardResolvers.push(resolve))
    : 'CLIPBOARD_MARKER',
  writeText: async () => {}
}});
const escapeHTML = text => String(text).replace(/[&<>"']/g, character =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
globalThis.__auditPreviewResult = params => {
  const map = [];
  let body = String(params.content || '').split('\n').map((line, index) => {
    const heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (heading) {
      const id = `audit-heading-${index + 1}`;
      map.push({id, line:index + 1, level:heading[1].length, title:heading[2]});
      return `<h${heading[1].length} id="${id}" data-source-line="${index + 1}">${escapeHTML(heading[2])}</h${heading[1].length}>`;
    }
    return line ? `<p data-source-line="${index + 1}">${escapeHTML(line)}</p>` : '';
  }).join('');
  if (String(params.content || '').includes('SVG_REFERENCE_FIXTURE')) {
    body += `<svg id="diagram" role="img" aria-labelledby="diagram-title" aria-describedby="diagram-description" viewBox="0 0 200 60">
      <title id="diagram-title">Arrow diagram</title><desc id="diagram-description">A clipped arrow.</desc>
      <defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M0 0 L10 5 L0 10 Z"/></marker>
      <clipPath id="diagram-clip"><rect x="0" y="0" width="200" height="60"/></clipPath></defs>
      <path id="arrow-line" d="M20 30 L160 30" fill="none" stroke="currentColor" marker-end="url(#arrow)" clip-path="url(#diagram-clip)"/>
      </svg><p id="reference-note">A footnote target.</p><a id="reference-jump" href="#reference-note">Jump to footnote</a>
      <label id="reference-label" for="reference-task">A read-only task</label><input id="reference-task" type="checkbox">`;
  }
  return {body_html:body, source_map:map, diagnostics:[]};
};
globalThis.__TAURI__.core.invoke = async (command, args = {}) => {
  if (command === 'pick_markdown_files') return globalThis.__auditPickedFiles;
  if (command === 'pick_project_directory' && globalThis.__auditProjectEnabled) return '/fixtures/book';
  if (command === 'sidecar_request') {
    if (args.method === 'document.read') {
      const path = args.params.path;
      return {path, content:globalThis.__auditFiles[path], revision:'audit-fixture',
        kind:'markdown', read_only:false};
    }
    if (args.method === 'document.save') {
      const params = {...args.params};
      const save = () => {
        globalThis.__auditFiles[params.path] = params.content;
        return {path:params.path, content:params.content, revision:'audit-saved',
          kind:'markdown', read_only:false};
      };
      if (globalThis.__auditSaveHeld) return new Promise(resolve =>
        globalThis.__auditSaveResolvers.push(() => resolve(save())));
      return save();
    }
    if (args.method === 'project.open') {
      return {path:'/fixtures/book', name:'Audit book', config_sha256:'audit-book',
        files:[{path:'chapters/one.md', kind:'markdown'}], diagnostics:[],
        book:{title:'Audit book', chapter_count:1, output:'dist/book.pdf',
          chapters:[{path:'chapters/one.md', title:'First chapter'}]}};
    }
    if (args.method === 'book.preview') {
      return {html:'<!doctype html><html><head><style>body{display:none}</style></head><body><h1>FULL_BOOK_UNIQUE</h1><p>All chapters preview.</p></body></html>', diagnostics:[]};
    }
    if (args.method === 'preview.document_text') {
      const params = {...args.params};
      globalThis.__auditPreviewRequests.push(params);
      if (globalThis.__auditPreviewHeld) {
        return new Promise(resolve => globalThis.__auditPreviewResolvers.push(
          () => resolve(globalThis.__auditPreviewResult(params))));
      }
      return globalThis.__auditPreviewResult(params);
    }
  }
  return originalInvoke(command, args);
};
"""


def initialise(page: Any, url: str, locale: str, theme: str, *, source: bool = True) -> None:
    page.add_init_script(INIT_SCRIPT)
    page.add_init_script(BRIDGE_SCRIPT)
    page.add_init_script(
        f"localStorage.setItem('mardas.desktop.locale', {json.dumps(locale)});"
        "localStorage.setItem('mardas.desktop.preferences.v1', JSON.stringify("
        f"{{theme:{json.dumps(theme)}, onboardingComplete:true, "
        f"viewMode:{json.dumps('source' if source else 'write')}}}));"
    )
    page.goto(url, wait_until="networkidle")


def editor(page: Any) -> Any:
    return page.locator(".codemirror-mount .cm-content")


def mirror(page: Any) -> Any:
    return page.locator("#markdown-editor")


def replace_content(page: Any, value: str) -> None:
    editor(page).click()
    page.keyboard.press("Control+a")
    if value:
        page.keyboard.insert_text(value)
    else:
        page.keyboard.press("Backspace")
    expect(mirror(page)).to_have_value(value)


def mode(page: Any, name: str) -> None:
    activity = "source" if name == "split" else name
    page.locator(f'[data-view-mode="{activity}"][role="radio"]').click()
    expect(page.locator(".editor-pane")).to_have_attribute("data-view-mode", activity)
    # Old audit cases name a complete arrangement. The product now keeps the
    # activity and side-pane preference independent; configure both explicitly.
    if activity != "read":
        toggle = page.locator("#workspace-toggle-preview")
        wanted = name == "split"
        if (toggle.get_attribute("aria-pressed") == "true") != wanted:
            toggle.click()
        expect(toggle).to_have_attribute("aria-pressed", str(wanted).lower())


def navigator_item(page: Any, index: int) -> Any:
    return page.locator("#open-document-list button[data-document-id]").nth(index)


def check_hidden_region(page: Any, selector: str) -> None:
    """A collapsed region must not expose controls in the keyboard sequence."""
    focusable = page.locator(selector).evaluate("""root => Array.from(root.querySelectorAll(
      'button,input,select,textarea,a[href],[tabindex]')).filter(node => {
        const style = getComputedStyle(node);
        return !node.disabled && node.tabIndex >= 0 && !node.closest('[inert]')
          && node.getClientRects().length && style.visibility !== 'hidden';
      }).map(node => node.id || node.tagName)""")
    if focusable:
        raise AssertionError(f"Closed {selector} leaves focusable controls: {focusable}")


def run_behavior(page: Any, output: Path, locale: str, theme: str, checks: list[str]) -> list[str]:
    page.locator("#workflow-open").click()
    expect(page.locator(".document-tab")).to_have_count(2)
    expect(editor(page)).to_be_visible()
    expect(mirror(page)).to_have_value(CONTENT_B)
    expect(page.locator("#open-document-list button[data-document-id]")).to_have_count(2)
    expect(navigator_item(page, 0)).to_contain_text("report.md")
    expect(navigator_item(page, 1)).to_contain_text("report.md")
    navigator_text = page.locator("#open-document-list").inner_text()
    if "alpha" not in navigator_text or "بتا" not in navigator_text:
        raise AssertionError("Same-name files need visible distinct parent paths in Explorer")
    expect(page.locator("#editor-path")).to_have_attribute("title", FIXTURE_B)
    checks.append("standalone-file-open-and-same-name-paths")

    # File and document structure remain present together. Collapsing one must
    # reclaim space without collapsing the other or retaining hidden controls.
    page.locator("#workspace-toggle-sidebar").click()
    expect(page.locator("#author-sidebar")).to_be_visible()
    expect(page.locator("#file-navigator")).to_be_visible()
    page.locator('[data-sidebar="outline"]').click()
    expect(page.locator("#outline-list")).to_contain_text("بخش دوم")
    inspector_width = page.locator(".editor-pane").bounding_box()["width"]
    page.locator("#inspector-close").click()
    check_hidden_region(page, "#author-sidebar")
    expect(page.locator("#file-navigator")).to_be_visible()
    if page.locator(".editor-pane").bounding_box()["width"] <= inspector_width:
        raise AssertionError("Closing the inspector did not reclaim document width")
    checks.append("independent-explorer-inspector-and-space-reclamation")

    navigator_item(page, 0).click()
    expect(mirror(page)).to_have_value(CONTENT_A)
    editor(page).click()
    page.keyboard.press("Control+End")
    page.wait_for_timeout(600)  # A separate undo group from fixture activation.
    page.keyboard.press("Enter")
    page.keyboard.insert_text("EDIT_ALPHA")
    updated_a = CONTENT_A + "\nEDIT_ALPHA"
    expect(mirror(page)).to_have_value(updated_a)
    checks.append("navigator-alpha-edit-updates-visible-document")
    expect(navigator_item(page, 0)).to_have_class(re.compile(r"\bdirty\b"))
    expect(page.locator("#save-state")).not_to_be_empty()
    cursor_a = page.locator("#cursor-status").inner_text()
    navigator_item(page, 1).click()
    expect(mirror(page)).to_have_value(CONTENT_B)
    editor(page).click()
    page.keyboard.press("Control+End")
    page.keyboard.press("Enter")
    page.keyboard.insert_text("EDIT_BETA")
    updated_b = CONTENT_B + "\nEDIT_BETA"
    expect(mirror(page)).to_have_value(updated_b)
    page.keyboard.press("Control+z")
    expect(mirror(page)).to_have_value(CONTENT_B)
    checks.append("navigator-beta-undo-keeps-beta-content")
    navigator_item(page, 0).click()
    expect(mirror(page)).to_have_value(updated_a)
    expect(page.locator("#cursor-status")).to_have_text(cursor_a)
    checks.append("navigator-edit-ownership-independent-history-and-caret")
    checks.extend(run_clipboard_race(page, updated_a))

    # Ctrl+P is for files; Ctrl+Shift+P is for commands. Query, arrows and Enter
    # must activate the item selected by keyboard, with editor focus restored.
    editor(page).focus()
    page.keyboard.press("Control+p")
    expect(page.locator("#navigation-modal")).to_be_visible()
    page.locator("#navigation-query").fill("بتا")
    expect(page.locator("#navigation-list .navigation-item")).to_have_count(1)
    page.keyboard.press("Enter")
    expect(page.locator("#navigation-modal")).to_be_hidden()
    expect(mirror(page)).to_have_value(CONTENT_B)
    page.wait_for_function("() => document.activeElement?.closest('.cm-editor')")
    page.keyboard.press("Control+p")
    page.locator("#navigation-query").fill("report.md")
    expect(page.locator("#navigation-list .navigation-item")).to_have_count(2)
    page.keyboard.press("ArrowDown")
    selected = page.locator('#navigation-list .navigation-item[aria-selected="true"]')
    expect(selected).to_have_count(1)
    selected_path = selected.inner_text()
    page.keyboard.press("Enter")
    expected = CONTENT_A + "\nEDIT_ALPHA" if "alpha" in selected_path else CONTENT_B
    expect(mirror(page)).to_have_value(expected)
    page.keyboard.press("Control+p")
    page.locator("#navigation-query").fill("alpha")
    page.keyboard.press("Escape")
    expect(mirror(page)).to_have_value(expected)
    page.wait_for_function("() => document.activeElement?.closest('.cm-editor')")
    page.keyboard.press("Control+Shift+p")
    expect(page.locator("#command-modal")).to_be_visible()
    expect(page.locator("#navigation-modal")).to_be_hidden()
    page.keyboard.press("Escape")
    checks.append("distinct-file-and-command-keyboard-pickers")

    navigator_item(page, 1).click()
    page.keyboard.press("Control+Shift+o")
    expect(page.locator("#navigation-modal")).to_be_visible()
    page.locator("#navigation-query").fill("بخش دوم")
    expect(page.locator("#navigation-list .navigation-item")).to_have_count(1)
    page.keyboard.press("Enter")
    expect(page.locator("#navigation-modal")).to_be_hidden()
    expect(page.locator("#cursor-status")).to_contain_text("5")
    checks.append("keyboard-heading-navigation")

    # Reading is a distinct, read-only destination; keyboard shortcuts and
    # controls must not mutate an editor that is hidden behind it.
    mode(page, "read")
    expect(page.locator("#reading-surface")).to_be_visible()
    expect(page.locator("#reading-document")).to_contain_text("UNIQUE_BETA")
    expect(editor(page)).to_be_hidden()
    page.keyboard.press("Control+Shift+p")
    page.locator("#command-query").fill("math")
    expect(page.locator("#command-list [data-command-id^='insert-math']")).to_have_count(0)
    page.keyboard.press("Escape")
    navigator_item(page, 0).click()
    expect(page.locator("#reading-document")).to_contain_text("UNIQUE_ALPHA")
    expect(page.locator("#reading-document")).not_to_contain_text("UNIQUE_BETA")
    navigator_item(page, 1).click()
    expect(page.locator("#reading-document")).to_contain_text("UNIQUE_BETA")
    page.locator("#workspace-toggle-sidebar").click()
    page.locator('[data-sidebar="outline"]').click()
    page.locator("#outline-list button").last.focus()
    page.keyboard.press("Enter")
    expect(editor(page)).to_be_hidden()
    page.wait_for_function("() => document.activeElement?.id === 'reading-document'")
    page.locator("#inspector-close").click()
    page.wait_for_function("() => document.activeElement?.id === 'reading-document'")
    before_reading = mirror(page).input_value()
    page.locator("#reading-surface").click()
    page.keyboard.insert_text("HIDDEN_EDIT_MUST_NOT_EXIST")
    page.keyboard.press("Control+b")
    page.keyboard.press("Control+h")
    page.keyboard.press("Escape")
    expect(mirror(page)).to_have_value(before_reading)
    mode(page, "source")
    expect(editor(page)).to_be_visible()
    page.keyboard.press("Control+Shift+p")
    page.locator("#command-query").fill("math")
    expect(page.locator("#command-list [data-command-id^='insert-math']")).to_have_count(2)
    page.keyboard.press("Escape")
    checks.append("palette-editing-actions-follow-readable-and-editable-modes")
    expect(mirror(page)).to_have_value(CONTENT_B)
    editor(page).focus()
    page.keyboard.press("Control+Shift+z")
    expect(mirror(page)).to_have_value(updated_b)
    for view in ("write", "split", "source"):
        mode(page, view)
        expect(mirror(page)).to_have_value(updated_b)
    page.keyboard.press("Control+z")
    expect(mirror(page)).to_have_value(CONTENT_B)
    checks.append("reading-cannot-edit-and-mode-changes-preserve-history")

    # A slow render may retain the previous article for continuity, but it
    # must explicitly identify that article as stale until the new one arrives.
    page.evaluate("globalThis.__auditPreviewHeld = true")
    editor(page).click()
    page.keyboard.press("Control+End")
    page.keyboard.press("Enter")
    page.keyboard.insert_text("LATEST_BETA_PENDING")
    mode(page, "read")
    page.wait_for_function("() => globalThis.__auditPreviewResolvers.length > 0")
    expect(page.locator("#reading-loading")).to_be_visible()
    expect(page.locator("#reading-surface [data-content-status]")).to_have_attribute("data-stale", "true")
    page.evaluate("""() => {
        globalThis.__auditPreviewHeld = false;
        globalThis.__auditPreviewResolvers.splice(0).forEach(resolve => resolve());
    }""")
    expect(page.locator("#reading-document")).to_contain_text("LATEST_BETA_PENDING")
    expect(page.locator("#reading-loading")).to_be_hidden()
    checks.append("reader-hides-stale-result-until-current-render-completes")

    checks.extend(run_preview_references(page))
    checks.extend(run_reader_empty_navigation(page))

    mode(page, "source")
    page.locator("#workspace-toggle-sidebar").click()
    expect(page.locator("#author-sidebar")).to_be_visible()
    page.locator("#workspace-toggle-formatting").click()
    expect(page.locator(".format-bar")).to_be_visible()
    layout_before = {
        "files": page.locator("#file-navigator").is_visible(),
        "inspector": page.locator("#author-sidebar").is_visible(),
        "formatting": page.locator(".format-bar").is_visible(),
    }
    page.locator("#workspace-focus").click()
    expect(page.locator("#exit-focus-mode")).to_be_visible()
    for region in ("#file-navigator", "#author-sidebar", ".format-bar"):
        check_hidden_region(page, region)
    page.locator("#exit-focus-mode").click()
    for key, selector in (("files", "#file-navigator"), ("inspector", "#author-sidebar"),
                          ("formatting", ".format-bar")):
        if page.locator(selector).is_visible() != layout_before[key]:
            raise AssertionError(f"Leaving Focus did not restore {key}")
    page.locator("#workspace-focus").click()
    editor(page).focus()
    page.keyboard.press("Escape")
    expect(page.locator("#exit-focus-mode")).to_be_hidden()
    expect(page.locator("#file-navigator")).to_be_visible()
    expect(page.locator("#author-sidebar")).to_be_visible()
    checks.append("focus-hidden-controls-exit-and-layout-restoration")

    checks.extend(run_writing_width(page))
    checks.extend(run_export_navigation(page))
    checks.extend(run_authoring(page, locale))
    checks.extend(run_book_preview(page))
    checks.extend(run_narrow_panes(page))
    page.screenshot(path=str(output / f"{locale}-{theme}-workspace.png"), full_page=True)
    return checks


def run_narrow_panes(page: Any) -> list[str]:
    mode(page, "split")
    for selector in ("#workspace-toggle-files", "#workspace-toggle-sidebar"):
        if page.locator(selector).get_attribute("aria-pressed") != "true":
            page.locator(selector).click()
    for selector in ("#file-resizer", "#sidebar-resizer"):
        page.locator(selector).focus()
        page.keyboard.press("End")
    for button in page.locator(".document-toolbar button").all():
        expect(button).to_be_visible()
        button.evaluate("el => el.scrollIntoView({block:'nearest'})")
        geometry = button.evaluate("""el => {
          const r=el.getBoundingClientRect(), pane=el.closest('.editor-pane').getBoundingClientRect();
          const hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
          return {inside:r.left>=pane.left-.5 && r.right<=pane.right+.5,
            reachable:hit===el || el.contains(hit)};
        }""")
        if not geometry["inside"] or not geometry["reachable"]:
            raise AssertionError(f"Narrow editor clips toolbar control {button.get_attribute('id')}: {geometry}")
    for selector in ("#file-resizer", "#sidebar-resizer"):
        page.locator(selector).focus()
        page.keyboard.press("Home")
    return ["toolbar-controls-remain-reachable-with-both-panes-at-maximum-width"]


def run_clipboard_race(page: Any, content_a: str) -> list[str]:
    page.evaluate("globalThis.__auditClipboardHeld = true")
    editor(page).focus()
    page.keyboard.press("Control+End")
    page.keyboard.press("Control+Shift+v")
    page.wait_for_function("() => globalThis.__auditClipboardResolvers.length > 0")
    navigator_item(page, 1).click()
    expect(mirror(page)).to_have_value(CONTENT_B)
    page.evaluate("globalThis.__auditClipboardResolvers.splice(0).forEach(resolve => resolve('LATE_PASTE'))")
    page.wait_for_timeout(150)
    expect(mirror(page)).to_have_value(CONTENT_B)
    navigator_item(page, 0).click()
    expect(mirror(page)).to_have_value(content_a)
    editor(page).focus()
    page.keyboard.press("Control+End")
    page.keyboard.press("Control+Shift+v")
    page.wait_for_function("() => globalThis.__auditClipboardResolvers.length > 0")
    page.keyboard.press("Control+Home")
    page.evaluate("globalThis.__auditClipboardResolvers.splice(0).forEach(resolve => resolve('MOVED_CARET_PASTE'))")
    page.wait_for_timeout(150)
    expect(mirror(page)).to_have_value(content_a)
    page.evaluate("globalThis.__auditClipboardHeld = false")
    page.keyboard.press("Control+End")
    page.keyboard.press("Control+Shift+v")
    expect(mirror(page)).to_have_value(content_a + "CLIPBOARD_MARKER")
    page.keyboard.press("Control+z")
    expect(mirror(page)).to_have_value(content_a)
    return ["async-clipboard-discards-stale-document-and-caret-while-current-paste-works"]


def run_preview_references(page: Any) -> list[str]:
    before = mirror(page).input_value()
    mode(page, "source")
    replace_content(page, before + "\nSVG_REFERENCE_FIXTURE\n")
    mode(page, "split")
    expect(page.locator("#preview-document svg:not(.ui-icon)")).to_have_count(1)
    mode(page, "read")
    expect(page.locator("#reading-document svg:not(.ui-icon)")).to_be_visible()
    for surface, prefix in (("#preview-document", "preview-"),
                            ("#reading-document", "reading-")):
        root = page.locator(surface)
        for identifier in ("diagram", "diagram-title", "diagram-description", "arrow",
                           "diagram-clip", "arrow-line", "reference-note", "reference-jump",
                           "reference-label", "reference-task"):
            expect(root.locator(f'[id="{prefix}{identifier}"]')).to_have_count(1)
            expect(page.locator(f'[id="{prefix}{identifier}"]')).to_have_count(1)
        expect(root.locator(f'#{prefix}diagram')).to_have_attribute("aria-labelledby", f"{prefix}diagram-title")
        expect(root.locator(f'#{prefix}diagram')).to_have_attribute("aria-describedby", f"{prefix}diagram-description")
        expect(root.locator(f'#{prefix}arrow-line')).to_have_attribute("marker-end", f"url(#{prefix}arrow)")
        expect(root.locator(f'#{prefix}arrow-line')).to_have_attribute("clip-path", f"url(#{prefix}diagram-clip)")
        expect(root.locator(f'#{prefix}reference-jump')).to_have_attribute("href", f"#{prefix}reference-note")
        expect(root.locator(f'#{prefix}reference-label')).to_have_attribute("for", f"{prefix}reference-task")
        expect(root.locator(f'#{prefix}reference-task')).to_be_disabled()
    mode(page, "source")
    replace_content(page, before)
    return ["reader-and-split-keep-svg-clip-marker-aria-label-and-anchor-references-within-own-namespace"]


def run_reader_empty_navigation(page: Any) -> list[str]:
    before_b = mirror(page).input_value()
    replace_content(page, "")
    navigator_item(page, 0).click()
    before_a = mirror(page).input_value()
    page.evaluate("globalThis.__auditPreviewHeld = true")
    editor(page).focus()
    page.keyboard.press("Control+End")
    page.keyboard.insert_text("\nHELD_ALPHA_READER\n")
    mode(page, "read")
    page.wait_for_function("() => globalThis.__auditPreviewResolvers.length > 0")
    expect(page.locator("#reading-loading")).to_be_visible()
    navigator_item(page, 1).click()
    expect(mirror(page)).to_have_value("")
    expect(page.locator("#reading-loading")).to_be_hidden()
    expect(page.locator("#preview-loading")).to_be_hidden()
    page.evaluate("""() => {
        globalThis.__auditPreviewHeld = false;
        globalThis.__auditPreviewResolvers.splice(0).forEach(resolve => resolve());
    }""")
    page.wait_for_timeout(150)
    expect(page.locator("#reading-document")).not_to_contain_text("HELD_ALPHA_READER")
    expect(page.locator("#reading-loading")).to_be_hidden()
    mode(page, "source")
    replace_content(page, before_b)
    navigator_item(page, 0).click()
    replace_content(page, before_a)
    navigator_item(page, 1).click()
    return ["reader-clears-loading-on-empty-document-navigation-and-discards-superseded-render"]


def run_writing_width(page: Any) -> list[str]:
    for opener, region in (("#workspace-toggle-files", "#file-navigator"),
                           ("#workspace-toggle-sidebar", "#author-sidebar")):
        if page.locator(region).is_visible():
            page.locator(opener).click()
    mode(page, "write")
    before = mirror(page).input_value()
    editor(page).focus()
    page.keyboard.press("Control+End")
    page.wait_for_timeout(600)
    page.keyboard.insert_text("WIDTH_HISTORY_MARKER")
    expect(mirror(page)).to_have_value(before + "WIDTH_HISTORY_MARKER")
    full_width = editor(page).bounding_box()["width"]
    open_settings(page)
    page.locator("#setting-writing-width").select_option("readable")
    page.locator('#settings-form button[type="submit"]').click()
    comfortable_width = editor(page).bounding_box()["width"]
    if comfortable_width >= full_width - 100:
        raise AssertionError(f"Readable column did not narrow full writing space: {full_width} -> {comfortable_width}")
    open_settings(page)
    page.locator("#setting-writing-width").select_option("wide")
    page.locator('#settings-form button[type="submit"]').click()
    expect(page.locator("html")).to_have_attribute("data-writing-width", "wide")
    wide_width = editor(page).bounding_box()["width"]
    if wide_width <= comfortable_width + 100:
        raise AssertionError(f"Wide column did not enlarge writing space: {comfortable_width} -> {wide_width}")
    saved = page.evaluate("JSON.parse(localStorage.getItem('mardas.desktop.preferences.v1')).writingWidth")
    if saved != "wide":
        raise AssertionError("Writing width preference was not persisted")
    expect(mirror(page)).to_have_value(before + "WIDTH_HISTORY_MARKER")
    mode(page, "source")
    editor(page).focus()
    page.keyboard.press("Control+z")
    expect(mirror(page)).to_have_value(before)
    open_settings(page)
    expect(page.locator("#setting-writing-width")).to_have_value("wide")
    page.keyboard.press("Escape")
    return ["writing-column-preference-persists-and-preserves-source-history"]


def release_saves(page: Any) -> None:
    page.evaluate("""() => {
        globalThis.__auditSaveHeld = false;
        globalThis.__auditSaveResolvers.splice(0).forEach(resolve => resolve());
    }""")


def run_export_navigation(page: Any) -> list[str]:
    # A dirty, path-backed file is saved before export. A slow save must not
    # override a newer file-selection intent or export an obsolete snapshot.
    page.locator("#workspace-toggle-files").click()
    navigator_item(page, 0).click()
    mode(page, "source")
    before = mirror(page).input_value()
    page.evaluate("globalThis.__auditSaveHeld = true")
    page.locator("#workspace-export").click()
    page.wait_for_function("() => globalThis.__auditSaveResolvers.length > 0")
    navigator_item(page, 1).click()
    selected_b = mirror(page).input_value()
    release_saves(page)
    page.wait_for_timeout(200)
    expect(page.locator("#workspace-view")).to_be_visible()
    expect(mirror(page)).to_have_value(selected_b)
    navigator_item(page, 0).click()
    expect(mirror(page)).to_have_value(before)
    editor(page).focus()
    page.keyboard.press("Control+End")
    page.keyboard.insert_text("SAVE_STARTED")
    page.evaluate("globalThis.__auditSaveHeld = true")
    page.locator("#workspace-export").click()
    page.wait_for_function("() => globalThis.__auditSaveResolvers.length > 0")
    editor(page).focus()
    page.keyboard.press("Control+End")
    page.keyboard.insert_text("_CHANGED_WHILE_SAVING")
    current = before + "SAVE_STARTED_CHANGED_WHILE_SAVING"
    release_saves(page)
    page.wait_for_timeout(200)
    expect(page.locator("#workspace-view")).to_be_visible()
    expect(mirror(page)).to_have_value(current)
    # A fresh save completes normally; publication returns to the current
    # reading surface and does not transfer focus to its hidden source editor.
    page.locator("#workspace-export").click()
    expect(page.locator("#export-view")).to_be_visible()
    expect(page.locator("#source-path")).to_have_value(FIXTURE_A)
    page.locator("#export-back").click()
    expect(page.locator("#workspace-view")).to_be_visible()
    expect(mirror(page)).to_have_value(current)
    mode(page, "read")
    expect(page.locator("#reading-document")).to_contain_text("_CHANGED_WHILE_SAVING")
    page.locator("#workspace-export").click()
    expect(page.locator("#export-view")).to_be_visible()
    page.locator("#export-back").click()
    expect(page.locator("#reading-surface")).to_be_visible()
    expect(editor(page)).to_be_hidden()
    page.wait_for_function("() => document.activeElement?.id === 'reading-document'")
    expect(mirror(page)).to_have_value(current)
    mode(page, "write")
    return ["export-discarded-after-navigation-or-newer-edit-and-reader-return-preserves-document"]


def run_book_preview(page: Any) -> list[str]:
    before = mirror(page).input_value()
    page.evaluate("globalThis.__auditProjectEnabled = true")
    if not page.locator("#file-navigator").is_visible():
        page.locator("#workspace-toggle-files").click()
    page.locator("#navigator-open-project").click()
    page.locator('[data-sidebar="book"]').click()
    prior_mode = page.locator(".editor-pane").get_attribute("data-view-mode")
    prior_preview = page.locator("#preview-document").text_content()
    page.locator("#book-preview").click()
    expect(page.locator("#book-review-modal")).to_be_visible()
    expect(page.locator("#book-review-document")).to_contain_text("FULL_BOOK_UNIQUE")
    expect(page.locator(".editor-pane")).to_have_attribute("data-view-mode", prior_mode)
    page.wait_for_timeout(400)  # The superseded per-document preview timer.
    expect(page.locator("#book-review-document")).to_contain_text("FULL_BOOK_UNIQUE")
    assert page.locator("#preview-document").text_content() == prior_preview
    expect(mirror(page)).to_have_value(before)
    page.keyboard.press("Escape")
    expect(page.locator("#book-review-modal")).to_be_hidden()
    return ["whole-book-review-has-independent-scope-and-preserves-chapter-mode-and-preview"]


def run_authoring(page: Any, locale: str) -> list[str]:
    mode(page, "write")
    replace_content(page, "")
    page.keyboard.type("/table", delay=40)
    expect(page.locator(".cm-tooltip-autocomplete")).to_be_visible()
    expect(page.locator(".cm-tooltip-autocomplete [role=option]")).to_have_count(1)
    page.wait_for_timeout(150)  # CodeMirror's completion interaction delay.
    page.keyboard.press("Enter")
    expect(mirror(page)).to_have_value(re.compile(r"^\|.+\|\n\|.+---", re.DOTALL))
    page.keyboard.press("Control+z")
    expect(mirror(page)).to_have_value("/table")
    # The same slash in a URL or fenced source is ordinary Markdown text.
    replace_content(page, "https://example.test")
    page.keyboard.press("Control+End")
    page.keyboard.type("/")
    expect(page.locator(".cm-tooltip-autocomplete")).to_be_hidden()
    replace_content(page, "```text\n\n```")
    page.keyboard.press("Control+Home")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("Home")
    page.keyboard.type("/")
    expect(page.locator(".cm-tooltip-autocomplete")).to_be_hidden()

    replace_content(page, "Select me.\n")
    page.keyboard.press("Control+Home")
    for _ in range(6):
        page.keyboard.press("Shift+ArrowRight")
    toolbar = page.locator('.cm-selection-toolbar[role="toolbar"]')
    expect(toolbar).to_be_visible()
    page.keyboard.press("Alt+F10")
    expect(toolbar.locator('[data-editor-command="bold"]')).to_be_focused()
    page.keyboard.press("ArrowLeft" if locale == "fa" else "ArrowRight")
    expect(toolbar.locator('[data-editor-command="italic"]')).to_be_focused()
    page.keyboard.press("Home")
    expect(toolbar.locator('[data-editor-command="bold"]')).to_be_focused()
    page.keyboard.press("Enter")
    expect(mirror(page)).to_have_value("**Select** me.\n")
    page.keyboard.press("Control+z")
    expect(mirror(page)).to_have_value("Select me.\n")
    page.keyboard.press("Control+Home")
    for _ in range(6):
        page.keyboard.press("Shift+ArrowRight")
    page.keyboard.press("Alt+F10")
    page.keyboard.press("Escape")
    page.wait_for_function("() => document.activeElement?.closest('.cm-editor')")
    page.keyboard.press("Control+b")
    expect(mirror(page)).to_have_value("**Select** me.\n")
    for first, second, direction in (("Option", "Value", "ltr"), ("گزینه", "مقدار", "rtl")):
        replace_content(page, f"| {first} | {second} |\n| --- | --- |\n| A | B |\n\nEnd.\n")
        cells = page.locator(".cm-md-table table th")
        expect(cells).to_have_count(2)
        expect(cells.nth(0)).to_have_text(first)
        first_x = cells.nth(0).bounding_box()["x"]
        second_x = cells.nth(1).bounding_box()["x"]
        if (first_x < second_x) != (direction == "ltr"):
            raise AssertionError(f"{locale}: {direction} table columns follow interface direction")
    return ["slash-insertion-single-undo-and-code-url-safety", "contextual-formatting-keyboard-selection-and-undo",
            "english-and-persian-table-column-order-independent-of-interface"]


def run_responsive(page: Any, output: Path, locale: str, theme: str, width: int) -> dict[str, Any]:
    page.locator('[data-template-id="report"]').click()
    expect(editor(page)).to_be_visible()
    replace_content(page, "# Responsive document\n\nمتن فارسی and English.\n\n## A section\n")
    # Check each auxiliary area can be opened, closed and exited with keyboard
    # without shrinking or moving the document outside the viewport.
    for opener, closer, region in (
        ("#workspace-toggle-files", "#navigator-close", "#file-navigator"),
        ("#workspace-toggle-sidebar", "#inspector-close", "#author-sidebar"),
    ):
        if not page.locator(region).is_visible():
            page.locator(opener).click()
        expect(page.locator(region)).to_be_visible()
        close_box = page.locator(closer).bounding_box()
        if not close_box or close_box["x"] < 0 or close_box["x"] + close_box["width"] > width + 1:
            raise AssertionError(f"{width}: panel exit {closer} outside viewport: {close_box}")
        page.locator(closer).focus()
        page.keyboard.press("Enter")
        check_hidden_region(page, region)
        page.wait_for_function("() => document.activeElement?.closest('.cm-editor')")

    for control in ("#format-find", "#insert-menu-button", "#workspace-focus"):
        expect(page.locator(control)).to_be_visible()
    page.locator("#document-actions-menu > summary").click()
    for action in ("#workspace-new", "#workspace-open", "#workspace-save-as", "#workspace-validate"):
        expect(page.locator(action)).to_be_visible()
        box = page.locator(action).bounding_box()
        if not box or box["x"] < -1 or box["x"] + box["width"] > width + 1:
            raise AssertionError(f"{width}: document action {action} cannot be reached: {box}")
    page.keyboard.press("Escape")
    page.locator("#workspace-focus").click()
    expect(page.locator("#exit-focus-mode")).to_be_visible()
    page.locator("#exit-focus-mode").click()
    mode(page, "read")
    expect(page.locator("#reading-surface")).to_be_visible()
    expect(page.locator("#reading-document")).to_contain_text("Responsive document")
    geometry = page.evaluate("""() => ({
        horizontalOverflow: document.documentElement.scrollWidth > innerWidth + 1,
        pageScroll: document.documentElement.scrollHeight > innerHeight + 1,
        document: document.querySelector('#reading-surface').getBoundingClientRect().toJSON(),
        direction: document.documentElement.dir
    })""")
    if geometry["horizontalOverflow"] or geometry["pageScroll"]:
        raise AssertionError(f"{width}/{locale}/{theme}: unwanted page overflow: {geometry}")
    if geometry["document"]["width"] < min(width - 40, 260):
        raise AssertionError(f"{width}: reader has too little usable width: {geometry}")
    page.screenshot(path=str(output / f"{locale}-{theme}-{width}-reading.png"), full_page=True)
    return {"width": width, "locale": locale, "theme": theme, "geometry": geometry, "status": "passed"}


def run_audit(dist: Path, output: Path, *, only: str = "all", variant: str | None = None) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    with serve(dist) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        variants = [(locale, theme) for locale in ("en", "fa") for theme in ("light", "dark")]
        if variant:
            variants = [tuple(variant.split("-", 1))]
        if only in ("all", "behavior", "authoring"):
            scenario = "authoring" if only == "authoring" else "behavior"
            for locale, theme in variants:
                context = browser.new_context(viewport={"width": 1440, "height": 960})
                page = context.new_page()
                page.set_default_timeout(12_000)
                page_errors: list[str] = []
                checks: list[str] = []
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                page.on("console", lambda message: page_errors.append(f"console.error: {message.text}")
                        if message.type == "error" else None)
                try:
                    initialise(page, url, locale, theme)
                    if only == "authoring":
                        page.locator('[data-template-id="blank"]').click()
                        checks = run_authoring(page, locale)
                    else:
                        checks = run_behavior(page, output, locale, theme, checks)
                    if page_errors:
                        raise AssertionError(f"Browser errors: {page_errors}")
                    results.append({"scenario": scenario,
                                    "locale": locale, "theme": theme,
                                    "checks": checks, "status": "passed"})
                except Exception as exc:
                    message = f"{scenario}/{locale}/{theme}: {exc}"
                    errors.append(message)
                    page.screenshot(path=str(output / f"failure-{locale}-{theme}.png"), full_page=True)
                    results.append({"scenario": scenario, "locale": locale, "theme": theme,
                                    "checks": checks, "status": "failed", "error": str(exc),
                                    "editor_state": page.evaluate("""() => ({
                                        activeElement:document.activeElement?.outerHTML.slice(0,400),
                                        contenteditable:document.querySelector('.cm-content')?.contentEditable,
                                        text:document.querySelector('.cm-content')?.textContent,
                                        inert:document.querySelector('.cm-content')?.closest('[inert]')?.className,
                                        mode:document.querySelector('.editor-pane')?.dataset.viewMode
                                    })""")})
                finally:
                    context.close()
        if only in ("all", "responsive"):
            for locale, theme in variants:
                for width in (360, 768, 1024, 1440):
                    context = browser.new_context(viewport={"width": width, "height": 900})
                    page = context.new_page()
                    page.set_default_timeout(12_000)
                    page_errors = []
                    page.on("pageerror", lambda error: page_errors.append(str(error)))
                    page.on("console", lambda message: page_errors.append(f"console.error: {message.text}")
                            if message.type == "error" else None)
                    try:
                        initialise(page, url, locale, theme, source=False)
                        result = run_responsive(page, output, locale, theme, width)
                        if page_errors:
                            raise AssertionError(f"Browser errors: {page_errors}")
                        results.append({"scenario": "responsive", **result})
                    except Exception as exc:
                        message = f"responsive/{locale}/{theme}/{width}: {exc}"
                        errors.append(message)
                        page.screenshot(path=str(output / f"failure-{locale}-{theme}-{width}.png"), full_page=True)
                        results.append({"scenario": "responsive", "locale": locale, "theme": theme,
                                        "width": width, "status": "failed", "error": str(exc)})
                    finally:
                        context.close()
        browser.close()
    report = {"status": "failed" if errors else "passed", "scenarios": results, "errors": errors}
    (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--output-dir", type=Path, default=Path("build/desktop-editor-ux-audit"))
    parser.add_argument("--only", choices=("all", "behavior", "authoring", "responsive"), default="all")
    parser.add_argument("--variant", choices=("en-light", "en-dark", "fa-light", "fa-dark"))
    args = parser.parse_args()
    report = run_audit(args.dist, args.output_dir, only=args.only, variant=args.variant)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

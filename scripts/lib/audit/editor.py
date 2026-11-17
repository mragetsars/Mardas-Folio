"""Deterministic editor fixtures and common user interactions."""

from __future__ import annotations

import json
from typing import Any

from playwright.sync_api import expect

from lib.audit.desktop import INIT_SCRIPT, click_workspace_layout_control

FIXTURE_A = "/fixtures/alpha/report.md"
FIXTURE_B = "/fixtures/بتا/report.md"
CONTENT_A = (
    "# Alpha document\n\nAlpha body UNIQUE_ALPHA.\n\n## Second section\n\nA final paragraph.\n"
)
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
    if (args.method === 'project.open' || args.method === 'project.refresh') {
      return {path:'/fixtures/book', name:'Audit book', config_sha256:'audit-book',
        files:[{path:'chapters/one.md', kind:'markdown'}], diagnostics:[],
        book:{title:'Audit book', chapter_count:1, output:'dist/book.pdf',
          chapters:[{path:'chapters/one.md', title:'First chapter'}]}};
    }
    if (args.method === 'project.read') {
      return {path:'chapters/one.md', absolute_path:'/fixtures/book/chapters/one.md',
        content:'# First chapter\n\nA saved chapter.\n', revision:'audit-chapter',
        sha256:'audit-chapter', kind:'markdown', read_only:false};
    }
    if (args.method === 'project.save') {
      return {path:'chapters/one.md', absolute_path:'/fixtures/book/chapters/one.md',
        content:args.params.content, revision:'audit-chapter-saved',
        sha256:'audit-chapter-saved', kind:'markdown', read_only:false};
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
            click_workspace_layout_control(page, "#workspace-toggle-preview")
        expect(toggle).to_have_attribute("aria-pressed", str(wanted).lower())


def navigator_item(page: Any, index: int) -> Any:
    if page.locator("#navigator-tab-files").get_attribute("aria-selected") != "true":
        page.locator("#navigator-tab-files").click()
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

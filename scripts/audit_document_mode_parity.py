#!/usr/bin/env python3
"""Verify activity/layout contracts with real Markdown payloads in Chromium.

Only the native transport and file pickers are fixtures. The HTTP bridge calls
the actual Python EngineService against exclusive temporary QA documents.
No installed application, personal document or profile is opened.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
from typing import Any

from playwright.sync_api import expect, sync_playwright

from audit_book_workflow import engine_server
from audit_desktop_ui import DEFAULT_DIST, ROOT
from audit_document_preview import RICH, wait_math


SAMPLE = RICH.split("## Inert document HTML", 1)[0] + """
### Third-level heading
#### Fourth-level heading
##### Fifth-level heading
###### Sixth-level heading

> A quotation with English and متن فارسی.

- First list item
- مورد دوم

""" + "\n".join(
    f"## Position section {number}\n\n"
    + f"UNIQUE_POSITION_{number} فارسی and English reading position. " * 14
    + "\n\nSecond paragraph for this section.\n"
    for number in range(1, 13)
)

BRIDGE = r"""
globalThis.__TAURI__ = {
  core: {invoke: async (command, args = {}) => {
    if (command === 'take_launch_files') return [];
    if (command === 'pick_markdown_files') return [globalThis.__modeFixture.pick];
    if (command === 'pick_project_directory') return globalThis.__modeFixture.project;
    if (command === 'sidecar_cancel') return {cancel_requested: false};
    if (command === 'updater_status') return {configured: false};
    if (command !== 'sidecar_request') return null;
    const response = await fetch('/__engine', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({method: args.method, params: args.params})});
    const payload = await response.json();
    if (payload.error) throw JSON.stringify(payload.error);
    return payload.result;
  }}, event: {listen: async () => () => {}}
};
Object.freeze(Object.prototype);
"""

ARTICLE = r"""root => {
  const properties = ['fontFamily', 'fontSize', 'fontWeight', 'lineHeight',
    'marginBlockStart', 'marginBlockEnd', 'paddingBlockStart', 'paddingBlockEnd',
    'paddingInlineStart', 'paddingInlineEnd', 'borderBottomWidth',
    'borderBottomStyle', 'borderRadius', 'backgroundColor', 'display', 'color'];
  const samples = {article: root, h1: root.querySelector('h1'), h2: root.querySelector('h2'),
    h3: root.querySelector('h3'), h4: root.querySelector('h4'), h5: root.querySelector('h5'), h6: root.querySelector('h6'),
    paragraph: root.querySelector('p'), inlineCode: root.querySelector('p code'),
    pre: root.querySelector('pre'), table: root.querySelector('table:not(.codehilitetable):not(.highlighttable)'),
    th: root.querySelector('table:not(.codehilitetable):not(.highlighttable) th'),
    td: root.querySelector('table:not(.codehilitetable):not(.highlighttable) td'), list: root.querySelector('ol,ul'),
    blockquote: root.querySelector('blockquote')};
  const styles = Object.fromEntries(Object.entries(samples).filter(([,node]) => node)
    .map(([key,node]) => {const style = getComputedStyle(node);
      return [key,Object.fromEntries(properties.map(property => [property,style[property]]))];}));
  const copy = root.cloneNode(true);
  copy.querySelectorAll('style,.document-source-jump').forEach(node => node.remove());
  const text = copy.textContent.replace(/\s+/g, ' ').trim();
  const internalLinks = [...root.querySelectorAll('a[href^="#"]')].map(link => {
    const id = link.getAttribute('href').slice(1);
    return {text: link.textContent.trim(), target: id.replace(/^(reading-|preview-)/, ''),
      valid: Boolean(id && root.querySelector(`#${CSS.escape(id)}`))};
  });
  const math = [...root.querySelectorAll('.math')].filter(node => !node.closest('pre,code'));
  return {styles, text, internalLinks,
    math: math.map(node => ({source: node.getAttribute('aria-label'),
      rendered: node.dataset.mathRendered === 'true',
      paths: node.querySelectorAll('mjx-container > svg path').length})),
    headingRoles: [...root.querySelectorAll('h1,h2,h3,h4,h5,h6')].map(node => node.getAttribute('role')),
    sourceButtons: root.querySelectorAll('.document-source-jump').length,
    position: {top: root.scrollTop, height: root.scrollHeight, viewport: root.clientHeight}};
}"""


def _preview_count(calls: list[dict]) -> int:
    return sum(call["method"] == "preview.document_text" for call in calls)


def _activity(page: Any, activity: str) -> None:
    page.locator(f'button[data-view-mode="{activity}"]').click()
    expect(page.locator("#workspace-view")).to_have_attribute("data-view-mode", activity)


def _side_preview(page: Any, *, enabled: bool = True) -> None:
    toggle = page.locator("#workspace-toggle-preview")
    if (toggle.get_attribute("aria-pressed") == "true") != enabled:
        toggle.click()
    expect(toggle).to_have_attribute("aria-pressed", str(enabled).lower())


def _append(page: Any, text: str) -> None:
    page.locator(".cm-content").click()
    page.keyboard.press("Control+End")
    page.keyboard.insert_text(text)


def _source_anchor(page: Any) -> dict[str, object]:
    return page.evaluate(r"""() => {
      const frame = document.querySelector('.cm-scroller').getBoundingClientRect();
      const lines = [...document.querySelectorAll('.cm-lineNumbers .cm-gutterElement')]
        .filter(node => getComputedStyle(node).visibility !== 'hidden' &&
          node.getBoundingClientRect().bottom > frame.top + 1 &&
          node.getBoundingClientRect().top < frame.bottom && /^\d+$/.test(node.textContent.trim()));
      const line = Number(lines[0]?.textContent || 1);
      const raw = document.querySelector('#markdown-editor').value.split('\n');
      const headings = raw.slice(0,line).flatMap((text,index) => /^#{1,6}\s/.test(text)
        ? [{line:index+1,title:text.replace(/^#+\s*/, '')}] : []);
      return {line,heading:headings.at(-1) || null};
    }""")


def _wait_content(page: Any, selector: str) -> None:
    expect(page.locator(selector)).to_contain_text("PREVIEW_RICH_ONLY")
    wait_math(page, selector, 5)


def _set_zoom(page: Any, percent: int) -> None:
    page.locator("#document-zoom-reset").click()
    direction = "in" if percent > 100 else "out"
    for _ in range(abs(percent - 100) // 10):
        page.locator(f"#document-zoom-{direction}").click()
    expect(page.locator("html")).to_have_attribute("data-document-zoom", str(percent))


def run_audit(dist: Path, output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"status": "running", "scope": __doc__, "scenarios": []}
    with tempfile.TemporaryDirectory(prefix="mode-fixture-", dir=output) as temporary:
        fixture_root = Path(temporary).resolve()
        markdown = fixture_root / "parity-document.md"
        config = fixture_root / "settings.toml"
        locked = fixture_root / "locked.md"
        other = fixture_root / "other.md"
        other.write_text("# Other document\n\nOther content.\n", encoding="utf-8")
        project_config = fixture_root / "mardas.toml"
        markdown.write_text(SAMPLE, encoding="utf-8")
        config.write_text('title = "Configuration text"\n', encoding="utf-8")
        locked.write_text("# Locked document\n\nThis file is read only.\n", encoding="utf-8")
        locked.chmod(0o444)
        project_text = 'schema_version = 1\n[project]\ntitle = "Mode parity project"\n'
        project_text += "\n" + "\n".join(f"# Project comment {number}" for number in range(1, 20))
        project_text += "\n# PROJECT_POSITION_TOKEN\n"
        project_config.write_text(project_text, encoding="utf-8")
        project_match_line = next(index + 1 for index, line in enumerate(project_text.splitlines())
                                  if "PROJECT_POSITION_TOKEN" in line)
        (fixture_root / "preview-image.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="60">'
            '<rect width="200" height="60" fill="#2563eb"/></svg>', encoding="utf-8")
        with engine_server(dist) as (url, calls), sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for locale, theme in (("en", "light"), ("fa", "dark")):
                scenario: dict[str, Any] = {"locale": locale, "theme": theme, "checks": [], "parity": []}
                errors: list[str] = []
                external: list[str] = []
                context = browser.new_context(viewport={"width": 1440, "height": 960})
                context.add_init_script(
                    "globalThis.__modeFixture = " + json.dumps({"pick": str(markdown), "project": str(fixture_root)}) + ";"
                    f"localStorage.setItem('mardas.desktop.locale', {json.dumps(locale)});"
                    "localStorage.setItem('mardas.desktop.preferences.v1', JSON.stringify("
                    + json.dumps({"theme": theme, "onboardingComplete": True,
                                  "viewMode": "source", "autoPreview": True}) + "));"
                    + BRIDGE
                )
                page = context.new_page()
                page.set_default_timeout(30_000)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("request", lambda request: external.append(request.url)
                        if request.url.startswith(("http:", "https:")) and not request.url.startswith(url) else None)
                baseline = _preview_count(calls)
                try:
                    page.goto(url, wait_until="networkidle")
                    page.locator("#workflow-open").click()
                    expect(page.locator("#markdown-editor")).to_have_value(SAMPLE)
                    expect(page.locator('button[data-view-mode]')).to_have_count(3)
                    expect(page.locator("#insert-menu-button")).to_be_visible()
                    expect(page.locator("#workspace-toggle-formatting")).to_be_visible()
                    page.locator("#workspace-toggle-formatting").click()
                    expect(page.locator("#format-bar")).to_be_visible()
                    _append(page, "\nHIDDEN_WORK_MARKER\n")
                    page.wait_for_timeout(900)
                    assert _preview_count(calls) == baseline, "Hidden source view generated backend previews"
                    page.keyboard.press("Control+z")
                    expect(page.locator("#markdown-editor")).to_have_value(SAMPLE)
                    scenario["checks"].append("editing with no rendered view performs no speculative engine preview")

                    page.locator("#workspace-toggle-sidebar").click()
                    page.locator('[data-sidebar="problems"]').click()
                    pending = ("This version has not been checked yet. Run Check document." if locale == "en"
                               else "این نسخهٔ متن هنوز بررسی نشده است. «بررسی سند» را اجرا کن.")
                    expect(page.locator("#problem-list")).to_have_text(pending)
                    page.locator("#document-actions-menu > summary").click()
                    page.locator("#workspace-validate").click()
                    expect(page.locator("#problem-list .tool-empty")).not_to_have_text(pending)
                    if page.locator("#document-actions-menu").evaluate("node => node.open"):
                        page.locator("#document-actions-menu > summary").click()
                    _append(page, "\nCHECK_FRESHNESS_TOKEN\n")
                    expect(page.locator("#problem-list")).to_have_text(pending)
                    page.keyboard.press("Control+z")
                    expect(page.locator("#markdown-editor")).to_have_value(SAMPLE)
                    page.locator("#inspector-close").click()
                    scenario["checks"].append("Problems distinguishes unchecked text, completed check and new edits")

                    _side_preview(page)
                    _wait_content(page, "#preview-document")
                    for zoom in (60, 100, 200):
                        _set_zoom(page, zoom)
                        side = page.locator("#preview-document").evaluate(ARTICLE)
                        _activity(page, "read")
                        _wait_content(page, "#reading-document")
                        expect(page.locator("#insert-menu-button")).to_be_hidden()
                        expect(page.locator("#workspace-toggle-formatting")).to_be_hidden()
                        expect(page.locator("#format-bar")).to_be_hidden()
                        read = page.locator("#reading-document").evaluate(ARTICLE)
                        differences = [
                            {"sample": sample, "property": property_name, "side": value,
                             "read": read["styles"].get(sample, {}).get(property_name)}
                            for sample, values in side["styles"].items()
                            for property_name, value in values.items()
                            if read["styles"].get(sample, {}).get(property_name) != value
                        ]
                        assert not differences, differences
                        assert side["text"] == read["text"], "Read and side preview changed content"
                        assert side["internalLinks"] == read["internalLinks"]
                        assert all(link["valid"] for link in read["internalLinks"]), read["internalLinks"]
                        assert side["math"] == read["math"]
                        assert all(item["rendered"] and item["paths"] for item in read["math"])
                        assert all(role != "button" for role in side["headingRoles"])
                        assert side["sourceButtons"] > 0 and read["sourceButtons"] == 0
                        scenario["parity"].append({"zoom": zoom, "computed_differences": differences,
                                                   "math_instances": len(read["math"]), "styles": read["styles"]})
                        page.screenshot(path=str(output / f"{locale}-{theme}-read-{zoom}.png"))
                        _activity(page, "source")
                        expect(page.locator("#preview-pane")).to_be_visible()
                        _wait_content(page, "#preview-document")
                    scenario["checks"].append("same content typography math tables and internal links at 60/100/200 percent")
                    scenario["checks"].append("source navigation is a separate button without replacing heading semantics")

                    _set_zoom(page, 100)
                    _side_preview(page, enabled=False)
                    _append(page, "\nVIEW_HISTORY_TOKEN\n")
                    expected_content = page.locator("#markdown-editor").input_value()
                    cursor = page.locator("#cursor-status").inner_text()
                    source_anchor = _source_anchor(page)
                    _activity(page, "read")
                    _wait_content(page, "#reading-document")
                    expect(page.locator("#reading-document")).to_contain_text("VIEW_HISTORY_TOKEN")
                    page.wait_for_timeout(100)
                    position = page.locator("#reading-document").evaluate("node => ({top:node.scrollTop,height:node.scrollHeight,viewport:node.clientHeight})")
                    assert position["top"] > 0, position
                    read_anchor = page.locator("#reading-document").evaluate("""root => {
                      const top = root.getBoundingClientRect().top;
                      const headings = [...root.querySelectorAll('h1[data-source-line],h2[data-source-line],h3[data-source-line],h4[data-source-line],h5[data-source-line],h6[data-source-line]')];
                      const previous = headings.filter(node => node.getBoundingClientRect().top <= top + 1).at(-1);
                      const next = headings.find(node => node.getBoundingClientRect().top > top + 1);
                      return {previous:Number(previous?.dataset.sourceLine || 1),next:Number(next?.dataset.sourceLine || 100000)};
                    }""")
                    assert read_anchor["previous"] <= source_anchor["line"] <= read_anchor["next"], (source_anchor, read_anchor)
                    _activity(page, "source")
                    expect(page.locator("#markdown-editor")).to_have_value(expected_content)
                    expect(page.locator("#cursor-status")).to_have_text(cursor)
                    page.wait_for_timeout(100)
                    assert page.locator(".cm-scroller").evaluate("node => node.scrollTop") > 0
                    page.locator(".cm-content").focus()
                    page.keyboard.press("Control+z")
                    expect(page.locator("#markdown-editor")).to_have_value(SAMPLE)
                    scenario["position"] = position
                    scenario["source_anchor"] = source_anchor
                    scenario["read_anchor"] = read_anchor
                    scenario["checks"].append("Source/Read changes preserve place cursor content and actual undo history")

                    _side_preview(page)
                    _wait_content(page, "#preview-document")
                    page.locator("label:has(#auto-preview)").click()
                    expect(page.locator("#auto-preview")).not_to_be_checked()
                    before_pause = _preview_count(calls)
                    _append(page, "\nPAUSED_FRESHNESS_TOKEN\n")
                    page.wait_for_timeout(900)
                    assert _preview_count(calls) == before_pause
                    expect(page.locator("#preview-document")).not_to_contain_text("PAUSED_FRESHNESS_TOKEN")
                    expect(page.locator("#preview-pane [data-content-status]")).to_have_attribute("data-stale", "true")
                    _activity(page, "read")
                    expect(page.locator("#reading-document")).to_contain_text("PAUSED_FRESHNESS_TOKEN")
                    expect(page.locator("#reading-auto-preview")).not_to_be_checked()
                    expect(page.locator("#reading-surface [data-content-status]")).to_have_attribute("data-stale", "false")
                    _activity(page, "source")
                    _append(page, "\nMANUAL_REFRESH_TOKEN\n")
                    page.wait_for_timeout(900)
                    page.locator("#refresh-preview").click()
                    expect(page.locator("#preview-document")).to_contain_text("MANUAL_REFRESH_TOKEN")
                    scenario["checks"].append("paused edits are visibly stale while explicit view entry and refresh use current content")

                    _activity(page, "source")
                    _append(page, "\nSTALE_TAB_ENTRY_TOKEN\n")
                    page.evaluate("path => {__modeFixture.pick = path}", str(other))
                    page.locator("#navigator-open").click()
                    expect(page.locator("#markdown-editor")).to_have_value(other.read_text())
                    _activity(page, "read")
                    expect(page.locator("#reading-document")).to_contain_text("Other content.")
                    page.locator(".tab-activate").filter(has_text="parity-document.md").click()
                    expect(page.locator("#reading-document")).to_contain_text("STALE_TAB_ENTRY_TOKEN")
                    assert not page.locator("#reading-auto-preview").is_checked()
                    scenario["checks"].append("tab entry refreshes stale content even while typing updates remain paused")

                    _activity(page, "read")
                    if page.locator("#workspace-toggle-sidebar").get_attribute("aria-pressed") == "false":
                        page.locator("#workspace-toggle-sidebar").click()
                    page.locator('[data-sidebar="frontmatter"]').click()
                    expect(page.locator("#sidebar-panel-frontmatter")).to_be_visible()
                    page.evaluate("path => {__modeFixture.pick = path}", str(config))
                    page.locator("#navigator-open").click()
                    expect(page.locator("#markdown-editor")).to_have_value(config.read_text())
                    expect(page.locator("#workspace-view")).to_have_attribute("data-view-mode", "source")
                    expect(page.locator("#insert-menu-button")).to_be_hidden()
                    expect(page.locator("#workspace-toggle-formatting")).to_be_hidden()
                    expect(page.locator("#format-bar")).to_be_hidden()
                    assert page.evaluate("JSON.parse(localStorage.getItem('mardas.desktop.preferences.v1')).viewMode") == "read"
                    expect(page.locator('button[data-view-mode="read"]')).to_be_disabled()
                    expect(page.locator("#sidebar-panel-frontmatter")).to_be_hidden()
                    expect(page.locator('[data-sidebar="problems"]')).to_have_attribute("aria-selected", "true")
                    page.locator('button[data-view-mode="source"]').focus()
                    for key in ("ArrowRight", "Home", "End", "ArrowLeft"):
                        page.keyboard.press(key)
                        assert page.evaluate("JSON.parse(localStorage.getItem('mardas.desktop.preferences.v1')).viewMode") == "read", key
                    page.locator(".tab-activate").filter(has_text="parity-document.md").click()
                    expect(page.locator("#workspace-view")).to_have_attribute("data-view-mode", "read")
                    expect(page.locator("#reading-document")).to_be_visible()
                    expect(page.locator("#sidebar-panel-frontmatter")).to_be_visible()
                    scenario["checks"].append("plain configuration files derive Source without changing the Markdown reading preference")

                    page.locator("#workspace-home").click()
                    page.locator("#workflow-project").click()
                    expect(page.locator("#file-navigator #project-file-tree")).to_be_visible()
                    page.locator("#project-search-query").fill("PROJECT_POSITION_TOKEN")
                    page.locator("#run-project-search").click()
                    expect(page.locator("#project-search-results button")).to_have_count(1)
                    page.locator("#project-search-results button").click()
                    expect(page.locator("#markdown-editor")).to_have_value(project_text)
                    expect(page.locator("#workspace-view")).to_have_attribute("data-view-mode", "source")
                    expect(page.locator("#cursor-status")).to_contain_text(str(project_match_line))
                    expect(page.locator(".codemirror-mount")).to_have_attribute("data-document-kind", "text")
                    assert not page.locator(".cm-content :is(.tok-heading,.cm-md-heading)").count()
                    assert page.evaluate("JSON.parse(localStorage.getItem('mardas.desktop.preferences.v1')).viewMode") == "read"
                    expect(page.locator(".cm-content")).to_have_attribute("contenteditable", "true")
                    page.locator(".tab-activate").filter(has_text="parity-document.md").click()
                    expect(page.locator("#workspace-view")).to_have_attribute("data-view-mode", "read")
                    scenario["checks"].append("project search opens config at its match while preserving the Markdown reading activity")
                    page.evaluate("path => {__modeFixture.pick = path}", str(locked))
                    page.locator("#navigator-open").click()
                    expect(page.locator("#markdown-editor")).to_have_value(locked.read_text())
                    _activity(page, "source")
                    expect(page.locator(".cm-content")).to_have_attribute("contenteditable", "false")
                    page.keyboard.press("Control+End")
                    page.keyboard.insert_text("SHOULD_NOT_APPEAR")
                    expect(page.locator("#markdown-editor")).to_have_value(locked.read_text())
                    expect(page.locator("#workspace-save-as")).to_be_enabled()
                    scenario["checks"].append("read-only resources stay noneditable across activity changes while Save As remains available")
                    assert not errors, errors
                    assert not external, external
                    scenario["status"] = "passed"
                except Exception as error:
                    scenario["status"] = "failed"
                    scenario["error"] = str(error)
                    page.screenshot(path=str(output / f"{locale}-{theme}-failure.png"))
                finally:
                    scenario["page_errors"] = errors
                    scenario["external_requests"] = external
                    report["scenarios"].append(scenario)
                    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    context.close()

            # Old preferences must preserve the combined source+comparison task.
            context = browser.new_context(viewport={"width": 1440, "height": 960})
            context.add_init_script(
                "globalThis.__modeFixture = " + json.dumps({"pick": str(markdown), "project": str(fixture_root)}) + ";"
                "localStorage.setItem('mardas.desktop.locale','en');"
                "localStorage.setItem('mardas.desktop.preferences.v1',JSON.stringify("
                "{onboardingComplete:true,viewMode:'split'}));" + BRIDGE)
            page = context.new_page()
            try:
                page.goto(url, wait_until="networkidle")
                page.locator("#workflow-open").click()
                expect(page.locator("#workspace-view")).to_have_attribute("data-view-mode", "source")
                expect(page.locator("#workspace-toggle-preview")).to_have_attribute("aria-pressed", "true")
                _wait_content(page, "#preview-document")
                report["legacy_split"] = {"status": "passed"}
            except Exception as error:
                report["legacy_split"] = {"status": "failed", "error": str(error)}
            finally:
                context.close()
                browser.close()
    report["status"] = "passed" if all(item["status"] == "passed" for item in report["scenarios"]) and report["legacy_split"]["status"] == "passed" else "failed"
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--out", type=Path, default=ROOT / "build/product-audit/document-modes")
    args = parser.parse_args()
    result = run_audit(args.dist.resolve(), args.out.resolve())
    print(json.dumps({"status": result["status"], "scenarios": [
        {key: value for key, value in scenario.items() if key not in {"parity"}}
        for scenario in result["scenarios"]], "legacy_split": result["legacy_split"]}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)

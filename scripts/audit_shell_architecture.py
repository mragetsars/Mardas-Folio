#!/usr/bin/env python3
"""Measure shared chrome, nonwrapping four-pane controls and publication edges."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import traceback

from playwright.sync_api import expect, sync_playwright

from audit_desktop_editor_ux import BRIDGE_SCRIPT
from audit_desktop_ui import DEFAULT_DIST, INIT_SCRIPT, serve


def click_control(page, selector):
    page.wait_for_timeout(80)  # Allow the measured overflow's animation frame.
    target = page.locator(selector)
    overflow = not target.is_visible()
    if overflow:
        page.locator("#workspace-view-menu-button").click()
    target.click()
    page.wait_for_timeout(80)
    return overflow


def run(dist: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "running", "cases": []}
    with serve(dist) as url, sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        for locale, theme, width in [("en", "dark", 1920), ("fa", "dark", 1920),
                                      ("en", "light", 1440), ("fa", "light", 1280),
                                      ("en", "dark", 768), ("fa", "dark", 360)]:
            case = {"locale": locale, "theme": theme, "width": width, "checks": []}
            report["cases"].append(case)
            page = browser.new_page(viewport={"width": width, "height": 1000})
            page.set_default_timeout(12000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            desktop = width > 1100
            page.add_init_script(INIT_SCRIPT + BRIDGE_SCRIPT)
            page.add_init_script("localStorage.setItem('mardas.desktop.locale'," + json.dumps(locale) + ");"
                "localStorage.setItem('mardas.desktop.preferences.v1',JSON.stringify(" + json.dumps({
                    "theme": theme, "onboardingComplete": True, "viewMode": "write", "sidePreview": desktop}) + "));"
                "localStorage.setItem('mardas.desktop.workspace-layout.v2',JSON.stringify(" + json.dumps({
                    "filesOpen": desktop, "sidebarOpen": desktop, "filesWidth": 248,
                    "sidebarWidth": 296, "previewWidth": 500, "formattingOpen": True}) + "));")
            try:
                page.goto(url, wait_until="networkidle")
                assert page.locator(".topbar").bounding_box()["height"] == 48
                cta = page.locator("#workflow-new").evaluate("e=>getComputedStyle(e).backgroundColor")
                assert cta != "rgb(245, 158, 11)", cta
                page.screenshot(path=str(output / f"{locale}-{width}-home.png"))
                case["checks"].append("Home retains the same 48px brand/engine header and a neutral primary action surface")
                page.evaluate("""() => {
                  for (const name of ['long-writing-reference.md','TEST_OVERVIEW.fa.md']) {
                    const path='/fixtures/project/docs/'+name;
                    __auditFiles[path]='# '+name+'\\n\\nمتن فارسی همراه با English.\\n\\n## بخش دوم AdaptiveCruiseTest\\n';
                  }
                  __auditPickedFiles=Object.keys(__auditFiles);
                }""")
                page.locator("#workflow-open").click()
                expect(page.locator("#document-tabs .document-tab")).to_have_count(4)
                page.wait_for_timeout(300)
                expected = page.locator("#markdown-editor").input_value()
                geometry = page.evaluate("""() => {
                  const rect=s=>{const e=document.querySelector(s),r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom,scroll:e.scrollWidth,client:e.clientWidth}};
                  return {header:rect('.topbar'),tabs:rect('.tab-bar'),bar:rect('.document-toolbar'),
                    canvas:rect('.editor-surface'),nav:rect('.navigator-heading'),preview:rect('#preview-pane>.pane-header'),
                    inspector:rect('.inspector-heading'),wrap:getComputedStyle(document.querySelector('.document-toolbar')).flexWrap,
                    viewport:innerWidth,pageWidth:document.documentElement.scrollWidth};
                }""")
                case["geometry"] = geometry
                assert geometry["header"]["height"] == 48, geometry
                assert geometry["bar"]["y"] == 48 and geometry["bar"]["height"] == 40, geometry
                assert geometry["canvas"]["y"] == 88, geometry
                assert geometry["wrap"] == "nowrap" and geometry["bar"]["scroll"] <= geometry["bar"]["client"] + 1, geometry
                assert geometry["pageWidth"] <= width + 1, geometry
                placement = page.evaluate("""() => {
                  const bar=document.querySelector('.document-toolbar').getBoundingClientRect();
                  const modes=document.querySelector('.document-activity-controls').getBoundingClientRect();
                  return {leading:document.documentElement.dir==='rtl'?bar.right-modes.right:modes.left-bar.left,
                    buttons:[...document.querySelectorAll('.document-toolbar button')].filter(e=>e.getClientRects().length)
                      .map(e=>{const r=e.getBoundingClientRect();return {x:r.x,right:r.right,top:r.top,bottom:r.bottom}})
                      .sort((a,b)=>a.x-b.x)};
                }""")
                assert 0 <= placement["leading"] <= 10, placement
                for index, button in enumerate(placement["buttons"]):
                    assert button["top"] >= 48 and button["bottom"] <= 88, placement
                    if index:
                        assert placement["buttons"][index - 1]["right"] <= button["x"] + 1, placement
                if desktop:
                    for part in ("nav", "preview", "inspector"):
                        assert geometry[part]["y"] == 48 and geometry[part]["height"] == 40, geometry
                    assert geometry["tabs"]["width"] > geometry["bar"]["width"], geometry
                case["checks"].append("all visible pane controls share the 48→88px keylines; toolbar never wraps; tabs span the global workspace")
                for mode in ("source", "read", "write"):
                    page.locator(f'[data-view-mode="{mode}"][role="radio"]').click()
                    expect(page.locator(".editor-pane")).to_have_attribute("data-view-mode", mode)
                    assert page.locator(".document-toolbar").bounding_box()["height"] == 40
                    if mode == "read":
                        expect(page.locator("#format-bar")).to_be_hidden()
                        expect(page.locator("#refresh-reading")).to_be_visible()
                        expect(page.locator("#reading-auto-preview")).to_have_accessible_name("Live updates" if locale == "en" else "به‌روزرسانی خودکار")
                    case.setdefault("mode_scroll", []).append(page.evaluate("""() => ({
                      mode:document.querySelector('.editor-pane').dataset.viewMode,
                      window:scrollY, root:document.documentElement.scrollTop,body:document.body.scrollTop,
                      shell:document.querySelector('.shell').scrollTop,main:document.querySelector('main').scrollTop,
                      workspace:document.querySelector('#workspace-view').scrollTop,grid:document.querySelector('.authoring-grid').scrollTop,
                      bar:document.querySelector('.topbar').getBoundingClientRect().y})"""))
                expect(page.locator("#markdown-editor")).to_have_value(expected)
                case["checks"].append("Write/Source/Read keep the same chrome height and preserve document bytes")
                if desktop:
                    tabs_before = page.locator(".tab-bar").bounding_box()
                    for selector in ("#workspace-toggle-preview", "#workspace-toggle-sidebar", "#workspace-toggle-files"):
                        click_control(page, selector)
                    tabs_after = page.locator(".tab-bar").bounding_box()
                    assert tabs_before == tabs_after, (tabs_before, tabs_after)
                    assert page.locator(".editor-surface").bounding_box()["y"] == 88
                    for selector in ("#workspace-toggle-files", "#workspace-toggle-sidebar", "#workspace-toggle-preview"):
                        click_control(page, selector)
                    case["checks"].append("one to four pane toggles leave tabs and top keylines fixed")
                    for selector in ("#file-resizer", "#preview-resizer", "#sidebar-resizer"):
                        page.locator(selector).focus()
                        page.keyboard.press("End")
                    page.wait_for_timeout(120)
                    stress = page.locator(".document-toolbar").evaluate("e=>({width:e.clientWidth,scroll:e.scrollWidth,height:e.getBoundingClientRect().height})")
                    assert stress["width"] >= 320 and stress["scroll"] <= stress["width"] + 1 and stress["height"] == 40, stress
                    assert page.locator(".tab-bar").bounding_box() == tabs_before
                    case["stress_geometry"] = stress
                    page.screenshot(path=str(output / f"{locale}-{width}-maximum-panes.png"))
                    case["checks"].append("maximum requested sidebar widths retain a 320px editor, fixed global tabs and one nonwrapping control row")
                else:
                    overflow = click_control(page, "#writing-appearance-button")
                    expect(page.locator("#writing-appearance")).to_be_visible()
                    page.keyboard.press("Escape")
                    expect(page.locator("#writing-appearance")).to_be_hidden()
                    expect(page.locator("#workspace-view-menu")).to_be_hidden()
                    expect(page.locator("#workspace-view-menu-button" if overflow else "#writing-appearance-button")).to_be_focused()
                    case["checks"].append("overflow exposes the original appearance control and Escape returns focus")
                expect(page.locator("#markdown-editor")).to_have_value(expected)
                page.screenshot(path=str(output / f"{locale}-{width}-workspace.png"))
                page.locator("#home-button").click()
                page.locator("#workflow-quick").click()
                edges = page.evaluate("""() => {
                  const r=s=>{const a=document.querySelector(s).getBoundingClientRect();return {left:a.left,right:a.right,width:a.width}};
                  return {content:r('.export-content'),layout:r('.export-layout'),dock:r('.export-dock')};
                }""")
                case["export_edges"] = edges
                assert abs(edges["layout"]["left"] - edges["dock"]["left"]) <= 1, edges
                assert abs(edges["layout"]["right"] - edges["dock"]["right"]) <= 1, edges
                assert not page.evaluate("document.documentElement.scrollWidth>innerWidth+1")
                page.screenshot(path=str(output / f"{locale}-{width}-export.png"))
                case["checks"].append("export destination dock and two-column layout have identical outer edges")
                assert not errors, errors
                case["status"] = "passed"
            except Exception as error:
                case["status"] = "failed"
                case["error"] = (str(error) or traceback.format_exc(limit=2))[:3000]
                page.screenshot(path=str(output / f"{locale}-{width}-failure.png"))
            finally:
                case["page_errors"] = errors
                page.close()
        browser.close()
    report["status"] = "passed" if all(case["status"] == "passed" for case in report["cases"]) else "failed"
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--output", type=Path, default=Path("build/design-system/shell"))
    args = parser.parse_args()
    result = run(args.dist.resolve(), args.output.resolve())
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(result["status"] != "passed")

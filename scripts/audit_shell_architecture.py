#!/usr/bin/env python3
"""Measure shared chrome, nonwrapping four-pane controls and publication edges."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
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


def text_contrast(color, background):
    """WCAG contrast for the computed RGB text on the opaque action surface."""
    foreground = [float(value) for value in re.findall(r"[\d.]+", color)]
    surface = [float(value) for value in re.findall(r"[\d.]+", background)]
    assert len(foreground) in {3, 4} and len(surface) in {3, 4}, (color, background)
    assert len(surface) == 3 or surface[3] == 1, background
    alpha = foreground[3] if len(foreground) == 4 else 1
    foreground = [value * alpha + surface[index] * (1 - alpha)
                  for index, value in enumerate(foreground[:3])]

    def luminance(channels):
        values = [value / 255 for value in channels[:3]]
        values = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
                  for value in values]
        return sum(value * weight for value, weight in zip(values, [.2126, .7152, .0722]))

    values = [luminance(foreground), luminance(surface)]
    return (max(values) + .05) / (min(values) + .05)


def check_home_design_language(page):
    action = page.locator("#workflow-new")
    page.mouse.move(1, 1)
    page.wait_for_timeout(180)
    states = {}
    for name in ("base", "hover"):
        if name == "hover":
            action.hover()
            page.wait_for_timeout(180)
        style = action.evaluate("""e=>{
          const token=document.createElement('i');token.style.color='var(--ui-muted)';
          token.style.display='none';e.append(token);
          const expectedMuted=getComputedStyle(token).color;token.remove();
          return {background:getComputedStyle(e).backgroundColor,
            helper:getComputedStyle(e.querySelector('small')).color,
            title:getComputedStyle(e.querySelector('strong')).color,expectedMuted};
        }""")
        assert style["helper"] == style["expectedMuted"], (name, style)
        style["helperContrast"] = text_contrast(style["helper"], style["background"])
        style["titleContrast"] = text_contrast(style["title"], style["background"])
        assert style["helperContrast"] >= 4.5 and style["titleContrast"] >= 4.5, (name, style)
        states[name] = style
    return states


def command_style(target):
    return target.evaluate("""e=>{
      const s=getComputedStyle(e),r=e.getBoundingClientRect();
      const token=document.createElement('i');token.style.background='var(--ui-control-hover)';
      e.append(token);const expected=getComputedStyle(token).backgroundColor;token.remove();
      return {background:s.backgroundColor,expected,radius:s.borderRadius,height:r.height,
        color:s.color,opacity:s.opacity,disabled:e.disabled};
    }""")


def floating_style(target):
    style = target.evaluate("""e=>{
      const token=document.createElement('i');token.style.background='var(--ui-surface-floating)';
      e.append(token);const expected=getComputedStyle(token).backgroundColor;token.remove();
      return {background:getComputedStyle(e).backgroundColor,expected,inShell:Boolean(e.closest('.shell'))};
    }""")
    assert style["background"] == style["expected"], style
    return style


def hover_command(target):
    target.hover()
    target.page.wait_for_timeout(180)
    style = command_style(target)
    assert style["background"] == style["expected"], style
    assert style["radius"] == "6px", style
    return style


def check_workspace_menu_geometry(page):
    """Measure the opened popup, including local overflow and physical anchor."""
    geometry = page.evaluate("""() => {
      const menu=document.querySelector('#workspace-view-menu');
      const anchor=document.querySelector('#workspace-view-menu-button').getBoundingClientRect();
      const box=menu.getBoundingClientRect();
      const rect=e=>{const r=e.getBoundingClientRect();return {id:e.id,classes:e.className,
        left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height}};
      const children=[...menu.children,...menu.querySelectorAll('button,select,input')]
        .filter(e=>e.getClientRects().length && getComputedStyle(e).visibility!=='hidden')
        .map(rect).filter(r=>r.width>0 && r.height>0);
      return {left:box.left,right:box.right,top:box.top,bottom:box.bottom,width:box.width,
        expectedLeft:Math.max(8,Math.min(anchor.right-box.width,innerWidth-box.width-8)),
        anchorRight:anchor.right,anchorBottom:anchor.bottom,viewportWidth:innerWidth,
        scrollWidth:menu.scrollWidth,clientWidth:menu.clientWidth,children};
    }""")
    assert abs(geometry["left"] - geometry["expectedLeft"]) <= 1, geometry
    assert geometry["scrollWidth"] <= geometry["clientWidth"] + 1, geometry
    assert geometry["left"] >= 7 and geometry["right"] <= geometry["viewportWidth"] - 7, geometry
    assert abs(geometry["top"] - geometry["anchorBottom"] - 6) <= 1, geometry
    for child in geometry["children"]:
        assert child["left"] >= geometry["left"] and child["right"] <= geometry["right"], geometry
    return geometry


def check_disabled_commands(page, url):
    """Open a read-only fixture normally; never synthesize disabled attributes."""
    locale, theme = page.evaluate("[document.documentElement.lang,document.documentElement.dataset.theme]")
    readonly = page.context.browser.new_page(viewport={"width": 1920, "height": 1000})
    readonly.add_init_script(INIT_SCRIPT + BRIDGE_SCRIPT.replace("read_only:false", "read_only:true"))
    readonly.add_init_script("localStorage.setItem('mardas.desktop.locale'," + json.dumps(locale) + ");"
        "localStorage.setItem('mardas.desktop.preferences.v1',JSON.stringify(" + json.dumps({
            "theme": theme, "onboardingComplete": True, "viewMode": "source"}) + "));")
    try:
        readonly.goto(url, wait_until="networkidle")
        readonly.locator("#workflow-open").click()
        undo = readonly.locator('#format-bar button[data-editor-command="undo"]')
        expect(undo).to_be_visible()
        expect(undo).to_be_disabled()
        before = command_style(undo)
        undo.hover(force=True)
        readonly.wait_for_timeout(180)
        after = command_style(undo)
        assert before == after, {"before": before, "after": after}
        assert before["background"] == "rgba(0, 0, 0, 0)" and before["opacity"] == "0.4", before
        return {"before": before, "hover": after, "fixture": "normal document.read read_only:true"}
    finally:
        readonly.close()


def check_design_language(page, url):
    """Exercise real hover/focus after the complete stylesheet cascade loads."""
    surfaces = page.evaluate("""() => {
      const color=s=>getComputedStyle(document.querySelector(s)).backgroundColor;
      return {files:color('.file-navigator'),inspector:color('.author-sidebar'),
        filesHeader:color('.navigator-heading'),inspectorHeader:color('.inspector-heading')};
    }""")
    assert len(set(surfaces.values())) == 1, surfaces
    states = {}
    for selector in ("#writing-appearance-button", "#format-find", "#document-mode-help",
                     "#insert-menu-button", "#workspace-focus", "#workspace-toggle-sidebar"):
        target = page.locator(selector)
        parked = not target.is_visible()
        if parked:
            page.locator("#workspace-view-menu-button").click()
        style = hover_command(target)
        if not parked:
            assert style["height"] == 28, (selector, style)
        states[selector] = style
        if parked:
            page.keyboard.press("Escape")
    # A selected toggle keeps its semantic amber fill while hovered.
    click_control(page, "#workspace-toggle-preview")
    target = page.locator("#workspace-toggle-preview")
    if not target.is_visible():
        page.locator("#workspace-view-menu-button").click()
    target.hover()
    page.wait_for_timeout(180)
    active = target.evaluate("e=>({background:getComputedStyle(e).backgroundColor,pressed:e.getAttribute('aria-pressed')})")
    assert active["pressed"] == "true" and active["background"] != states["#format-find"]["background"], active
    if page.locator("#workspace-view-menu").is_visible():
        page.keyboard.press("Escape")
    click_control(page, "#workspace-toggle-preview")
    # Keyboard navigation must remain visible on the same neutral controls.
    page.locator("#format-find").focus()
    page.keyboard.press("Tab")
    focus = page.locator(":focus").evaluate("e=>({visible:e.matches(':focus-visible'),width:getComputedStyle(e).outlineWidth,style:getComputedStyle(e).outlineStyle})")
    assert focus == {"visible": True, "width": "2px", "style": "solid"}, focus
    # Popovers are moved to body at runtime; check the real opened DOM rather
    # than assuming that floating commands inherit the workspace shell scope.
    click_control(page, "#writing-appearance-button")
    appearance = page.locator("#writing-appearance")
    expect(appearance).to_be_visible()
    floating = {"appearance": floating_style(appearance)}
    assert not floating["appearance"]["inShell"], floating
    floating["appearance_close_hover"] = hover_command(page.locator("#writing-appearance-close"))
    assert floating["appearance_close_hover"]["background"] != floating["appearance"]["background"], floating
    page.locator("#writing-appearance-close").click()
    page.locator(".cm-content").click(button="right", position={"x": 24, "y": 24})
    expect(page.locator("#editor-context-menu")).to_be_visible()
    floating["context"] = floating_style(page.locator("#editor-context-menu"))
    context_item = page.locator("#editor-context-menu .context-menu-item:not(:disabled)").first
    context_item.hover()
    page.wait_for_timeout(180)
    floating["context_item_hover"] = command_style(context_item)
    assert floating["context_item_hover"]["background"] == floating["context_item_hover"]["expected"], floating
    assert floating["context_item_hover"]["background"] != floating["context"]["background"], floating
    page.keyboard.press("Escape")
    page.locator("#command-button").click()
    expect(page.locator("#command-modal")).to_be_visible()
    floating["command"] = floating_style(page.locator("#command-modal .command-card"))
    page.keyboard.press("Escape")
    page.locator("#settings-button").click()
    expect(page.locator("#settings-modal")).to_be_visible()
    floating["settings"] = floating_style(page.locator("#settings-form"))
    floating["settings_close_hover"] = hover_command(page.locator("#close-settings"))
    page.locator("#close-settings").click()
    floating["all_dialogs"] = [floating_style(page.locator(".modal-card").nth(index))
                               for index in range(page.locator(".modal-card").count())]

    viewport = page.viewport_size
    try:
        page.set_viewport_size({"width": 360, "height": viewport["height"]})
        page.wait_for_timeout(180)
        page.locator("#workspace-view-menu-button").click()
        menu = page.locator("#workspace-view-menu")
        expect(menu).to_be_visible()
        floating["workspace_menu"] = floating_style(menu)
        floating["workspace_menu_geometry"] = check_workspace_menu_geometry(page)
        floating["workspace_menu_hover"] = {}
        for selector in ("#writing-appearance-button", "#format-find", "#document-mode-help",
                         "#insert-menu-button", "#workspace-focus", "#workspace-toggle-sidebar"):
            target = menu.locator(selector)
            if target.count() and target.is_visible():
                floating["workspace_menu_hover"][selector] = hover_command(target)
        assert floating["workspace_menu_hover"], floating
        menu.locator("#writing-appearance-button").click()
        expect(appearance).to_be_visible()
        expect(menu).to_be_hidden()
        floating["appearance_from_overflow"] = floating_style(appearance)
        floating["overflow_appearance_close_hover"] = hover_command(page.locator("#writing-appearance-close"))
        page.keyboard.press("Escape")
        expect(appearance).to_be_hidden()
        expect(page.locator("#workspace-view-menu-button")).to_be_focused()
    finally:
        page.set_viewport_size(viewport)
        page.wait_for_timeout(180)
    return {"surfaces": surfaces, "hover": states, "selected_hover": active, "keyboard_focus": focus,
            "floating": floating, "disabled_undo": check_disabled_commands(page, url)}


def run(dist: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "running", "cases": []}
    with serve(dist) as url, sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        for locale, theme, width in [("en", "dark", 1920), ("fa", "dark", 1920),
                                      ("en", "light", 1440), ("fa", "light", 1280),
                                      ("en", "dark", 1118), ("fa", "dark", 1118),
                                      ("en", "dark", 768), ("fa", "dark", 360)]:
            height = 852 if width == 1118 else 1000
            case = {"locale": locale, "theme": theme, "width": width, "height": height, "checks": []}
            report["cases"].append(case)
            page = browser.new_page(viewport={"width": width, "height": height})
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
                case["home_design_language"] = check_home_design_language(page)
                page.screenshot(path=str(output / f"{locale}-{width}-home.png"))
                case["checks"].append("Home retains the same 48px brand/engine header and a neutral primary action surface")
                case["checks"].append("New document helper uses the shared muted token; helper and title retain at least 4.5:1 contrast in base and real hover states")
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
                if width in {1118, 360}:
                    case["workspace_menu_reopen_geometry"] = []
                    for _ in range(3):
                        page.locator("#workspace-view-menu-button").click()
                        expect(page.locator("#workspace-view-menu")).to_be_visible()
                        case["workspace_menu_reopen_geometry"].append(check_workspace_menu_geometry(page))
                        page.keyboard.press("Escape")
                    case["checks"].append("workspace overflow follows its physical trigger in both layout directions and has no local horizontal scrollbar or escaped controls")
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
                    case["design_language"] = check_design_language(page, url)
                    case["checks"].append("Files/Inspector share one surface; neutral commands share hover, radius and density; selected hover and keyboard focus remain distinct")
                    case["checks"].append("body-portaled popovers, context menus and dialogs share their floating role; overflow commands retain contrast and read-only Undo stays dim without hover feedback")
                    for selector in ("#workspace-toggle-files", "#workspace-toggle-sidebar", "#workspace-toggle-preview"):
                        click_control(page, selector)
                    case["checks"].append("one to four pane toggles leave tabs and top keylines fixed")
                    for selector in ("#file-resizer", "#preview-resizer", "#sidebar-resizer"):
                        page.locator(selector).focus()
                        page.keyboard.press("End")
                    page.wait_for_timeout(120)
                    stress = page.locator(".document-toolbar").evaluate("e=>({width:e.clientWidth,scroll:e.scrollWidth,height:e.getBoundingClientRect().height})")
                    # Just above the drawer breakpoint the panel minima can
                    # consume one pixel of the preferred 320px editor budget.
                    minimum_editor = min(320, width - 208 - 340 - 248 - 3)
                    assert stress["width"] >= minimum_editor and stress["scroll"] <= stress["width"] + 1 and stress["height"] == 40, stress
                    assert page.locator(".tab-bar").bounding_box() == tabs_before
                    case["stress_geometry"] = stress
                    page.screenshot(path=str(output / f"{locale}-{width}-maximum-panes.png"))
                    case["checks"].append(f"maximum requested sidebar widths retain at least a {minimum_editor}px editor, fixed global tabs and one nonwrapping control row")
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

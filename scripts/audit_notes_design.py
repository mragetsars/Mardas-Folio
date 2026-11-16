#!/usr/bin/env python3
"""Review Geist theme roles, focus and surfaces in a real browser.

This is a visual acceptance aid, not a rendering-engine or native-shell test.
It reuses the editor UX audit's isolated native-transport fixture. No installed
application, personal profile or user document is opened. Screenshots and
computed colours make the design review reproducible without screenshot hashes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from playwright.sync_api import expect, sync_playwright

from audit_desktop_editor_ux import editor, initialise
from audit_desktop_ui import DEFAULT_DIST, click_workspace_layout_control, open_settings, select_settings_section, serve

ROOT = Path(__file__).resolve().parents[1]

COLOURS = """() => {
  const root = getComputedStyle(document.documentElement);
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d', {willReadFrequently:true});
  const rgb = token => {
    ctx.clearRect(0,0,1,1);
    ctx.fillStyle = root.getPropertyValue(token).trim();
    ctx.fillRect(0,0,1,1);
    return [...ctx.getImageData(0,0,1,1).data].slice(0,3);
  };
  const lin = value => {
    value /= 255;
    return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4;
  };
  const luminance = c => .2126*lin(c[0]) + .7152*lin(c[1]) + .0722*lin(c[2]);
  const pairs = [
    ['--ui-text','--ui-panel',4.5],
    ['--ui-text-soft','--ui-panel',4.5],
    ['--ui-muted','--ui-panel',4.5],
    ['--ui-selected-text','--ui-selected-bg',4.5],
    ['--ui-primary-text','--ui-primary-bg',4.5],
    ['--ui-primary-text','--ui-primary-hover',4.5],
    ['--cm-text','--ui-page',4.5],
    ['--ui-accent','--ui-panel',4.5],
    ['--ui-accent','--ui-selected-bg',3]
  ];
  return {
    roles:Object.fromEntries(['--ui-bg','--ui-panel','--ui-accent','--ui-danger','--ui-warning',
      '--ui-success','--ui-primary-bg','--ui-selected-bg','--ui-primary-text'].map(key => [key,root.getPropertyValue(key).trim()])),
    pairs:pairs.map(([foreground,background,minimum]) => {
      const a=luminance(rgb(foreground)), b=luminance(rgb(background));
      return {foreground,background,minimum,ratio:+((Math.max(a,b)+.05)/(Math.min(a,b)+.05)).toFixed(3)};
    })
  };
}"""


def _geometry(page: Any) -> dict[str, object]:
    return page.evaluate("""() => ({
      horizontalOverflow:document.documentElement.scrollWidth > innerWidth+1,
      verticalPageOverflow:document.documentElement.scrollHeight > innerHeight+1,
      direction:document.documentElement.dir,
      active:document.activeElement?.id,
    })""")


def run_audit(dist: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {"status": "running", "scope": __doc__, "scenarios": []}
    with serve(dist) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for locale in ("en", "fa"):
                for theme in ("light", "dark"):
                    for width in (360, 768, 1440, 1920):
                        prefix = f"{locale}-{theme}-{width}"
                        scenario: dict[str, Any] = {"locale": locale, "theme": theme, "width": width}
                        errors: list[str] = []
                        context = browser.new_context(viewport={"width": width, "height": 960})
                        page = context.new_page()
                        page.set_default_timeout(20_000)
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
                        try:
                            initialise(page, url, locale, theme, source=False)
                            expect(page.locator("html")).to_have_attribute("data-theme", theme, timeout=20_000)
                            expect(page.locator("html")).to_have_attribute("data-accent", "monochrome")
                            expect(page.locator("#workflow-new")).to_be_visible()
                            colours = page.evaluate(COLOURS)
                            ink = "#ffffff" if theme == "dark" else "#000000"
                            assert colours["roles"]["--ui-primary-bg"] == colours["roles"]["--ui-accent"] == ink, colours
                            assert all(pair["ratio"] >= pair["minimum"] for pair in colours["pairs"]), colours
                            accents = page.locator("#setting-accent option").evaluate_all("options => options.map(option => option.value)")
                            for accent in accents:
                                page.evaluate("(value) => { document.documentElement.dataset.accent = value; }", accent)
                                accent_colours = page.evaluate(COLOURS)
                                assert all(pair["ratio"] >= pair["minimum"] for pair in accent_colours["pairs"]), (accent, accent_colours)
                                for role in ("--ui-bg", "--ui-panel", "--ui-danger", "--ui-warning", "--ui-success"):
                                    assert accent_colours["roles"][role] == colours["roles"][role], (accent, role)
                            page.evaluate("() => { document.documentElement.dataset.accent = 'monochrome'; }")
                            scenario["colours"] = colours
                            page.screenshot(path=str(output / f"{prefix}-home.png"), full_page=True)
                            save = page.locator("#workspace-save")
                            expect(save).to_be_disabled()
                            style = "node => {const s=getComputedStyle(node); return [s.backgroundColor,s.borderColor,s.color]}"
                            page.mouse.move(1, 1)
                            before_hover = save.evaluate(style)
                            save.hover()
                            page.wait_for_timeout(160)
                            after_hover = save.evaluate(style)
                            assert after_hover == before_hover, ("disabled Save changed appearance on hover", before_hover, after_hover)

                            page.locator("#workflow-new").click()
                            expect(editor(page)).to_be_visible()
                            page.keyboard.insert_text("# Notes workspace\n\nمتن فارسی و English.\n")
                            expect(page.locator("#markdown-editor")).to_have_value("# Notes workspace\n\nمتن فارسی و English.\n")
                            # Keyboard modality must paint a visible ring on the selected activity.
                            page.keyboard.press("Tab")
                            selected = page.locator('button[data-view-mode="write"]')
                            selected.focus()
                            focus = selected.evaluate("""node => {
                              const style = getComputedStyle(node);
                              return {visible:node.matches(':focus-visible'),outline:style.outlineStyle,
                                width:parseFloat(style.outlineWidth),colour:style.outlineColor};
                            }""")
                            assert focus["visible"] and focus["outline"] != "none" and focus["width"] >= 2, focus
                            scenario["focus"] = focus
                            geometry = _geometry(page)
                            assert not geometry["horizontalOverflow"] and not geometry["verticalPageOverflow"], geometry
                            assert geometry["direction"] == ("rtl" if locale == "fa" else "ltr")
                            scenario["workspace"] = geometry
                            page.screenshot(path=str(output / f"{prefix}-workspace.png"), full_page=True)

                            open_settings(page)
                            expect(page.locator("#settings-modal")).to_be_visible()
                            expect(page.locator("#settings-appearance")).to_be_visible()
                            expect(page.locator("#settings-writing")).to_be_hidden()
                            placeholder = page.locator("#settings-search").evaluate("""input => {
                              const ctx = document.createElement('canvas').getContext('2d', {willReadFrequently:true});
                              const sample = colour => {ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = colour;
                                ctx.fillRect(0, 0, 1, 1); return [...ctx.getImageData(0, 0, 1, 1).data].slice(0, 3)};
                              const bg = sample(getComputedStyle(input).backgroundColor);
                              const fg = sample(getComputedStyle(input, '::placeholder').color);
                              const luminance = channels => channels.map(value => {
                                value /= 255; return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4;
                              }).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
                              const values = [luminance(bg), luminance(fg)].sort((a, b) => b - a);
                              return {bg, fg, ratio:(values[0] + .05) / (values[1] + .05)};
                            }""")
                            assert placeholder["ratio"] >= 4.5, placeholder
                            scenario["placeholder"] = placeholder
                            if width == 360:
                                page.set_viewport_size({"width": width, "height": 540})
                            modal = page.locator("#settings-form").bounding_box()
                            assert modal and modal["x"] >= -1 and modal["x"] + modal["width"] <= width + 1, modal
                            assert page.evaluate("Boolean(document.activeElement?.closest('#settings-modal'))")
                            settings_geometry = page.evaluate("""() => {
                              const content = document.querySelector('#settings-sections');
                              const footer = document.querySelector('.settings-footer');
                              return {
                                fits: content.scrollWidth <= content.clientWidth + 1,
                                footerPinned: content.getBoundingClientRect().bottom <= footer.getBoundingClientRect().top + 1,
                                footerVisible: footer.getBoundingClientRect().bottom <= innerHeight + 1,
                              };
                            }""")
                            assert all(settings_geometry.values()), settings_geometry
                            scenario["settings"] = settings_geometry
                            page.screenshot(path=str(output / f"{prefix}-settings.png"))

                            select_settings_section(page, "writing")
                            expect(page.locator("#settings-appearance")).to_be_hidden()
                            expect(page.locator("#setting-auto-preview")).to_be_checked()
                            switch = page.locator("#setting-auto-preview").evaluate("""input => {
                              const root = getComputedStyle(document.documentElement);
                              const ctx = document.createElement('canvas').getContext('2d');
                              const normalize = colour => {ctx.fillStyle=colour;return ctx.fillStyle;};
                              return {fill:normalize(root.getPropertyValue('--ui-primary-bg')),
                                track:normalize(getComputedStyle(input.nextElementSibling).backgroundColor),
                                ink:normalize(root.getPropertyValue('--ui-primary-text')),
                                thumb:normalize(getComputedStyle(input.nextElementSibling,'::after').backgroundColor)};
                            }""")
                            assert switch["fill"] == switch["track"] and switch["ink"] == switch["thumb"], switch
                            scenario["checked_switch"] = switch
                            if width == 1440:
                                search = page.locator("#settings-search")
                                search.fill("ماشين تحرير" if locale == "fa" else "typewriter")
                                expect(page.locator("#setting-typewriter")).to_be_visible()
                                expect(page.locator("#setting-auto-preview")).to_be_hidden()
                                search.fill("monochrome")
                                expect(page.locator("#setting-accent")).to_be_visible()
                                expect(page.locator("#setting-theme")).to_be_hidden()
                                search.press("Enter")
                                expect(page.locator("#settings-modal")).to_be_visible()
                                search.fill("no-matching-setting-47")
                                expect(page.locator("#settings-empty")).to_be_visible()
                                page.locator("#settings-clear-search").click()
                                expect(page.locator("#settings-writing")).to_be_visible()
                                expect(search).to_be_focused()
                                select_settings_section(page, "appearance")
                                picker = page.locator("#setting-accent")
                                submit = page.locator("#settings-form button[type='submit']")
                                zoom = page.locator("#setting-document-zoom")
                                zoom.fill("999")
                                select_settings_section(page, "writing")
                                submit.click()
                                expect(page.locator("#settings-modal")).to_be_visible()
                                expect(zoom).to_be_focused()
                                zoom.fill("100")
                                page.mouse.move(0, 0)
                                expect(picker).to_have_value("monochrome")
                                picker.select_option("blue")
                                expect(page.locator(".settings-accent-swatch")).to_have_css("background-color", "rgb(0, 110, 254)")
                                page.locator("#cancel-settings").click()
                                expect(page.locator("html")).to_have_attribute("data-accent", "monochrome")
                                open_settings(page)
                                expect(picker).to_have_value("monochrome")
                                picker.select_option("purple")
                                expect(page.locator(".settings-accent-swatch")).to_have_css("background-color", "rgb(126, 58, 184)")
                                select_settings_section(page, "writing")
                                select_settings_section(page, "appearance")
                                expect(picker).to_have_value("purple")
                                submit.click()
                                expect(page.locator("html")).to_have_attribute("data-accent", "purple")
                                saved = page.evaluate("JSON.parse(localStorage.getItem('mardas.desktop.preferences.v1')).accent")
                                assert saved == "purple", saved
                                open_settings(page)
                                expect(picker).to_have_value("purple")
                                expect(submit).to_have_css("background-color", "rgb(126, 58, 184)")
                                expect(submit).to_have_css("color", "rgb(255, 255, 255)")
                                picker.select_option("monochrome")
                                submit.click()
                                expect(page.locator("html")).to_have_attribute("data-accent", "monochrome")
                            else:
                                page.keyboard.press("Escape")
                            expect(page.locator("#settings-modal")).to_be_hidden()
                            if width == 1440:
                                click_workspace_layout_control(page, "#workspace-focus")
                                expect(page.locator("html")).to_have_attribute("data-focus-mode", "true")
                                page.keyboard.press("Control+Shift+P")
                                page.locator("#command-query").fill("preferences")
                                page.locator('[data-command-id="settings"]').click()
                                expect(page.locator("#settings-modal")).to_be_visible()
                                assert page.locator("#setting-focus-mode").count() == 0
                                page.locator("#settings-form button[type='submit']").click()
                                expect(page.locator("#settings-modal")).to_be_hidden()
                                expect(page.locator("html")).to_have_attribute("data-focus-mode", "true")
                                page.keyboard.press("Escape")
                                expect(page.locator("html")).to_have_attribute("data-focus-mode", "false")
                            assert not errors, errors
                            scenario["status"] = "passed"
                        except Exception as error:  # noqa: BLE001 - preserve each visual case's evidence
                            scenario.update(status="failed", error=str(error))
                            page.screenshot(path=str(output / f"{prefix}-failure.png"), full_page=True)
                        finally:
                            scenario["page_errors"] = errors
                            report["scenarios"].append(scenario)
                            context.close()
        finally:
            browser.close()
    report["status"] = "passed" if all(item["status"] == "passed" for item in report["scenarios"]) else "failed"
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--out", type=Path, default=ROOT / "build/notes-design")
    args = parser.parse_args()
    result = run_audit(args.dist.resolve(), args.out.resolve())
    print(json.dumps({"status": result["status"], "scenarios": [
        {key: value for key, value in scenario.items() if key not in {"colours"}}
        for scenario in result["scenarios"]]}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "passed" else 1)

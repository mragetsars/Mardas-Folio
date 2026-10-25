#!/usr/bin/env python3
"""Review Notes-inspired theme roles, focus and surfaces in a real browser.

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
from audit_desktop_ui import DEFAULT_DIST, open_settings, serve

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
    ['--ui-accent','--ui-accent-soft',4.5],
    ['--ui-on-accent','--ui-accent-fill',4.5],
    ['--cm-text','--ui-page',4.5],
    ['--ui-accent','--ui-panel',3]
  ];
  return {
    roles:Object.fromEntries(['--ui-bg','--ui-panel','--ui-accent',
      '--ui-accent-fill','--ui-accent-soft','--ui-on-accent'].map(key => [key,root.getPropertyValue(key).trim()])),
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
                            expect(page.locator("#workflow-new")).to_be_visible()
                            colours = page.evaluate(COLOURS)
                            assert colours["roles"]["--ui-accent-fill"], "Primary fill role is missing"
                            assert all(pair["ratio"] >= pair["minimum"] for pair in colours["pairs"]), colours
                            scenario["colours"] = colours
                            page.screenshot(path=str(output / f"{prefix}-home.png"), full_page=True)

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
                            expect(page.locator("#setting-auto-preview")).to_be_checked()
                            switch = page.locator("#setting-auto-preview").evaluate("""input => {
                              const root = getComputedStyle(document.documentElement);
                              const ctx = document.createElement('canvas').getContext('2d');
                              const normalize = colour => {ctx.fillStyle=colour;return ctx.fillStyle;};
                              return {fill:normalize(root.getPropertyValue('--ui-accent-fill')),
                                track:normalize(getComputedStyle(input.nextElementSibling).backgroundColor),
                                ink:normalize(root.getPropertyValue('--ui-on-accent')),
                                thumb:normalize(getComputedStyle(input.nextElementSibling,'::after').backgroundColor)};
                            }""")
                            assert switch["fill"] == switch["track"] and switch["ink"] == switch["thumb"], switch
                            scenario["checked_switch"] = switch
                            modal = page.locator("#settings-form").bounding_box()
                            assert modal and modal["x"] >= -1 and modal["x"] + modal["width"] <= width + 1, modal
                            assert page.evaluate("Boolean(document.activeElement?.closest('#settings-modal'))")
                            page.screenshot(path=str(output / f"{prefix}-settings.png"), full_page=True)
                            page.keyboard.press("Escape")
                            expect(page.locator("#settings-modal")).to_be_hidden()
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

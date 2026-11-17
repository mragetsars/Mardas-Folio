#!/usr/bin/env python3
"""Exercise sidebar keylines, metadata scrolling, mixed-direction outline and path disclosure."""

from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from lib.audit.desktop import DEFAULT_DIST, click_workspace_layout_control, serve
from lib.audit.editor import FIXTURE_A, initialise, replace_content

SAMPLE = (
    "# سند آزمایشی پنل‌ها\n\nمتن فارسی برای آزمودن مشخصات سند.\n\n"
    "## AdaptiveCruiseTest — کروز تطبیقی با عنوان طولانی برای مرور راحت‌تر\n\nBody.\n\n"
    "### BrakeController — کنترل ترمز\n\nFinal paragraph.\n"
)


def run(dist: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "running", "scenarios": []}
    with serve(dist) as url, sync_playwright() as runtime:
        browser = runtime.chromium.launch()
        for locale, theme, width, height in [
            ("en", "dark", 1920, 1080),
            ("fa", "dark", 1920, 1080),
            ("en", "light", 1366, 600),
            ("fa", "light", 1366, 600),
        ]:
            case = {
                "locale": locale,
                "theme": theme,
                "width": width,
                "height": height,
                "checks": [],
            }
            report["scenarios"].append(case)
            page = browser.new_page(viewport={"width": width, "height": height})
            page.set_default_timeout(10000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            try:
                initialise(page, url, locale, theme, source=False)
                page.locator("#workflow-open").click()
                replace_content(page, SAMPLE)
                if (
                    page.locator("#workspace-toggle-sidebar").get_attribute("aria-pressed")
                    != "true"
                ):
                    click_workspace_layout_control(page, "#workspace-toggle-sidebar")
                if (
                    page.locator("#workspace-toggle-preview").get_attribute("aria-pressed")
                    != "true"
                ):
                    click_workspace_layout_control(page, "#workspace-toggle-preview")
                expect(page.locator("#file-navigator")).to_be_visible()
                expect(page.locator(".preview-pane")).to_be_visible()
                page.locator("#sidebar-tab-project").click()
                expect(page.locator("#project-empty")).to_be_visible()
                expect(page.locator("#refresh-project")).to_be_hidden()
                expect(page.locator("#sidebar-open-project")).to_be_visible()
                assert (
                    page.locator("#project-search-results").get_attribute("aria-live") == "polite"
                )
                case["checks"].append(
                    "project empty state offers one correctly labelled action and search updates are announced"
                )
                page.locator("#sidebar-tab-frontmatter").click()
                expect(page.locator("#sidebar-panel-frontmatter")).to_be_visible()
                page.locator("#sidebar-resizer").focus()
                page.keyboard.press("Home")
                expect(page.locator("#sidebar-resizer")).to_have_attribute("aria-valuenow", "248")
                geometry = page.evaluate("""() => {
                  const box = s => {const r=document.querySelector(s).getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,height:r.height,width:r.width}};
                  const form = document.querySelector('#frontmatter-form');
                  const tabs = ['#navigator-tab-files','#sidebar-tab-frontmatter'].map(s=>{
                    const e=document.querySelector(s), c=getComputedStyle(e);return {radius:c.borderRadius,background:c.backgroundColor,height:e.getBoundingClientRect().height};
                  });
                  return {nav:box('.navigator-heading'),inspector:box('.inspector-heading'),editor:box('.document-toolbar'),
                    panel:box('#sidebar-panel-frontmatter'),form:box('#frontmatter-form'),body:box('.property-grid-body'),footer:box('.property-grid-footer'),
                    overflow:form.scrollWidth>form.clientWidth+1,tabs};
                }""")
                case["geometry"] = geometry
                assert (
                    max(geometry[name]["top"] for name in ("nav", "inspector", "editor"))
                    - min(geometry[name]["top"] for name in ("nav", "inspector", "editor"))
                    <= 1
                ), geometry
                assert all(
                    geometry[name]["height"] == 40 for name in ("nav", "inspector", "editor")
                ), geometry
                assert geometry["tabs"][0] == geometry["tabs"][1], geometry["tabs"]
                assert geometry["footer"]["bottom"] <= geometry["panel"]["bottom"] + 1, geometry
                assert geometry["footer"]["top"] >= geometry["body"]["bottom"] - 1, geometry
                assert not geometry["overflow"], geometry
                case["checks"].append(
                    "all four panes stay open with navigation, editor and inspector on one 40px keyline; text and icon tabs share identical selected geometry and paint"
                )

                footer = page.locator(".property-grid-footer")
                before_footer = footer.bounding_box()
                page.locator(".property-grid-body").evaluate("e=>e.scrollTop=e.scrollHeight")
                assert footer.bounding_box() == before_footer
                expect(footer.locator("button")).to_be_visible()
                page.locator('#frontmatter-form input[name="title"]').fill(
                    "عنوان آزمایشی — Inspector"
                )
                page.locator('#frontmatter-form input[name="subtitle"]').fill(
                    "Mixed فارسی / English"
                )
                expect(page.locator("#markdown-editor")).to_have_value(SAMPLE)
                footer.locator("button").click()
                updated = page.locator("#markdown-editor").input_value()
                assert "عنوان آزمایشی — Inspector" in updated and SAMPLE in updated, updated
                page.locator(".cm-content").focus()
                page.keyboard.press("Control+z")
                expect(page.locator("#markdown-editor")).to_have_value(SAMPLE)
                case["checks"].append(
                    "metadata footer stays anchored while fields scroll; form drafts do not edit Markdown until Apply; physical Undo restores exact original source"
                )

                if page.locator("#workspace-toggle-files").get_attribute("aria-pressed") != "true":
                    click_workspace_layout_control(page, "#workspace-toggle-files")
                page.locator("#navigator-tab-outline").click()
                expect(page.locator(".outline-heading")).to_have_count(3)
                outline = page.locator(".outline-row").evaluate_all("""rows=>rows.map(row=>{
                  const button=row.querySelector('.outline-heading'),title=row.querySelector('.outline-heading-title');
                  const b=button.getBoundingClientRect(),t=title.getBoundingClientRect(),c=getComputedStyle(title);
                  return {depth:Number(row.style.getPropertyValue('--outline-depth')),height:b.height,left:b.left,right:b.right,
                    titleHeight:t.height,lineHeight:parseFloat(c.lineHeight),direction:c.direction,whiteSpace:c.whiteSpace,bidi:c.unicodeBidi};
                })""")
                assert [row["depth"] for row in outline] == [0, 1, 2], outline
                assert all(
                    row["height"] >= 34 and row["titleHeight"] <= row["lineHeight"] * 2 + 1
                    for row in outline
                ), outline
                assert all(
                    row["whiteSpace"] == "normal" and row["bidi"] == "isolate" for row in outline
                ), outline
                edge = "right" if locale == "fa" else "left"
                delta = outline[1][edge] - outline[0][edge]
                assert abs(abs(delta) - 12) <= 1, outline
                case["outline"] = outline
                case["checks"].append(
                    "mixed Persian/English headings keep logical 12px indentation, stable disclosure columns and a two-line reading rhythm"
                )

                page.locator("#navigator-tab-files").click()
                first_path = page.locator("#open-document-list .navigator-document").first
                assert first_path.locator("small").inner_text() == "fixtures / alpha"
                assert FIXTURE_A in first_path.get_attribute("title")
                assert (
                    not page.locator(".navigator-footer").get_by_text("Ctrl P", exact=True).count()
                )
                expect(page.locator("#markdown-editor")).to_have_value(SAMPLE)
                assert not errors, errors
                case["checks"].append(
                    "open files disclose compact distinguishing parent folders with full original paths in tooltips and no duplicate Quick Open trigger"
                )
                page.screenshot(path=str(output / f"{locale}-{theme}-{width}.png"))
                case["status"] = "passed"
            except Exception as error:
                case["status"] = "failed"
                case["error"] = (str(error) or traceback.format_exc(limit=2))[:2600]
                page.screenshot(path=str(output / f"{locale}-{theme}-{width}-failure.png"))
            finally:
                case["page_errors"] = errors
                page.close()
        browser.close()
    report["status"] = (
        "passed" if all(case["status"] == "passed" for case in report["scenarios"]) else "failed"
    )
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--output", type=Path, default=Path("build/design-system/property-panels"))
    args = parser.parse_args()
    result = run(args.dist.resolve(), args.output.resolve())
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(result["status"] != "passed")

#!/usr/bin/env python3
"""Exercise long-form authoring against the real editor and rendering engine.

The bridge replaces only native file pickers and transport. Markdown is read
and rendered by EngineService from exclusive temporary files. No installed
Office Viewer/Mardas profile or personal document is used.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import time
from typing import Any

from playwright.sync_api import expect, sync_playwright

from audit_book_workflow import engine_server
from audit_desktop_ui import DEFAULT_DIST, ROOT


SAMPLE = (
    "AUTHORING_SELECTION_WORD\n\n# Long-form writing / نوشتن طولانی\n\nEnergy is $E=mc^2$.\n\n"
    + "\n\n".join(
        f"## Chapter {chapter} / فصل {chapter}\n\n"
        + "\n\n".join(
            f"Paragraph {paragraph}. متن فارسی برای نوشتن و مطالعهٔ طولانی. "
            + "English and فارسی stay in the same Markdown document. " * 30
            for paragraph in range(1, 16)
        )
        + f"\n\n### Detail {chapter} / جزئیات\n\nA final paragraph.\n"
        for chapter in range(1, 13)
    )
    + "\n\nFINAL_WRITING_MARKER\n"
)

BRIDGE = r"""
globalThis.__TAURI__ = {
  core: {invoke: async (command, args = {}) => {
    if (command === 'take_launch_files') return [];
    if (command === 'pick_markdown_files') return [globalThis.__writingFixture.pick];
    if (command === 'updater_status') return {configured:false};
    if (command === 'sidecar_cancel') return {cancel_requested:false};
    if (command !== 'sidecar_request') return null;
    const response = await fetch('/__engine', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({method:args.method,params:args.params})});
    const payload = await response.json();
    if (payload.error) throw JSON.stringify(payload.error);
    return payload.result;
  }}, event:{listen:async () => () => {}}
};
Object.freeze(Object.prototype);
"""


def _buffer(page: Any) -> Any:
    return page.locator("#markdown-editor")


def _editor(page: Any) -> Any:
    return page.locator(".codemirror-mount .cm-content")


def _visible_command(page: Any, command: str) -> Any:
    return page.locator(f'[data-editor-command="{command}"]:visible').first


def _geometry(page: Any) -> dict[str, Any]:
    return page.evaluate("""() => {
      const root = document.querySelector('.editor-surface').getBoundingClientRect();
      const body = document.querySelector('.cm-scroller').getBoundingClientRect();
      const lines = document.querySelectorAll('.cm-line');
      return {horizontalOverflow:document.documentElement.scrollWidth>innerWidth+1,
        canvasShare:+((root.width*root.height)/(innerWidth*innerHeight)).toFixed(3),
        viewportLineNodes:lines.length,editorWidth:Math.round(body.width),
        lineHeight:getComputedStyle(document.querySelector('.cm-content')).lineHeight};
    }""")


def _rhythm(page: Any) -> dict[str, Any]:
    return page.locator(".cm-line").first.evaluate("""node => {
      const style=getComputedStyle(node);
      return {fontFamily:style.fontFamily,fontSize:parseFloat(style.fontSize),
        lineHeight:parseFloat(style.lineHeight),
        ratio:parseFloat(style.lineHeight)/parseFloat(style.fontSize)};
    }""")


def _appearance(page: Any, width: int) -> dict[str, Any]:
    trigger = page.locator("#writing-appearance-button")
    trigger.click()
    dialog = page.locator("#writing-appearance")
    expect(dialog).to_be_visible()
    box = dialog.bounding_box()
    assert box and box["x"] >= -1 and box["x"] + box["width"] <= width + 1, box
    page.locator("#writing-font").select_option("serif")
    page.locator("#writing-density").select_option("compact")
    compact = _rhythm(page)
    page.locator("#writing-density").select_option("relaxed")
    relaxed = _rhythm(page)
    assert relaxed["ratio"] > compact["ratio"] + 0.1, (compact, relaxed)
    page.locator("#writing-density").select_option("compact")
    zoom = page.locator("#writing-zoom")
    zoom.focus()
    page.keyboard.press("Home")
    for _ in range(6):
        page.keyboard.press("ArrowUp")
    expect(zoom).to_have_value("120")
    expect(page.locator("html")).to_have_attribute("data-document-zoom", "120")
    preferences = page.evaluate("JSON.parse(localStorage.getItem('mardas.desktop.preferences.v1'))")
    assert preferences["writingFont"] == "serif", preferences
    assert preferences["writingDensity"] == "compact", preferences
    assert preferences["documentZoom"] == 120, preferences
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(trigger).to_be_focused()
    return {"compact": compact, "relaxed": relaxed, "preferences": preferences}


def _outline(page: Any) -> dict[str, Any]:
    page.locator("#workspace-writing-layout").click()
    expect(page.locator("#preview-pane")).to_be_hidden()
    expect(page.locator("#navigator-tab-outline")).to_have_attribute("aria-selected", "true")
    expect(page.locator("#outline-filter")).to_be_visible()
    follow = page.locator("#outline-follow").bounding_box()
    assert follow and follow["width"] <= 24 and follow["height"] <= 24, (
        "Outline follow checkbox must not inherit full-width form-field sizing"
    )
    heading = page.locator("#outline-list .outline-heading")
    expect(heading).to_have_count(25)
    expect(page.locator("#outline-list .level")).to_have_count(0)
    page.locator("#outline-collapse-all").click()
    expect(heading).to_have_count(1)
    page.locator("#outline-expand-all").click()
    expect(heading).to_have_count(25)
    page.locator("#outline-filter").fill("Chapter 8")
    expect(heading).to_have_count(2)
    heading.filter(has_text="Chapter 8").click()
    expect(_buffer(page)).to_have_value(SAMPLE)
    expect(page.locator("#outline-list [aria-current='location']")).to_contain_text("Chapter 8")
    expect(_editor(page)).to_be_focused()
    page.locator("#outline-filter").fill("")
    expect(heading).to_have_count(25)
    # A user browsing the structure can collapse with arrow keys and keep the
    # caret stationary; Enter performs the explicit document navigation.
    root = heading.first
    root.focus()
    collapse = "ArrowRight" if page.locator("html").get_attribute("dir") == "rtl" else "ArrowLeft"
    page.keyboard.press(collapse)
    expect(heading).to_have_count(1)
    expect(root).to_have_attribute("aria-expanded", "false")
    page.keyboard.press("ArrowLeft" if collapse == "ArrowRight" else "ArrowRight")
    expect(heading).to_have_count(25)
    before = _buffer(page).input_value()
    page.locator("#outline-follow").check()
    # Respect the pause after manual outline browsing, then verify that a
    # caret move reveals the current section instead of merely marking it.
    page.wait_for_timeout(3100)
    _editor(page).focus()
    page.keyboard.press("Control+End")
    expect(page.locator("#outline-list [aria-current='location']")).to_contain_text("Detail 12")
    page.wait_for_function("""() => {
      const item=document.querySelector('#outline-list [aria-current="location"]');
      const frame=document.querySelector('#file-navigator').getBoundingClientRect();
      if (!item) return false;
      const box=item.getBoundingClientRect();
      if (box.top<frame.top || box.bottom>frame.bottom) return false;
      const hit=document.elementFromPoint((box.left+box.right)/2,(box.top+box.bottom)/2);
      return hit===item || item.contains(hit);
    }""")
    assert _buffer(page).input_value() == before
    return {
        "headings": 25,
        "filter_matches_with_ancestor": 2,
        "keyboard_collapsing": True,
        "follow": True,
    }


def run_audit(dist: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    (output / "fixture.md").write_text(SAMPLE, encoding="utf-8")
    report: dict[str, Any] = {"status": "running", "scope": __doc__, "scenarios": []}
    with tempfile.TemporaryDirectory(prefix="writing-fixture-", dir=output) as directory:
        source = Path(directory) / "long-writing.md"
        source.write_text(SAMPLE, encoding="utf-8")
        with engine_server(dist) as (url, calls), sync_playwright() as runtime:
            browser = runtime.chromium.launch(headless=True)
            for locale, theme, width in (
                ("en", "light", 1440),
                ("fa", "dark", 1440),
                ("fa", "light", 768),
                ("en", "dark", 360),
            ):
                scenario: dict[str, Any] = {
                    "locale": locale,
                    "theme": theme,
                    "width": width,
                    "checks": [],
                }
                errors: list[str] = []
                context = browser.new_context(viewport={"width": width, "height": 960})
                context.add_init_script(
                    "globalThis.__writingFixture=" + json.dumps({"pick": str(source)}) + ";"
                    f"localStorage.setItem('mardas.desktop.locale',{json.dumps(locale)});"
                    "if(!localStorage.getItem('mardas.desktop.preferences.v1')) localStorage.setItem('mardas.desktop.preferences.v1',JSON.stringify("
                    + json.dumps({"theme": theme, "onboardingComplete": True})
                    + "));"
                    + BRIDGE
                )
                page = context.new_page()
                page.set_default_timeout(20_000)
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        errors.append(message.text) if message.type == "error" else None
                    ),
                )
                started = time.monotonic()
                preview_baseline = sum(call["method"] == "preview.document_text" for call in calls)
                try:
                    page.goto(url, wait_until="networkidle")
                    page.locator("#workflow-open").click()
                    expect(_buffer(page)).to_have_value(SAMPLE, timeout=30_000)
                    expect(page.locator("#workspace-view")).to_have_attribute(
                        "data-view-mode", "write"
                    )
                    expect(page.locator("#preview-pane")).to_be_hidden()
                    expect(_editor(page)).to_be_visible()
                    expect(
                        page.locator(".cm-md-math-preview mjx-container svg").first
                    ).to_be_visible(timeout=30_000)
                    scenario["ready_seconds"] = round(time.monotonic() - started, 3)
                    scenario["checks"].append(
                        "default writing opens one editable canvas without duplicated preview"
                    )
                    scenario["checks"].append(
                        "inactive inline mathematics renders in the actual writing canvas"
                    )

                    if width >= 768:
                        expect(_visible_command(page, "bold")).to_be_visible()
                    _editor(page).focus()
                    page.keyboard.press("Control+Home")
                    page.keyboard.press("Shift+End")
                    scenario["appearance"] = _appearance(page, width)
                    expect(_buffer(page)).to_have_value(SAMPLE)
                    scenario["checks"].append(
                        "font density and zoom are discoverable view-only preferences with keyboard dismissal"
                    )

                    if width < 768:
                        more = page.locator("#format-overflow-button")
                        expect(more).to_be_visible()
                        more.focus()
                        page.keyboard.press("Enter")
                        expect(page.locator("#format-overflow-menu")).to_be_visible()
                        menu = page.locator("#format-overflow-menu").bounding_box()
                        assert (
                            menu and menu["x"] >= -1 and menu["x"] + menu["width"] <= width + 1
                        ), menu
                        page.keyboard.press("Escape")
                        expect(page.locator("#format-overflow-menu")).to_be_hidden()
                        expect(more).to_be_focused()
                        scenario["checks"].append(
                            "narrow writing tools remain discoverable in a keyboard-operable overflow menu"
                        )

                    if width >= 768:
                        bold = _visible_command(page, "bold")
                        expect(bold).to_be_visible()
                        _editor(page).focus()
                        bold.click()
                        expect(_buffer(page)).to_have_value(
                            SAMPLE.replace(
                                "AUTHORING_SELECTION_WORD", "**AUTHORING_SELECTION_WORD**", 1
                            )
                        )
                        expect(bold).to_have_attribute("aria-pressed", "true")
                        _editor(page).focus()
                        page.keyboard.press("Control+z")
                        expect(_buffer(page)).to_have_value(SAMPLE)
                        scenario["checks"].append(
                            "direct formatting preserves the selected text and actual Undo restores exact Markdown"
                        )

                    if width >= 768:
                        scenario["outline"] = _outline(page)
                        scenario["checks"].append(
                            "hierarchical outline filters collapses follows and navigates without changing Markdown"
                        )

                    # Blank paragraph separators remain part of the editable
                    # document even when their visual height is reduced.
                    _editor(page).focus()
                    page.keyboard.press("Control+Home")
                    page.keyboard.press("ArrowDown")
                    page.keyboard.insert_text("EMPTY_PARAGRAPH_CARET_TOKEN")
                    expect(_buffer(page)).to_have_value(
                        SAMPLE.replace("\n\n#", "\nEMPTY_PARAGRAPH_CARET_TOKEN\n#", 1)
                    )
                    page.keyboard.press("Control+z")
                    expect(_buffer(page)).to_have_value(SAMPLE)
                    page.keyboard.press("Control+Home")
                    page.keyboard.press("ArrowDown")
                    page.keyboard.press("ArrowDown")
                    page.keyboard.press("ArrowUp")
                    page.keyboard.insert_text("EMPTY_LINE_UP_TOKEN")
                    expect(_buffer(page)).to_have_value(
                        SAMPLE.replace("\n\n#", "\nEMPTY_LINE_UP_TOKEN\n#", 1)
                    )
                    page.keyboard.press("Control+z")
                    expect(_buffer(page)).to_have_value(SAMPLE)
                    page.keyboard.press("Control+End")
                    page.keyboard.press("Enter")
                    page.keyboard.press("Enter")
                    page.keyboard.insert_text("BLANK_LINE_CARET_TOKEN")
                    expect(_buffer(page)).to_have_value(SAMPLE + "\n\nBLANK_LINE_CARET_TOKEN")
                    # Separate key events may create more than one history
                    # group. Walk back only the operations we just performed.
                    for _ in range(4):
                        if _buffer(page).input_value() == SAMPLE:
                            break
                        page.keyboard.press("Control+z")
                    expect(_buffer(page)).to_have_value(SAMPLE)
                    scenario["checks"].append(
                        "blank lines remain editable and do not compromise undo or document bytes"
                    )

                    page.wait_for_timeout(700)
                    assert (
                        sum(call["method"] == "preview.document_text" for call in calls)
                        == preview_baseline
                    )
                    scenario["checks"].append(
                        "writing with no content preview performs no speculative engine renders"
                    )
                    _editor(page).focus()
                    page.keyboard.press("Control+Home")
                    page.keyboard.press("ArrowDown")
                    page.keyboard.press("ArrowDown")
                    geometry = _geometry(page)
                    assert not geometry["horizontalOverflow"], geometry
                    assert geometry["viewportLineNodes"] < 200, geometry
                    scenario["geometry"] = geometry
                    page.screenshot(path=str(output / f"{locale}-{theme}-{width}.png"))
                    assert source.read_text(encoding="utf-8") == SAMPLE, (
                        "View interactions changed the on-disk document"
                    )
                    page.reload(wait_until="networkidle")
                    expect(page.locator("html")).to_have_attribute(
                        "data-document-zoom", "120", timeout=30_000
                    )
                    expect(page.locator("html")).to_have_attribute(
                        "data-writing-density", "compact"
                    )
                    expect(page.locator("#writing-font")).to_have_value("serif")
                    if page.locator("#workflow-open").is_visible():
                        page.locator("#workflow-open").click()
                    expect(_buffer(page)).to_have_value(SAMPLE, timeout=30_000)
                    scenario["checks"].append(
                        "appearance choices survive reload without rewriting or losing the document"
                    )
                    assert not errors, errors
                    scenario["status"] = "passed"
                except Exception as error:
                    scenario["status"] = "failed"
                    message = str(error)
                    actual_start = message.find("Actual value:")
                    if len(message) > 5000:
                        excerpt = (
                            message[actual_start : actual_start + 2000]
                            if actual_start >= 0
                            else message[-1500:]
                        )
                        message = message[:2000] + "\n[assertion text truncated]\n" + excerpt
                    scenario["error"] = message
                    if _buffer(page).count():
                        actual_file = output / f"{locale}-{theme}-{width}-actual.md"
                        actual_file.write_text(_buffer(page).input_value(), encoding="utf-8")
                        scenario["actual_buffer"] = actual_file.name
                    page.screenshot(path=str(output / f"{locale}-{theme}-{width}-failure.png"))
                finally:
                    scenario["page_errors"] = errors
                    report["scenarios"].append(scenario)
                    context.close()
            browser.close()
    report["status"] = (
        "passed" if all(item["status"] == "passed" for item in report["scenarios"]) else "failed"
    )
    (output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--out", type=Path, default=ROOT / "build/authoring-workspace")
    arguments = parser.parse_args()
    result = run_audit(arguments.dist.resolve(), arguments.out.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

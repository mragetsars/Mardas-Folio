#!/usr/bin/env python3
"""Verify raw Markdown block direction and real source caret movement.

Run after building the desktop frontend. The browser bridge supplies predictable
preview HTML; these checks exercise CodeMirror rather than the rendering engine.

    python scripts/audit_editor_source_direction.py --output build/source-direction
"""

from __future__ import annotations
import argparse
import json
from pathlib import Path

from audit_desktop_editor_ux import initialise, replace_content, mode
from audit_desktop_ui import DEFAULT_DIST, serve
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]

FIXTURE = "\n".join(
    [
        "# English source",
        "",
        "English prose keeps its Latin direction.",
        "نثر فارسی جهت راست به چپ خود را نگه می‌دارد.",
        "",
        "```javascript",
        "// توضیح فارسی برای کد",
        "const count = 1;",
        "",
        "```",
        "",
        "| Name | Count |",
        "| --- | ---: |",
        "| 1 | 2 |",
        "",
        "| نام | تعداد |",
        "| --- | ---: |",
        "| ۱ | ۲ |",
        "",
        "```text",
        "متن فارسی در بلوک کد",
        "```",
        "",
        "Tail marker.",
    ]
)
DEFAULT_OUTPUT = ROOT / "build" / "editor-source-direction"

READ_CARET = """() => {
  const selection = getSelection();
  const lines = [...document.querySelectorAll('.cm-line')];
  const raw = document.querySelector('#markdown-editor').value.split('\\n');
  const offset = (node, at) => {
    const line = (node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement).closest('.cm-line');
    const number = lines.indexOf(line);
    const range = document.createRange();
    range.selectNodeContents(line);
    range.setEnd(node, at);
    return raw.slice(0, number).reduce((total, text) => total + text.length + 1, 0) + range.toString().length;
  };
  const cursor = document.querySelector('.cm-cursor').getBoundingClientRect();
  return {anchor:offset(selection.anchorNode, selection.anchorOffset),
    head:offset(selection.focusNode, selection.focusOffset), x:cursor.left, y:cursor.top};
}"""


def run(dist: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    records = []
    with serve(dist) as url, sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for locale in ("en", "fa"):
            for theme in ("light", "dark"):
                context = browser.new_context(viewport={"width": 1440, "height": 1500})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "console",
                    lambda message: (
                        errors.append(message.text) if message.type == "error" else None
                    ),
                )
                initialise(page, url, locale, theme)
                page.locator("[data-template-id='blank']").click()
                replace_content(page, FIXTURE)
                page.locator(".cm-content").click()
                page.keyboard.press("Control+End")
                page.wait_for_timeout(300)
                page.keyboard.insert_text(" EDIT_MARKER")
                edited = FIXTURE + " EDIT_MARKER"
                expect(page.locator("#markdown-editor")).to_have_value(edited)
                cursor = page.locator("#cursor-status").inner_text()

                for view_mode in ("source", "split", "source"):
                    mode(page, view_mode)
                    page.wait_for_timeout(350)
                    expect(page.locator("#markdown-editor")).to_have_value(edited)
                    if page.locator("#cursor-status").inner_text() != cursor:
                        raise AssertionError("Changing Source/Split altered the exact caret status")
                    metrics = page.evaluate("""() => [...document.querySelectorAll('.cm-line')].map(line => ({
                      text:line.textContent, direction:getComputedStyle(line).direction,
                      isolation:getComputedStyle(line).unicodeBidi,
                      block:line.className.includes('cm-source-block-')
                    }))""")
                    if len(metrics) != len(edited.split("\n")):
                        raise AssertionError(f"Fixture not fully visible: {len(metrics)} lines")
                    for index in (5, 6, 7, 8, 9, 11, 12, 13, 19, 20, 21):
                        if metrics[index]["direction"] != "ltr" or not metrics[index]["block"]:
                            raise AssertionError(
                                f"LTR block direction at {index + 1}: {metrics[index]}"
                            )
                        if metrics[index]["isolation"] != "isolate":
                            raise AssertionError(
                                f"Block bidi isolation at {index + 1}: {metrics[index]}"
                            )
                    for index in (15, 16, 17):
                        if metrics[index]["direction"] != "rtl" or not metrics[index]["block"]:
                            raise AssertionError(
                                f"Persian table direction at {index + 1}: {metrics[index]}"
                            )
                    if metrics[2]["direction"] != "ltr" or metrics[3]["direction"] != "rtl":
                        raise AssertionError("Ordinary mixed prose stopped resolving per line")
                    if page.locator(
                        ".cm-md-table, .cm-md-frontmatter, .cm-md-rule, .cm-md-bullet, .cm-md-task"
                    ).count():
                        raise AssertionError("Raw source contains live widgets")
                    page.screenshot(path=str(output / f"{locale}-{theme}-{view_mode}.png"))
                    records.append(
                        {
                            "locale": locale,
                            "theme": theme,
                            "mode": view_mode,
                            "raw_buffer": True,
                            "caret": cursor,
                            "line_directions": metrics,
                        }
                    )

                # Browser selection offsets are mapped back onto the exact source
                # mirrored in the textarea; the painted caret must move in the
                # direction its source line advertises, even in the Persian UI.
                for view_mode in ("source", "split"):
                    mode(page, view_mode)
                    for line_number in (8, 10):
                        page.locator(".cm-line").nth(line_number - 1).click()
                        page.keyboard.press("Home")
                        page.wait_for_timeout(60)
                        home = page.evaluate(READ_CARET)
                        wanted = page.evaluate(
                            """number => document.querySelector('#markdown-editor').value
                          .split('\\n').slice(0, number - 1).reduce((total, text) => total + text.length + 1, 0)""",
                            line_number,
                        )
                        if home["head"] != wanted or home["anchor"] != wanted:
                            raise AssertionError(
                                f"Home source offset mismatch: {locale}/{view_mode}/{line_number}: {home}"
                            )
                        page.keyboard.press("ArrowRight")
                        page.wait_for_timeout(60)
                        right = page.evaluate(READ_CARET)
                        if (
                            right["head"] != wanted + 1
                            or right["anchor"] != wanted + 1
                            or right["x"] <= home["x"]
                        ):
                            raise AssertionError(
                                f"Right source/caret geometry mismatch: {locale}/{view_mode}/{line_number}: {home}, {right}"
                            )
                        page.keyboard.press("ArrowLeft")
                        page.wait_for_timeout(60)
                        left = page.evaluate(READ_CARET)
                        if (
                            left["head"] != wanted
                            or left["anchor"] != wanted
                            or abs(left["x"] - home["x"]) > 1
                        ):
                            raise AssertionError(
                                f"Left source/caret geometry mismatch: {locale}/{view_mode}/{line_number}: {home}, {left}"
                            )
                        expect(page.locator("#markdown-editor")).to_have_value(edited)
                        records.append(
                            {
                                "locale": locale,
                                "theme": theme,
                                "mode": view_mode,
                                "caret_line": line_number,
                                "home": home,
                                "right": right,
                                "left": left,
                            }
                        )

                page.locator(".cm-content").click()
                page.keyboard.press("Control+z")
                expect(page.locator("#markdown-editor")).to_have_value(FIXTURE)
                page.keyboard.press("Control+Shift+Z")
                expect(page.locator("#markdown-editor")).to_have_value(edited)
                if errors:
                    raise AssertionError(errors)
                context.close()
        browser.close()

    return {"cases": records, "history": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run(args.dist.resolve(strict=True), args.output.resolve())
    (args.output / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"PASS {len(report['cases'])} actual CodeMirror Source/Split direction cases, "
        "exact buffer/caret and per-mode undo/redo."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

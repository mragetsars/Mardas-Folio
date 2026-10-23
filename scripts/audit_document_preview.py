#!/usr/bin/env python3
"""Exercise desktop preview math with real Python-rendered Markdown payloads.

The browser uses the actual built frontend, offline MathJax asset and Python
preview body/page output. Only the native transport, file chooser and delivery
timing are fixtures. No installed app or user profile is opened. Run after
build_desktop_frontend.py; results and screenshots go to build/preview-audit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from playwright.sync_api import expect, sync_playwright

from audit_desktop_ui import DEFAULT_DIST, ROOT, serve
from mardas_folio.application import preview_document_text, preview_page_document_text
from mardas_folio.renderer import PdfOptions

DEFAULT_OUTPUT = ROOT / "build" / "preview-audit"
RICH = r"""---
title: Preview fidelity / پیش‌نمایش
---

# PREVIEW_RICH_ONLY — ریاضیات و Markdown

Inline energy $E = mc^2$, and $a^2+b^2=c^2$ stay beside their sentence.
متن فارسی با فرمول $\alpha + \beta = \gamma$ و English در همان پاراگراف.

$$
\int_0^\infty e^{-x^2}\,dx = \frac{\sqrt{\pi}}{2}
$$

$$
A = \begin{bmatrix}1 & 2\\3 & 4\end{bmatrix},\qquad
\det(A) = -2
$$

## Code retains its dollars

Inline code `$literal_inline$` and `\(literal_code\)` must remain code.

```python
KEEP_CODE_DOLLAR = "$not_math$"
KEEP_CODE_BRACKETS = r"\(literal_code\)"
print(KEEP_CODE_DOLLAR)
```

```python title="numbered.py" linenos
KEEP_NUMBERED_CODE = "$numbered_literal$"
KEEP_LONG_CODE = "ABCDEFGHIJKLMNOPQRSTUVWXYZ_ABCDEFGHIJKLMNOPQRSTUVWXYZ_ABCDEFGHIJKLMNOPQRSTUVWXYZ_ABCDEFGHIJKLMNOPQRSTUVWXYZ"
print(KEEP_NUMBERED_CODE)
```

## Aligned table / جدول

| Left | Center | Right |
| :--- | :---: | ---: |
| alpha | beta | gamma |
| فارسی | متن | ۱۲۳ |

## Offline diagram

```mermaid
flowchart LR
  A[Markdown] --> B{بررسی}
  B --> C[PDF]
```

![LOCAL_OFFLINE_IMAGE](preview-image.svg)

## Footnote

A source with a footnote[^audit] and a [local destination](#footnote).

[^audit]: Footnote body with English and متن فارسی.

## Inert document HTML

<script>globalThis.__previewAuditExecuted = true;</script>
<img src="https://example.invalid/preview-tracker.png" onerror="globalThis.__previewAuditExecuted = true;" alt="REMOTE_MUST_NOT_LOAD">
<iframe srcdoc="<script>parent.__previewAuditExecuted=true</script>"></iframe>
<a href="javascript:globalThis.__previewAuditExecuted=true">INERT_LINK</a>
"""
FRESH = r"""# FRESH_PREVIEW_ONLY

A newer document owns this preview: $\gamma_{\mathrm{fresh}} = \sqrt{2}$.
متن تازه که باید جای پیش‌نمایش قبلی بماند.
"""
SECURITY = r"""# SECURITY_PREVIEW_ONLY

$\href{javascript:globalThis.__previewAuditExecuted=true}{INERT_TEX_LINK}$

$\require{https://example.invalid/untrusted-tex-extension}$
"""

BRIDGE = r"""
globalThis.__previewAudit = {pick: 'rich', requests: [], held: []};
const payloads = fetch('/__preview_audit_payloads.json').then(response => response.json());
// A labelled client-only adversarial suffix complements the genuine backend
// payloads. These crafted URLs must never be resurrected by SVG ID rewriting.
const sanitizerProbe = '<img data-client-probe="remote-src" src="https://example.invalid/url(#x)">'
  + '<a data-client-probe="remote-href" href="https://example.invalid/url(#x)">INERT_REMOTE_LINK</a>'
  + '<svg><path data-client-probe="remote-paint" d="M0 0L1 1" fill="url(https://example.invalid/paint.svg#x)"/></svg>';
globalThis.__TAURI__ = {
  core: {invoke: async (command, args = {}) => {
    const data = await payloads;
    const audit = globalThis.__previewAudit;
    if (command === 'take_launch_files') return [];
    if (command === 'pick_markdown_files') return [data.rich.path, data.fresh.path, data.security.path];
    if (command === 'pick_markdown_file') return data[audit.pick].path;
    if (command === 'sidecar_request') {
      if (args.method === 'system.health') return {engine_version: '2.1.0', runtime: {platform: 'actual-backend-payload-audit'}};
      if (args.method === 'system.capabilities') return {methods: ['preview.document_page']};
      if (args.method === 'document.list_assets') return {assets: []};
      if (args.method === 'document.read') {
        const file = Object.values(data).find(entry => entry.path === args.params.path);
        return {path: file.path, content: file.content, revision: 'audit', kind: 'markdown', read_only: false};
      }
      if (['preview.document_text', 'preview.document_page'].includes(args.method)) {
        const file = Object.values(data).find(entry => entry.content === args.params.content);
        if (!file) throw new Error('Audit needs an exact Python payload for this source');
        audit.requests.push({method: args.method, path: file.path});
        if (args.method === 'preview.document_text') {
          return file === data.security ? {...file.body, body_html: file.body.body_html + sanitizerProbe} : file.body;
        }
        return file.page;
      }
      return {};
    }
    return null;
  }},
  event: {listen: async () => () => {}}
};
"""

ARTICLE_CHECK = r"""({selector, expectedMath, expectedCodes, alignment = true}) => {
  const root = document.querySelector(selector);
  if (!root) return {problems: ['preview article missing']};
  const problems = [];
  const maths = [...root.querySelectorAll('.math')].filter(node => !node.closest('pre,code'));
  if (maths.length !== expectedMath) problems.push(`math count ${maths.length} instead of ${expectedMath}`);
  const expressions = maths.map(node => {
    const svg = node.querySelector('mjx-container > svg');
    const box = svg?.getBoundingClientRect();
    const paths = [...(svg?.querySelectorAll('path') || [])];
    const source = node.getAttribute('aria-label') || '';
    if (node.dataset.mathRendered !== 'true' || !svg || !paths.length || !box || box.width <= 0 || box.height <= 0) {
      problems.push(`math has no visible SVG paths: ${source || node.textContent}`);
    }
    if (node.querySelector('[id],use[href],use[xlink\\:href]')) problems.push('math relies on shared SVG IDs');
    for (const fallback of node.querySelectorAll('mjx-assistive-mml')) {
      const style = getComputedStyle(fallback), bounds = fallback.getBoundingClientRect();
      const clipped = style.clip !== 'auto' || style.clipPath !== 'none';
      if (style.display !== 'none' && style.visibility !== 'hidden' && !clipped &&
          (bounds.width > 2 || bounds.height > 2)) {
        problems.push(`assistive MathML duplicates visible formula: ${source}`);
      }
    }
    if (node.dataset.mathError || node.querySelector('[data-mml-node="merror"]')) problems.push(`math error: ${source}`);
    if (/^\\+\(|^\$/.test(node.textContent.trim())) problems.push('literal math delimiters remain in preview');
    return {source, paths: paths.length, width: box?.width, height: box?.height,
      fill: paths[0] ? getComputedStyle(paths[0]).fill : null, direction: getComputedStyle(node).direction};
  });
  const code = [...root.querySelectorAll('code')].map(node => node.textContent);
  const headingOverflow = [...root.querySelectorAll('h1,h2,h3,h4,h5,h6')]
    .map(node => Math.max(0, node.scrollWidth - node.clientWidth));
  if (headingOverflow.some(amount => amount > 2)) problems.push('heading text overflows its preview column');
  for (const literal of expectedCodes) if (!code.includes(literal)) problems.push(`code text changed: ${literal}`);
  if (root.querySelector('pre mjx-container,code mjx-container')) problems.push('code was typeset as math');
  const identifier = root.querySelector('.codehilite .n');
  let codeContrast = null;
  if (identifier) {
    const rgb = value => (value.match(/[\d.]+/g) || []).map(Number);
    const luminance = color => {
      const channels = rgb(color).slice(0, 3).map(channel => {
        const value = channel / 255;
        return value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4;
      });
      return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
    };
    let ancestor = identifier, background = 'rgb(255,255,255)';
    while (ancestor) {
      const candidate = getComputedStyle(ancestor).backgroundColor;
      const channels = rgb(candidate);
      if (channels.length === 3 || channels[3] > .99) {background = candidate; break;}
      ancestor = ancestor.parentElement;
    }
    const foreground = getComputedStyle(identifier).color;
    const first = luminance(foreground), second = luminance(background);
    codeContrast = {foreground, background, ratio: (Math.max(first, second) + .05) / (Math.min(first, second) + .05)};
    if (codeContrast.ratio < 4.5) problems.push(`code identifier contrast is ${codeContrast.ratio.toFixed(2)}:1`);
  }
  const diagram = root.querySelector('.mermaid-diagram svg');
  if (expectedCodes.length && (!diagram || !diagram.querySelector('path'))) problems.push('offline Mermaid diagram is missing');
  if (diagram) {
    for (const element of diagram.querySelectorAll('[marker-end]')) {
      const target = /url\(#([^)]*)\)/.exec(element.getAttribute('marker-end'))?.[1];
      if (target && !diagram.querySelector(`[id="${CSS.escape(target)}"]`)) problems.push('Mermaid arrow marker reference is broken');
    }
  }
  const image = root.querySelector('img[alt="LOCAL_OFFLINE_IMAGE"]');
  if (expectedCodes.length && (!image || !image.complete || image.naturalWidth < 1 || !image.src.startsWith('data:image/'))) {
    problems.push('embedded local image did not load');
  }
  const alignments = [...root.querySelectorAll('table:not(.codehilitetable):not(.highlighttable) tr')].map(row =>
    [...row.querySelectorAll('th,td')].map(cell => getComputedStyle(cell).textAlign));
  if (alignment && expectedCodes.length && !alignments.length) problems.push('Markdown table missing');
  if (alignment) {
    for (const row of alignments) if (row.join(',') !== 'left,center,right') {
      problems.push(`table alignment lost: ${row.join(',')}`);
    }
  }
  const numbered = root.querySelector('.codehilitetable');
  let numberedCode = null;
  if (numbered) {
    const lineNumbers = numbered.querySelector('.linenos pre');
    const listing = numbered.querySelector('td.code pre');
    const numberBox = lineNumbers?.getBoundingClientRect(), codeBox = listing?.getBoundingClientRect();
    numberedCode = {tableDisplay: getComputedStyle(numbered).display,
      numberTop: numberBox?.top, codeTop: codeBox?.top,
      numberLineHeight: lineNumbers ? getComputedStyle(lineNumbers).lineHeight : null,
      codeLineHeight: listing ? getComputedStyle(listing).lineHeight : null};
    if (!numberBox || !codeBox || Math.abs(numberBox.top - codeBox.top) > 2 ||
        numberedCode.numberLineHeight !== numberedCode.codeLineHeight) {
      problems.push('numbered code lines and gutter are misaligned');
    }
  }
  for (const link of root.querySelectorAll('a[href^="#"]')) {
    if (!document.getElementById(link.getAttribute('href').slice(1))) problems.push('local/footnote link target is broken');
  }
  if (root.querySelector('script,iframe,object,embed,a[href^="javascript:"],img[src^="http"]')) problems.push('executable or remote document HTML survived');
  if ([...root.querySelectorAll('*')].some(node => [...node.attributes].some(attribute => /^on/i.test(attribute.name)))) {
    problems.push('active event attribute survived');
  }
  if (globalThis.__previewAuditExecuted) problems.push('document HTML executed');
  return {problems, expressions, codeBlocks: code.length, alignments,
    diagram: !!diagram, localImage: !!image, numberedCode, codeContrast, headingOverflow,
    mathIds: root.querySelectorAll('.math [id]').length};
}"""


def backend_payloads(output: Path) -> dict[str, Any]:
    sources = output / "source"
    sources.mkdir(parents=True, exist_ok=True)
    (sources / "preview-image.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="80" viewBox="0 0 240 80">'
        '<rect width="240" height="80" rx="8" fill="#dbeafe"/>'
        '<circle cx="36" cy="40" r="20" fill="#2563eb"/>'
        '<text x="68" y="46" font-family="sans-serif" font-size="16">Offline image</text></svg>',
        encoding="utf-8",
    )
    for name, content in [("rich", RICH), ("fresh", FRESH), ("security", SECURITY)]:
        (sources / f"{name}.md").write_text(content, encoding="utf-8")
    all_payloads: dict[str, Any] = {}
    for locale in ["en", "fa"]:
        for theme in ["light", "dark"]:
            payloads = {}
            for name, content in [("rich", RICH), ("fresh", FRESH), ("security", SECURITY)]:
                path = sources / f"{name}.md"
                options = PdfOptions(input_path=path, output_path=sources / f"{name}.pdf",
                                     document_language="fa-IR" if locale == "fa" else "en-US",
                                     mode=theme, style="modern", cover=False, unsafe_html=True)
                body = preview_document_text(options, content)
                page = preview_page_document_text(options, content)
                soup = BeautifulSoup(body["body_html"], "html.parser")
                payloads[name] = {
                    "path": str(path), "content": content, "body": body, "page": page,
                    "expected_math": len(soup.select(".math")),
                    "expected_codes": [node.get_text() for node in soup.select("code")],
                    "body_sha256": hashlib.sha256(body["body_html"].encode()).hexdigest(),
                }
            all_payloads[f"{locale}-{theme}"] = payloads
    (output / "backend-payloads.json").write_text(json.dumps(all_payloads, ensure_ascii=False), encoding="utf-8")
    return all_payloads


def initialise(browser: Any, url: str, payloads: dict[str, Any], locale: str, theme: str,
               width: int, errors: list[str], requests: list[str]) -> tuple[Any, Any]:
    context = browser.new_context(viewport={"width": width, "height": 900 if width > 1000 else 640},
                                  locale="fa-IR" if locale == "fa" else "en-US")
    def route_request(route: Any) -> None:
        request_url = route.request.url
        if request_url.startswith(url) or request_url.startswith(("data:", "blob:")):
            route.continue_()
        else:
            requests.append(request_url)
            route.abort()
    context.route("**/*", route_request)
    context.route("**/__preview_audit_payloads.json", lambda route: route.fulfill(json=payloads))
    page = context.new_page()
    page.set_default_timeout(20_000)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.add_init_script(BRIDGE)
    page.add_init_script(
        "localStorage.setItem('mardas.desktop.locale', " + json.dumps(locale) + ");"
        "localStorage.setItem('mardas.desktop.preferences.v1', JSON.stringify("
        + json.dumps({"theme": theme, "onboardingComplete": True, "viewMode": "source", "reducedMotion": "reduce"}) + "));"
        "localStorage.setItem('mardas.desktop.workspace-layout.v2', JSON.stringify("
        + json.dumps({"filesOpen": False, "sidebarOpen": False, "previewWidth": 340}) + "));"
    )
    return context, page


def wait_math(page: Any, selector: str, expected: int, *, frame: bool = False) -> None:
    page.wait_for_function("""({selector, expected, frame}) => {
      const doc = frame ? document.querySelector('#export-preview iframe')?.contentDocument : document;
      const root = doc?.querySelector(selector);
      const nodes = [...(root?.querySelectorAll('.math') || [])].filter(node => !node.closest('pre,code'));
      return nodes.length >= expected && nodes.every(node => node.dataset.mathRendered === 'true');
    }""", arg={"selector": selector, "expected": expected, "frame": frame})


def article_check(page: Any, selector: str, fixture: dict[str, Any], *, frame: bool = False) -> dict[str, Any]:
    args = {"selector": selector, "expectedMath": fixture["expected_math"],
            "expectedCodes": fixture["expected_codes"]}
    if frame:
        return page.locator("#export-preview iframe").content_frame.locator("body").evaluate(
            "(body, args) => (" + ARTICLE_CHECK + ")(args)", args)
    return page.evaluate(ARTICLE_CHECK, args)


def run_surface_case(browser: Any, url: str, payloads: dict[str, Any], locale: str, theme: str,
                     width: int, output: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"problems": [], "page_errors": [], "external_requests": [], "surfaces": {}}
    context, page = initialise(browser, url, payloads, locale, theme, width,
                               result["page_errors"], result["external_requests"])
    key = f"{locale}-{theme}-{width}"
    try:
        page.goto(url, wait_until="networkidle")
        page.locator("#workflow-open").click()
        page.locator(".document-tab .tab-activate").nth(0).click()
        page.locator('button.view-mode[data-view-mode="split"]').click()
        expect(page.locator("#preview-document")).to_contain_text("PREVIEW_RICH_ONLY")
        wait_math(page, "#preview-document", payloads["rich"]["expected_math"])
        result["surfaces"]["split"] = article_check(page, "#preview-document", payloads["rich"])
        result["preview_width"] = page.locator(".preview-pane").bounding_box()["width"]
        page.screenshot(path=str(output / f"{key}-split.png"))
        page.locator("#preview-document .math.display").last.evaluate("node => node.scrollIntoView({block: 'center'})")
        page.screenshot(path=str(output / f"{key}-split-matrix.png"))
        for feature, selector in [("code", ".code-block--numbered"), ("diagram", ".mermaid-diagram")]:
            page.locator(f"#preview-document {selector}").evaluate("node => node.scrollIntoView({block: 'center'})")
            page.screenshot(path=str(output / f"{key}-split-{feature}.png"))
        page.locator('button.view-mode[data-view-mode="read"]').click()
        wait_math(page, "#reading-document", payloads["rich"]["expected_math"])
        result["surfaces"]["read"] = article_check(page, "#reading-document", payloads["rich"])
        duplicate_ids = page.evaluate("""() => {
          const ids = [...document.querySelectorAll('#reading-document [id], #preview-document [id]')].map(node => node.id);
          return [...new Set(ids.filter((id, index) => ids.indexOf(id) !== index))];
        }""")
        if duplicate_ids:
            result["problems"].append(f"Split/Read share IDs: {duplicate_ids}")
        page.screenshot(path=str(output / f"{key}-read.png"))
        page.locator("#reading-document .math.display").last.evaluate("node => node.scrollIntoView({block: 'center'})")
        page.screenshot(path=str(output / f"{key}-read-matrix.png"))
        for feature, selector in [("code", ".code-block--numbered"), ("diagram", ".mermaid-diagram")]:
            page.locator(f"#reading-document {selector}").evaluate("node => node.scrollIntoView({block: 'center'})")
            page.screenshot(path=str(output / f"{key}-read-{feature}.png"))
        page.locator("#workspace-export").click()
        wait_math(page, '.pv-page[data-kind="content"] .md2pdf-article', payloads["rich"]["expected_math"], frame=True)
        result["surfaces"]["export"] = article_check(
            page, '.pv-page[data-kind="content"] .md2pdf-article', payloads["rich"], frame=True)
        page.screenshot(path=str(output / f"{key}-export.png"))
        page.locator("#export-back").click()
        page.locator(".document-tab .tab-activate").nth(2).click()
        expect(page.locator("#reading-document")).to_contain_text("SECURITY_PREVIEW_ONLY")
        wait_math(page, "#reading-document", payloads["security"]["expected_math"])
        security = page.locator("#reading-document").evaluate("""root => ({
          active: !!root.querySelector('.math a[href],a[href]:not([href^="#"]),script,iframe,object,embed'),
          activeNodes: [...root.querySelectorAll('.math a[href],a[href]:not([href^="#"]),script,iframe,object,embed')].map(node => node.outerHTML),
          events: [...root.querySelectorAll('*')].some(node => [...node.attributes].some(attribute => /^on/i.test(attribute.name))),
          restoredURL: [...root.querySelectorAll('[data-client-probe]')].some(node => [...node.attributes].some(attribute => /https?:/.test(attribute.value))),
          executed: !!globalThis.__previewAuditExecuted
        })""")
        result["tex_security"] = security
        if any(security[name] for name in ["active", "events", "restoredURL", "executed"]):
            result["problems"].append("TeX loaded active HTML or executable attributes")
    except Exception as error:
        result["problems"].append(f"{type(error).__name__}: {error}")
        page.screenshot(path=str(output / f"{key}-failure.png"))
    finally:
        for surface, checks in result["surfaces"].items():
            result["problems"].extend(f"{surface}: {problem}" for problem in checks["problems"])
        result["problems"].extend(result["page_errors"])
        result["problems"].extend(f"external request: {request}" for request in result["external_requests"])
        context.close()
    return result


def run_stale_case(browser: Any, url: str, payloads: dict[str, Any], output: Path, *, export: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"problems": [], "page_errors": [], "external_requests": []}
    context, page = initialise(browser, url, payloads, "en", "light", 1440,
                               result["page_errors"], result["external_requests"])
    held: list[Any] = []
    page.route("**/vendor/mathjax/tex-svg-full.js", lambda route: held.append(route))
    label = "export" if export else "split"
    try:
        page.goto(url, wait_until="networkidle")
        if export:
            page.locator("#workflow-quick").click()
            page.locator("#choose-source").click()
            page.wait_for_function("() => !!document.querySelector('#export-preview iframe')?.contentDocument?.querySelector('.math')")
            page.evaluate("() => { __previewAudit.pick = 'fresh'; }")
            page.locator("#choose-source").click()
            page.wait_for_function("() => document.querySelector('#export-preview iframe')?.contentDocument?.body.textContent.includes('FRESH_PREVIEW_ONLY')")
        else:
            page.locator("#workflow-open").click()
            page.locator(".document-tab .tab-activate").nth(0).click()
            page.locator('button.view-mode[data-view-mode="split"]').click()
            # A serialized preview may still await MathJax for a previously
            # activated tab. Switching documents must win once that load ends.
            for _ in range(200):
                if held:
                    break
                page.wait_for_timeout(25)
            page.locator(".document-tab .tab-activate").nth(1).click()
            expect(page.locator("#markdown-editor")).to_have_value(FRESH)
            # Typesetting a previous tab must not hold the engine preview
            # flight: the newer backend HTML can arrive before the asset does.
            expect(page.locator("#preview-document")).to_contain_text("FRESH_PREVIEW_ONLY")
        if len(held) != 1:
            raise AssertionError(f"Expected one held offline MathJax request, got {len(held)}")
        held.pop().continue_()
        selector = '.pv-page[data-kind="content"] .md2pdf-article' if export else "#preview-document"
        wait_math(page, selector, payloads["fresh"]["expected_math"], frame=export)
        result["article"] = article_check(page, selector, payloads["fresh"], frame=export)
        text = page.evaluate("""exporting => exporting
          ? document.querySelector('#export-preview iframe').contentDocument.body.textContent
          : document.querySelector('#preview-document').textContent""", export)
        if "PREVIEW_RICH_ONLY" in text or "FRESH_PREVIEW_ONLY" not in text:
            result["problems"].append("stale typeset mutated the newer document preview")
        result["problems"].extend(result["article"]["problems"])
        page.screenshot(path=str(output / f"stale-{label}.png"))
    except Exception as error:
        result["problems"].append(f"{type(error).__name__}: {error}")
        page.screenshot(path=str(output / f"stale-{label}-failure.png"))
    finally:
        for route in held:
            route.abort()
        result["problems"].extend(result["page_errors"])
        result["problems"].extend(f"external request: {request}" for request in result["external_requests"])
        context.close()
    return result


def run_audit(dist: Path, output: Path, *, executable_path: str | None = None,
              case_limit: int | None = None, skip_stale: bool = False) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    all_payloads = backend_payloads(output)
    report: dict[str, Any] = {"scope": "Actual Python preview body/page payloads and offline browser typesetter; native transport and delivery timing are fixtures",
                              "scenarios": {}, "stale": {}, "case_limit": case_limit}
    report["payloads"] = {key: {name: {"math": item["expected_math"], "body_sha256": item["body_sha256"]}
                                      for name, item in payload.items()} for key, payload in all_payloads.items()}
    with serve(dist) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=executable_path)
        for locale in ["en", "fa"]:
            for theme in ["light", "dark"]:
                for width in [1440, 840]:
                    if case_limit is not None and len(report["scenarios"]) >= case_limit:
                        continue
                    key = f"{locale}-{theme}-{width}"
                    report["scenarios"][key] = run_surface_case(browser, url, all_payloads[f"{locale}-{theme}"], locale, theme, width, output)
        if not skip_stale:
            for export in [False, True]:
                report["stale"]["export" if export else "split"] = run_stale_case(
                    browser, url, all_payloads["en-light"], output, export=export)
        browser.close()
    cases = [*report["scenarios"].values(), *report["stale"].values()]
    report["passed"] = bool(cases) and not any(case["problems"] for case in cases)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--executable-path")
    parser.add_argument("--case-limit", type=int)
    parser.add_argument("--skip-stale", action="store_true")
    args = parser.parse_args()
    report = run_audit(args.dist.resolve(), args.out.resolve(), executable_path=args.executable_path,
                       case_limit=args.case_limit, skip_stale=args.skip_stale)
    failures = {key: value["problems"] for key, value in {**report["scenarios"], **report["stale"]}.items() if value["problems"]}
    print(json.dumps({"passed": report["passed"], "scenarios": len(report["scenarios"]),
                      "stale_cases": len(report["stale"]), "failures": failures,
                      "report": str(args.out.resolve() / "report.json")}, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

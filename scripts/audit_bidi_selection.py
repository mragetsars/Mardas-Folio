#!/usr/bin/env python3
"""Compare actual glyph geometry with CodeMirror selection paint, including IPA."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
HTML = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="/styles.css"><link rel="stylesheet" href="/workspace.css">
<link rel="stylesheet" href="/authoring.css"><link rel="stylesheet" href="/writer-workspace.css">
<link rel="stylesheet" href="/interaction-details.css"></head>
<body data-view="workspace"><div class="editor-pane" style="display:block;height:900px;width:100%">
<textarea id="source"></textarea></div><script type="module">
import {createCodeMirrorEditorAdapter} from '/js/vendor/codemirror-editor.bundle.mjs';
window.adapter=createCodeMirrorEditorAdapter(document.querySelector('#source'),{mode:'live',theme:'dark'});
</script></body></html>"""

PARAGRAPH = (
    "حالا در سمت دیگه در علوم و تکنولوژی می بینیم که چیزی به وجود اومده به اسم هوش مصنوعی، "
    "تقریبا با داده‌های بزرگ و الگو ها و پیش بینی سر و کار داریم. "
    "دانش داده‌های بزرگ و دیتا ساینس big data (بیگ دیتا — /bɪɡ ˈdeɪtə/)، "
    "رو می‌شه بدون این که در ادامه درباره آن سخن بگیم به روش دیگری بررسی کنیم. "
) * 2

GEOMETRY = """({from,to})=>{
  const content=document.querySelector('.cm-content');
  const boxes=[...document.querySelectorAll('.cm-selectionBackground')]
    .map(e=>e.getBoundingClientRect()).filter(r=>r.width>.1&&r.height>.1);
  const covered=(r)=>boxes.some(p=>p.left-.5<=(r.left+r.right)/2&&p.right+.5>=(r.left+r.right)/2
    &&p.top-.5<=(r.top+r.bottom)/2&&p.bottom+.5>=(r.top+r.bottom)/2);
  const walker=document.createTreeWalker(content,NodeFilter.SHOW_TEXT);
  let node,offset=0,missing=[],extra=[],glyphs=0;
  while(node=walker.nextNode()){
    for(let i=0;i<node.length;i++){
      const at=offset+i,char=node.data[i];
      if(/[\\s\\u200b-\\u200f]/u.test(char))continue;
      const range=document.createRange();range.setStart(node,i);range.setEnd(node,i+1);
      for(const r of range.getClientRects()){
        if(r.width<.1)continue;
        if(at>=from&&at<to){glyphs++;if(!covered(r))missing.push({at,char,x:r.left,y:r.top});}
        else if(covered(r))extra.push({at,char,x:r.left,y:r.top});
      }
    }
    offset+=node.length;
  }
  const rect=content.getBoundingClientRect(),style=getComputedStyle(content);
  const left=rect.left+parseFloat(style.paddingLeft),right=rect.right-parseFloat(style.paddingRight);
  return {glyphs,missing,extra,source:content.textContent,selection:getSelection().toString(),
    outside:boxes.filter(r=>r.left<left-.6||r.right>right+.6).map(r=>r.toJSON()),
    bounds:{left,right},rectangles:boxes.length,boxes:boxes.map(r=>r.toJSON())};
}"""


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def run(dist: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(dist)))
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    report = {"status": "running", "cases": []}
    try:
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch()
            for locale in ("en", "fa"):
                for width in (1200, 680):
                    page = browser.new_page(viewport={"width": width, "height": 1000})
                    page.route("**/selection-fixture.html", lambda route: route.fulfill(body=HTML, content_type="text/html"))
                    page.goto(f"http://127.0.0.1:{server.server_port}/selection-fixture.html")
                    page.wait_for_function("Boolean(window.adapter)")
                    page.evaluate("locale=>{document.documentElement.dir=locale==='fa'?'rtl':'ltr';document.documentElement.dataset.theme='dark'}", locale)
                    for mode in ("live", "source"):
                        variants = [(value, "100%", 1) for value in ("—", "–", "…", "“", "’")]
                        variants.append(("—", "680px", 1.25))
                        for punctuation, column, scale in variants:
                            page.evaluate("v=>{document.documentElement.style.setProperty('--writing-column',v.column);document.documentElement.style.setProperty('--document-text-scale',v.scale)}", {"column": column, "scale": str(scale)})
                            text = PARAGRAPH.replace("—", punctuation)
                            ipa = text.index("bɪɡ ˈdeɪtə")
                            ranges = [(60, len(text)-30, "wrapped"), (ipa, ipa+10, "IPA"), (ipa+1, ipa+8, "partial-IPA")]
                            for start, end, label in ranges:
                                for direction in ("forward", "backward"):
                                    page.evaluate("v=>{adapter.setMode(v.mode);adapter.value=v.text;adapter.focus();adapter.setSelectionRange(v.from,v.to,v.direction)}", {
                                        "mode": mode, "text": text, "from": start, "to": end, "direction": direction,
                                    })
                                    page.evaluate("async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))}")
                                    page.wait_for_timeout(80)
                                    geometry = page.evaluate(GEOMETRY, {"from": start, "to": end})
                                    details = {"locale":locale,"width":width,"mode":mode,"column":column,"scale":scale,"punctuation":punctuation,"range":label,"direction":direction}
                                    assert geometry["source"] == text, (details, "source DOM mismatch")
                                    assert geometry["selection"] == text[start:end], (details, "logical selection mismatch")
                                    assert geometry["glyphs"] > 0 and not geometry["missing"], (details, geometry)
                                    assert not geometry["extra"], (details, geometry)
                                    assert not geometry["outside"], (details, geometry)
                                    report["cases"].append({**details,"selected_glyphs":geometry["glyphs"],"rectangles":geometry["rectangles"]})
                        page.screenshot(path=str(output/f"{locale}-{width}-{mode}.png"))
                    page.close()
            browser.close()
        report["status"] = "pass"
        return report
    finally:
        server.shutdown()
        server.server_close()
        (output/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT/"apps/desktop/frontend")
    parser.add_argument("--output", type=Path, default=ROOT/"build/bidi-selection")
    options = parser.parse_args()
    result = run(options.dist.resolve(), options.output.resolve())
    print(f"PASS {len(result['cases'])} actual glyph/selection geometry cases")

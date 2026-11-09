from pathlib import Path
from urllib.parse import unquote
import os

import pytest
from bs4 import BeautifulSoup

from mardas_folio.markdown import render_markdown

pytestmark = pytest.mark.skipif(
    os.environ.get("MARDAS_RENDER_SMOKE") != "1",
    reason="Chromium layout verification is opt-in",
)


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width", [360, 1000])
@pytest.mark.parametrize("surface", ["reading-document", "preview-document", "book-review-document"])
def test_content_controls_and_notes_are_readable(theme, width, surface):
    from playwright.sync_api import sync_playwright

    source = "# Heading\n\n- [ ] کار نخست\n- [x] Done\n\n> [!WARNING]\n> Warning text\n\nمتن [^a].\n\n[^a]: متن پانویس\n"
    result = render_markdown(source, language="fa")
    frontend = Path(__file__).resolve().parents[1] / "apps/desktop/frontend"
    styles = "\n".join((frontend / name).read_text(encoding="utf-8") for name in ("styles.css", "workspace.css", "shell-system.css"))
    old_css = os.environ.get("MF09_OLD_CSS")
    if old_css:
        styles = (frontend / "styles.css").read_text(encoding="utf-8") + "\n" + Path(old_css).read_text(encoding="utf-8")
    html = f'<html data-theme="{theme}"><head><style>{styles}</style></head><body><article class="document-content {surface}">{result.body_html}</article></body></html>'
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": 800})
        page.set_content(html)
        checkbox = page.locator(".task-list-item input").first
        assert checkbox.evaluate("e => e.getBoundingClientRect().height") < 25
        assert checkbox.evaluate("e => getComputedStyle(e.parentElement).listStyleType") == "none"
        assert page.locator(".callout-title").evaluate("e => getComputedStyle(e).display") == "block"
        assert page.locator(".footnotes ol").evaluate("e => getComputedStyle(e).listStyleType") == "none"
        assert page.locator(".footnote-item").evaluate("e => getComputedStyle(e).display") == "grid"
        for link in page.locator('.footnotes a[href^="#"], .footnote-ref a[href^="#"]').all():
            target = unquote(link.get_attribute("href")[1:])
            assert page.locator(f"[id={target!r}]").count() == 1
        assert BeautifulSoup(result.body_html, "html.parser").select_one(".footnote-marker").get_text() == "۱."
        browser.close()

"""Real DOM fixtures; no native dialogs, user files, or external network."""

import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from tests._paths import ROOT

import pytest
from bs4 import BeautifulSoup

FRONTEND = ROOT / "apps" / "desktop" / "frontend"


@pytest.fixture(scope="session")
def component_browser():
    if os.environ.get("MARDAS_BROWSER_TESTS") != "1":
        pytest.skip("Set MARDAS_BROWSER_TESTS=1 to run Chromium component tests")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture(scope="session")
def frontend_url(component_browser):
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(FRONTEND)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(params=["en", "fa"])
def export_panel(component_browser, frontend_url, request):
    """Mount the production HTML/CSS with the real component and injected native I/O."""
    markup = BeautifulSoup((FRONTEND / "index.html").read_text(encoding="utf-8"), "html.parser")
    for script in markup.find_all("script"):
        script.decompose()
    errors = []
    context = component_browser.new_context()
    try:
        page = context.new_page()
        page.set_default_timeout(5000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route(
            "**/__component__.html",
            lambda route: route.fulfill(
                body=str(markup),
                content_type="text/html",
            ),
        )
        page.goto(f"{frontend_url}/__component__.html")
        page.evaluate(
            """async (locale) => {
          const {createExportOptionsPanel} = await import('/js/features/export/export-options-panel.mjs');
          const {createTranslator} = await import('/js/core/i18n.mjs');
          const translator = createTranslator(locale);
          document.documentElement.dir = locale === 'fa' ? 'rtl' : 'ltr';
          document.documentElement.lang = locale;
          const root = document.querySelector('#export-view');
          document.querySelectorAll('.view').forEach(view => view.classList.remove('active'));
          root.classList.add('active');
          root.classList.remove('hidden');
          root.querySelector('#export-settings').hidden = false;
          root.querySelector('#export-setup').hidden = true;
          window.presetOptions = {style: 'modern', palette: 'blue', toc: true, cover: true};
          window.changes = [];
          window.pickErrors = [];
          window.pickPath = async () => null;
          window.panel = createExportOptionsPanel({
            root, t: (key) => translator.t(key),
            getPresetOptions: () => window.presetOptions,
            onChange: () => window.changes.push(window.panel.overrides()),
            pickPath: (field) => window.pickPath(field),
            onError: (error) => window.pickErrors.push(error.message),
          });
          window.panel.reset();
        }""",
            request.param,
        )
        yield page
        assert not errors, errors
    finally:
        context.close()

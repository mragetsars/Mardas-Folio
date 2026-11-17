"""Real application composition with only the native bridge substituted."""

import json

import pytest
from playwright.sync_api import expect

BRIDGE = r"""
localStorage.setItem("mardas.desktop.preferences.v1", JSON.stringify({
  onboardingComplete: true, viewMode: "source", autoPreview: false
}));
globalThis.calls = [];
globalThis.project = {
  path: "/fixtures/book", name: "کتاب Sample", config: "mardas.toml", config_sha256: "config-v1",
  files: [{path: "one.md", kind: "markdown"}],
  book: {title: "کتاب Sample", output: "dist/book.pdf", chapter_count: 1,
    chapters: [{path: "one.md", title: "فصل One"}]}
};
globalThis.__TAURI__ = {
  core: {invoke: async (command, args = {}) => {
    calls.push({command, ...args});
    if (command === "take_launch_files") return [];
    if (command === "pick_project_directory") return "/fixtures";
    if (command === "sidecar_cancel") return {cancel_requested: true};
    if (command !== "sidecar_request") return null;
    switch (args.method) {
      case "system.health": return {engine_version: "test", runtime: {platform: "browser"}};
      case "system.capabilities": return {methods: ["document.assets", "bibliography.index"]};
      case "book.create":
        if (globalThis.holdCreation) await new Promise(resolve => {globalThis.finishCreation = resolve;});
        return project;
      case "project.open":
      case "project.refresh": return {project};
      case "project.read": return {
        absolute_path: project.path + "/one.md", path: "one.md", kind: "markdown",
        content: "# فصل One\\n\\nEnglish and فارسی\\n", revision: "r1", sha256: "first"
      };
      case "project.search":
        if (globalThis.holdSearch) {
          await new Promise(resolve => {globalThis.finishSearch = resolve;});
          globalThis.holdSearch = false;
        }
        return {matches: [{path: "one.md", line: 3, column: 1, preview: args.params.query}],
          truncated: true, truncated_lines: 1, regex_line_limit: 2000};
      case "book.preview": return {html: '<html lang="fa" dir="rtl"><head><style>body{display:none}</style></head><body dir="rtl"><article class="md2pdf-article"><section class="md2pdf-cover">COVER_ONLY</section><div class="md2pdf-watermark">WATERMARK_ONLY</div><a href="#one">فهرست</a><h1 id="one">فصل One</h1><p>Book review متن</p><script>window.previewExecuted=true</script></article></body></html>'};
      case "bibliography.index": return {entries: [], diagnostics: []};
      case "document.assets": return {assets: []};
      case "validate.document_text": return {valid: true, diagnostics: []};
      case "preview.document_text": return {body_html: "<h1>فصل One</h1>", diagnostics: []};
      default: return {};
    }
  }},
  event: {listen: async () => () => {}}
};
"""


@pytest.fixture(params=["en", "fa"])
def book_page(component_browser, frontend_url, request):
    context = component_browser.new_context(viewport={"width": 1440, "height": 960})
    errors = []
    try:
        page = context.new_page()
        page.set_default_timeout(5000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script(
            "localStorage.setItem('mardas.desktop.locale', "
            + json.dumps(request.param)
            + ");"
            + BRIDGE
        )
        page.goto(frontend_url, wait_until="networkidle")
        expect(page.locator("#engine-state")).to_have_attribute("data-state", "ready")
        yield page, request.param
        assert not errors, errors
    finally:
        context.close()


def fill_book_form(page):
    page.locator("#workflow-book").click()
    expect(page.locator("#book-project-title-input")).to_be_focused()
    page.locator("#book-project-title-input").fill("کتاب Sample")
    expect(page.locator("#book-project-folder-input")).to_have_value("کتاب-sample")
    page.locator("#book-project-folder-input").fill("my-book")
    page.locator("#book-project-title-input").fill("کتاب Sample Updated")
    expect(page.locator("#book-project-folder-input")).to_have_value("my-book")
    page.locator("#choose-book-parent").click()


def test_book_creation_and_review_preserve_editor_focus_and_publication_scope(book_page):
    page, locale = book_page
    fill_book_form(page)
    expect(page.locator("#book-project-language")).to_have_value(
        "fa-IR" if locale == "fa" else "en-US"
    )
    expect(page.locator("#book-project-direction")).to_have_value(
        "rtl" if locale == "fa" else "ltr"
    )
    page.locator("#book-project-form button[type=submit]").click()
    expect(page.locator("#book-project-modal")).to_be_hidden()
    expect(page.locator("#markdown-editor")).to_have_value("# فصل One\\n\\nEnglish and فارسی\\n")
    before = page.locator("#markdown-editor").input_value()
    mode = page.locator("#workspace-view").get_attribute("data-view-mode")
    if not page.locator("#author-sidebar").is_visible():
        page.locator("#workspace-layout-button").click()
        page.locator("#workspace-toggle-sidebar").click()
        page.keyboard.press("Escape")
    page.locator('[data-sidebar="book"]').click()
    page.locator("#book-preview").click()
    review = page.locator("#book-review-document")
    expect(page.locator("#book-review-modal")).to_be_visible()
    expect(page.locator("#close-book-review")).to_be_focused()
    expect(review).to_have_attribute("dir", "rtl")
    expect(review).to_have_attribute("lang", "fa")
    expect(review).to_contain_text("Book review متن")
    expect(review.locator("script,style,.md2pdf-cover,.md2pdf-watermark")).to_have_count(0)
    expect(review.locator("a")).to_have_attribute("href", "#book-review-one")
    expect(review.locator("#book-review-one")).to_have_text("فصل One")
    assert page.evaluate("window.previewExecuted || false") is False
    assert page.locator("body").evaluate("el => getComputedStyle(el).display") != "none"
    assert page.locator("#workspace-view").get_attribute("data-view-mode") == mode
    page.keyboard.press("Escape")
    expect(page.locator("#book-review-modal")).to_be_hidden()
    expect(page.locator("#book-preview")).to_be_focused()
    expect(review).to_be_empty()
    expect(page.locator("#markdown-editor")).to_have_value(before)
    page.locator("#close-book-project").click()
    expect(page.locator("#navigator-project-section")).to_be_hidden()
    expect(page.locator("#markdown-editor")).to_have_value(before)
    created = page.evaluate("calls.find(call => call.method === 'book.create').params")
    assert created == {
        "parent_path": "/fixtures",
        "folder_name": "my-book",
        "title": "کتاب Sample Updated",
        "language": "fa-IR" if locale == "fa" else "en-US",
        "direction": "rtl" if locale == "fa" else "ltr",
    }


def test_dismissed_creation_does_not_activate_a_late_project(book_page):
    page, _ = book_page
    page.evaluate("globalThis.holdCreation = true")
    fill_book_form(page)
    page.locator("#book-project-form button[type=submit]").click()
    page.wait_for_function("typeof finishCreation === 'function'")
    page.keyboard.press("Escape")
    expect(page.locator("#book-project-modal")).to_be_hidden()
    page.evaluate("finishCreation()")
    expect(page.locator("#book-project-form button[type=submit]")).to_be_enabled()
    expect(page.locator("#navigator-project-section")).to_be_hidden()
    assert page.evaluate("calls.some(call => call.method === 'project.read')") is False
    page.locator("#workflow-book").click()
    expect(page.locator("#book-project-title-input")).to_have_value("")
    expect(page.locator("#book-project-folder-input")).to_have_value("")


def test_project_search_cancellation_rejects_late_results_and_keeps_navigation(book_page):
    page, _ = book_page
    fill_book_form(page)
    page.locator("#book-project-form button[type=submit]").click()
    expect(page.locator("#markdown-editor")).to_have_value("# فصل One\\n\\nEnglish and فارسی\\n")
    if not page.locator("#author-sidebar").is_visible():
        page.locator("#workspace-layout-button").click()
        page.locator("#workspace-toggle-sidebar").click()
        page.keyboard.press("Escape")
    page.locator('[data-sidebar="project"]').click()
    page.evaluate("globalThis.holdSearch = true")
    page.locator("#project-search-query").fill("OLD_RESULT")
    page.locator("#run-project-search").click()
    page.wait_for_function("typeof finishSearch === 'function'")
    expect(page.locator("#run-project-search")).to_have_attribute("data-state", "running")
    page.locator("#run-project-search").click()
    expect(page.locator("#run-project-search")).to_have_attribute("data-state", "idle")
    assert page.evaluate("calls.filter(call => call.command === 'sidecar_cancel').length") == 1
    page.locator("#project-search-query").fill("English فارسی")
    page.locator("#project-search-regex").check()
    page.locator("#project-search-case").check()
    page.locator("#run-project-search").click()
    page.evaluate("finishSearch()")
    results = page.locator("#project-search-results")
    expect(results.locator(".match-preview")).to_have_text("English فارسی")
    expect(results).not_to_contain_text("OLD_RESULT")
    expect(results.locator(".search-limit-notice")).to_have_count(2)
    expect(page.locator("#run-project-search")).to_have_attribute("data-state", "idle")
    request = page.evaluate("calls.filter(call => call.method === 'project.search').at(-1).params")
    assert request == {
        "project_path": "/fixtures/book",
        "query": "English فارسی",
        "regex": True,
        "case_sensitive": True,
        "max_results": 200,
    }
    results.locator("button").click()
    expect(page.locator("#markdown-editor")).to_have_value("# فصل One\\n\\nEnglish and فارسی\\n")
    expect(page.locator(".cm-content")).to_be_focused()

"""User-visible export-settings behavior, using real Chromium keyboard and DOM APIs."""

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.browser


def test_render_and_search_never_change_publication_options(export_panel):
    page = export_panel
    original = page.evaluate("window.panel.overrides()")
    page.locator("#option-search").fill("margin")
    page.locator("#show-expert").press("Space")
    page.evaluate("window.panel.render()")
    assert page.evaluate("window.panel.overrides()") == original
    assert page.evaluate("window.changes.length") == 1


def test_palette_has_one_tab_stop_and_supports_directional_navigation(export_panel):
    page = export_panel
    radios = page.locator('[data-option-key="palette"] [role="radio"]')
    assert radios.count() == 8  # inherit plus the seven publication palettes
    expect(page.locator('[data-option-key="palette"] [tabindex="0"]')).to_have_count(1)
    selected = page.locator('[data-option-key="palette"] [aria-checked="true"]')
    selected.focus()
    right = "ArrowLeft" if page.locator("html").get_attribute("dir") == "rtl" else "ArrowRight"
    selected.press(right)
    assert page.evaluate("window.panel.overrides().palette") == "emerald"
    expect(page.locator('[data-option-key="palette"] [aria-checked="true"]')).to_be_focused()
    page.locator('[data-option-key="palette"] [aria-checked="true"]').press("ArrowUp")
    page.locator('[data-option-key="palette"] [aria-checked="true"]').press("ArrowUp")
    assert "palette" not in page.evaluate("window.panel.overrides()")
    expect(page.locator('[data-option-key="palette"] [tabindex="0"]')).to_have_count(1)


def test_changing_and_resetting_option_restores_the_preset(export_panel):
    page = export_panel
    control = page.locator("#adv-style")
    control.focus()
    control.select_option("academic")
    expect(control).to_be_focused()
    assert page.evaluate("window.panel.modifiedCount()") == 1
    page.locator('[data-option-key="style"] .option-reset').click()
    assert page.evaluate("window.panel.overrides().style") == "modern"
    assert page.evaluate("window.panel.modifiedCount()") == 0
    expect(control).to_be_focused()


def test_invalid_draft_invalidates_previous_export_and_is_not_submitted(export_panel):
    page = export_panel
    page.locator("#option-category").select_option("page")
    margin = page.locator("#adv-margin-top")
    margin.fill("21mm")
    margin.press("Enter")
    assert page.evaluate("window.panel.overrides().margin_top") == "21mm"
    before = page.evaluate("window.changes.length")
    margin.fill("wide")
    margin.press("Enter")
    expect(margin).to_have_attribute("aria-invalid", "true")
    expect(page.locator("#adv-margin-top-problem")).not_to_be_empty()
    assert "margin_top" not in page.evaluate("window.panel.overrides()")
    assert page.evaluate("window.changes.length") == before + 1


def test_disabled_dependents_and_boolean_keyboard_state(export_panel):
    page = export_panel
    page.locator("#option-search").fill("toc")
    selected = page.locator('[data-option-key="toc"] [aria-checked="true"]')
    selected.focus()
    selected.press("ArrowUp")
    assert page.evaluate("window.panel.overrides().toc") is False
    expect(page.locator("#adv-toc-depth")).to_be_disabled()
    expect(page.locator('[data-option-key="toc"] [aria-checked="true"]')).to_be_focused()


@pytest.mark.parametrize("action", ["reset", "destroy"])
def test_late_native_picker_cannot_overwrite_a_replaced_or_disposed_draft(export_panel, action):
    page = export_panel
    page.locator("#option-search").fill("cover_logo")
    page.evaluate(
        "() => { window.pickPath = () => new Promise(resolve => window.finishPick = resolve); }"
    )
    page.locator('[data-option-key="cover_logo"] .text-row button').click()
    if action == "reset":
        page.evaluate("window.presetOptions = {style: 'academic'}; window.panel.reset()")
    else:
        page.evaluate("window.panel.destroy()")
    expected = page.evaluate("window.panel.overrides()")
    page.evaluate("window.finishPick('/late/logo.png')")
    assert page.evaluate("window.panel.overrides()") == expected


def test_native_picker_failure_is_reported_and_can_be_retried(export_panel):
    page = export_panel
    page.locator("#option-search").fill("cover_logo")
    page.evaluate(
        "() => { window.pickPath = async () => { throw new Error('Picker unavailable'); }; }"
    )
    button = page.locator('[data-option-key="cover_logo"] .text-row button')
    button.click()
    expect(button).to_be_enabled()
    assert page.evaluate("window.pickErrors") == ["Picker unavailable"]
    page.evaluate("() => { window.pickPath = async () => '/logo.png'; }")
    button.click()
    expect(page.locator("#adv-cover-logo")).to_have_value("/logo.png")


def test_disposal_removes_feature_listeners(export_panel):
    page = export_panel
    page.evaluate("window.panel.destroy()")
    page.locator("#option-category").select_option("page")
    expect(page.locator("#adv-style")).to_have_count(0)
    expect(page.locator("#adv-margin-top")).to_have_count(0)

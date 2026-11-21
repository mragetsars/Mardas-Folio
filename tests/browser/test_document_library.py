"""Exercise the desktop entry point with a real engine and a deterministic file picker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import expect

from mardas_folio.application import EngineService


@pytest.mark.parametrize("locale", ["en", "fa"])
def test_library_keyboard_create_save_reorder_and_reopen(
    component_browser, frontend_url, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, locale: str
) -> None:
    monkeypatch.setenv("MARDAS_FOLIO_LIBRARY_DIR", str(tmp_path / "profile"))
    engine = EngineService()
    names = ["first یادداشت.txt", "second یادداشت.txt"]
    selections = iter([None, *(str(tmp_path / name) for name in names)])
    errors: list[str] = []

    def native(command, args):
        if command == "sidecar_request":
            method = args["method"]
            if method == "system.health":
                return {"engine_version": "component", "runtime": {"platform": "test"}}
            if method == "system.capabilities":
                return engine.capabilities()
            return engine.dispatch(method, args.get("params", {}))
        if command == "take_launch_files":
            return []
        if command == "pick_text_output":
            assert args["suggested_path"].endswith(".txt")
            return next(selections)
        return None

    with component_browser.new_context(viewport={"width": 1000, "height": 800}) as context:
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.set_default_timeout(7000)
        page.expose_function("nativeInvoke", native)
        page.add_init_script(
            "localStorage.setItem('mardas.desktop.locale'," + json.dumps(locale) + ");"
            """localStorage.setItem('mardas.desktop.preferences.v1',JSON.stringify({
            onboardingComplete:true,autoPreview:false,viewMode:'source'}));
            globalThis.__TAURI__={core:{invoke:(c,a={})=>nativeInvoke(c,a)},
            event:{listen:async()=>()=>{}}};"""
        )
        page.goto(frontend_url)
        trigger = page.locator("#shelf-add")
        expect(trigger).to_have_attribute("aria-expanded", "false")
        trigger.focus()
        trigger.press("ArrowDown")
        expect(page.get_by_role("menuitem")).to_have_count(5)
        page.keyboard.press("Escape")
        expect(trigger).to_be_focused()
        expect(trigger).to_have_attribute("aria-expanded", "false")

        for i, name in enumerate(names):
            trigger.focus()
            trigger.press("ArrowDown")
            note = page.get_by_role("menuitem", name="Note" if locale == "en" else "یادداشت")
            note.click()
            if i == 0:
                page.locator("#workspace-save").click()
                assert not (tmp_path / name).exists()
            page.locator("#workspace-save").click()
            expect(page.locator("#editor-title")).to_contain_text(name)
            page.locator("#open-library").click()
            expect(page.locator(".library-item[data-type=note]")).to_have_count(i + 1)
        pair = page.locator(".library-slot").filter(
            has=page.locator(".library-item[data-type=note]")
        )
        expect(pair).to_have_count(1)
        first = page.locator(".library-item").first
        first.locator(".library-open").focus()
        first.locator(".library-grip").press("ArrowDown")
        expect(first.locator(".library-open")).to_have_attribute("title", names[1])
        page.reload()
        page.locator("#open-library").click()
        expect(page.locator(".library-item").first.locator(".library-open")).to_have_attribute(
            "title", names[1]
        )
        assert all((tmp_path / name).is_file() for name in names)
        assert not errors

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
    draft_name = "moved draft یادداشت.txt"
    selections = iter([None, *(str(tmp_path / name) for name in [*names, draft_name])])
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

        trigger.press("ArrowDown")
        page.get_by_role("menuitem", name="Note" if locale == "en" else "یادداشت").click()
        page.locator("#open-library").click()
        cards = page.locator(".library-item")
        expect(cards).to_have_count(3)
        draft = cards.last
        draft_id = draft.get_attribute("data-id")
        draft.locator(".library-open").focus()
        draft.locator(".library-grip").press("Home")
        expect(cards.first).to_have_attribute("data-id", draft_id)
        cards.first.locator(".library-open").click()
        page.locator("#workspace-save").click()
        expect(page.locator("#editor-title")).to_contain_text(draft_name)
        page.locator("#open-library").click()
        expect(cards.first.locator(".library-open")).to_have_attribute("title", draft_name)
        page.reload()
        page.locator("#open-library").click()
        expect(cards.first.locator(".library-open")).to_have_attribute("title", draft_name)
        expect(cards.nth(1).locator(".library-open")).to_have_attribute("title", names[1])
        assert all((tmp_path / name).is_file() for name in [*names, draft_name])
        assert not errors


@pytest.mark.parametrize("locale", ["en", "fa"])
def test_library_specimens_pointer_reorder_and_live_appearance(
    component_browser, frontend_url, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, locale: str
) -> None:
    monkeypatch.setenv("MARDAS_FOLIO_LIBRARY_DIR", str(tmp_path / "profile"))
    engine = EngineService()
    rows = [
        ("book", "Letters and White Space", {"variant": "full", "texture": "leather"}),
        (
            "document",
            "User Research Report",
            {"fastener": "clip", "sheets": "6", "chart": "۳۵، ۸۰"},
        ),
        ("note", "Field notes", {"material": "cotton"}),
        ("note", "One more idea", {"material": "sticky"}),
        ("resume", "Raha Nouri", {"avatar": "woman"}),
        ("article", "Reading the Landscape", {"binding": "wire", "pattern": "terrain"}),
    ]
    engine.dispatch(
        "library.write",
        {
            "expected_revision": 0,
            "items": [
                {
                    "id": str(i),
                    "path": str(tmp_path / f"sample-{i}"),
                    "type": kind,
                    "title": title,
                    "detail": "A short preview of the source file.",
                    "appearance": appearance,
                }
                for i, (kind, title, appearance) in enumerate(rows)
            ],
        },
    )

    def native(command, args):
        if command == "sidecar_request":
            return engine.dispatch(args["method"], args.get("params", {}))
        if command == "take_launch_files":
            return []
        return None

    with component_browser.new_context(viewport={"width": 1200, "height": 900}) as context:
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.expose_function("nativeInvoke", native)
        page.add_init_script(
            "localStorage.setItem('mardas.desktop.locale'," + json.dumps(locale) + ");"
            """localStorage.setItem('mardas.desktop.preferences.v1',JSON.stringify({
            onboardingComplete:true,autoPreview:false}));
            globalThis.__TAURI__={core:{invoke:(c,a={})=>nativeInvoke(c,a)},
            event:{listen:async()=>()=>{}}};"""
        )
        page.goto(frontend_url)
        grid = page.locator("#shelf-grid")
        expect(grid.locator(".library-item")).to_have_count(6)
        expect(grid.locator(".library-slot")).to_have_count(6)
        expect(grid).to_have_css("--columns", "3")
        expect(grid.locator(".folio-a4-leaf")).to_have_count(5)
        expect(grid.locator(".folio-report-bars i")).to_have_count(2)
        expect(grid.locator(".folio-note-pin")).to_have_count(1)
        expect(grid.locator(".folio-wire-loop")).to_have_count(14)
        expect(grid.locator(".folio-dogear")).to_have_count(3)

        book = grid.locator('[data-id="0"] .library-open')
        target = grid.locator('[data-id="2"] .library-open')
        source_box = book.bounding_box()
        target_box = target.bounding_box()
        assert source_box and target_box
        assert source_box["width"] == pytest.approx(196)
        assert target_box["width"] == pytest.approx(112, abs=0.05)
        page.mouse.move(source_box["x"] + 70, source_box["y"] + 90)
        page.mouse.down()
        page.mouse.move(target_box["x"] + 50, target_box["y"] + 10, steps=10)
        expect(page.locator(".library-drag-image")).to_have_count(1)
        expect(grid.locator('[data-id="2"]')).to_have_attribute("data-insert", "before")
        expect(grid.locator('[data-id="2"]')).to_have_attribute("data-axis", "y")
        page.mouse.up()
        expect(page.locator(".library-drag-image")).to_have_count(0)
        expect(grid.locator(".library-item").first).to_have_attribute("data-id", "1")
        assert [row["id"] for row in engine.dispatch("library.read", {})["items"]] == [
            "1",
            "0",
            "2",
            "3",
            "4",
            "5",
        ]

        report = grid.locator('[data-id="1"]')
        report.locator(".library-open").focus()
        report.locator(".library-tools button").first.click()
        form = page.locator(".library-appearance")
        expect(form).to_be_visible()
        form.locator('button[value="binder"]').click()
        expect(form.locator(".folio-binder-clip")).to_have_count(1)
        expect(grid.locator(".folio-paperclip")).to_have_count(1)
        form.locator('button[type="submit"]').click()
        expect(form).to_have_count(0)
        expect(report.locator(".folio-binder-clip")).to_have_count(1)
        assert engine.dispatch("library.read", {})["items"][0]["appearance"]["fastener"] == "binder"

        page.locator('#shelf-filter button[value="note"]').click()
        expect(grid.locator(".library-item")).to_have_count(2)
        expect(grid.locator(".library-slot")).to_have_count(2)
        expect(grid).to_have_css("--columns", "2")
        page.set_viewport_size({"width": 280, "height": 760})
        expect(grid).to_have_css("--columns", "1")
        assert page.locator("#shelf-search").bounding_box()["width"] > 60
        top_trigger = page.locator("#shelf-add-top")
        top_trigger.press("ArrowDown")
        expect(top_trigger).to_have_attribute("aria-expanded", "true")
        expect(page.locator("#shelf-type-list [role=menuitem]")).to_have_count(5)
        page.keyboard.press("Escape")
        expect(top_trigger).to_be_focused()
        expect(top_trigger).to_have_attribute("aria-expanded", "false")
        assert not errors

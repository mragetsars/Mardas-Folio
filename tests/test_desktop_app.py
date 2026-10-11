from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import pytest
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_desktop_frontend import build_frontend  # noqa: E402
from stage_desktop_runtime import stage_runtime  # noqa: E402
from verify_desktop_frontend import verify_frontend  # noqa: E402
from verify_desktop_installer import MIN_INSTALLER_BYTES, verify_installer  # noqa: E402
from mardas_folio import __version__  # noqa: E402

DESKTOP = ROOT / "apps" / "desktop"
TAURI = DESKTOP / "src-tauri"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")

# Letters, digits and ASCII punctuation are notation the interface font always
# has. Everything in a symbol category outside ASCII is a picture, and whether
# it draws at all depends on the symbol fonts the machine happens to carry.
_ALLOWED_SYMBOLS = "\u200c\u200f\u2014\u2026"


def _pictographs(text: str) -> list[str]:
    return [
        character
        for character in text
        if ord(character) > 0x7F
        and character not in _ALLOWED_SYMBOLS
        and not ("\u0600" <= character <= "\u06FF")
        and unicodedata.category(character) in {"So", "Sm", "Sk", "Po"}
    ]


def _rule_blocks(sheet: str, selector: str) -> list[str]:
    """Every declaration block whose selector list names *selector* itself.

    Only the element's own rules, not rules for its descendants: a
    ``direction`` on ``.editor-pane`` pins the pane, one on
    ``.editor-pane small`` pins a path inside it and is fine. Prefixes that
    only raise specificity (``html[dir="ltr"] .x``) are stripped so those
    count as the element's own rule too.
    """
    blocks: list[str] = []
    for selectors, body in _RULE.findall(sheet):
        for one in selectors.split(","):
            trimmed = re.sub(r"^\s*html(\[[^\]]*\])*\s+", "", one).strip()
            if trimmed == selector:
                blocks.append(body)
                break
    return blocks


def _symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symbolic links are unavailable: {exc}")


def _synthetic_runtime(root: Path) -> Path:
    root.mkdir(parents=True)
    executable = root / ("mardas-sidecar.exe" if sys.platform == "win32" else "mardas-sidecar")
    executable.write_bytes(b"synthetic-sidecar")
    browser = root / "runtime" / "chromium" / "headless-shell.bin"
    browser.parent.mkdir(parents=True)
    browser.write_bytes(b"synthetic-browser")
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "size": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    manifest = {
        "schema_version": 1,
        "version": __version__,
        "browser_bundled": True,
        "files": files,
    }
    (root / "runtime-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return root


def test_tauri_configuration_is_native_and_versioned() -> None:
    config = json.loads((TAURI / "tauri.conf.json").read_text(encoding="utf-8"))
    cargo = (TAURI / "Cargo.toml").read_text(encoding="utf-8")
    assert config["version"] == __version__
    assert config["build"]["frontendDist"] == "../dist"
    assert "devUrl" not in config["build"]
    assert config["bundle"]["targets"] == ["nsis"]
    assert config["bundle"]["resources"] == {"resources/sidecar/": "sidecar/"}
    assert config["plugins"]["updater"] == {
        "pubkey": "",
        "endpoints": [],
    }
    assert {"md", "markdown"}.issubset(set(config["bundle"]["fileAssociations"][0]["ext"]))
    windows_config = json.loads((TAURI / "tauri.windows.conf.json").read_text(encoding="utf-8"))
    macos_config = json.loads((TAURI / "tauri.macos.conf.json").read_text(encoding="utf-8"))
    linux_config = json.loads((TAURI / "tauri.linux.conf.json").read_text(encoding="utf-8"))
    assert windows_config["bundle"]["windows"]["webviewInstallMode"]["type"] == "offlineInstaller"
    assert windows_config["bundle"]["windows"]["nsis"]["installMode"] == "currentUser"
    # `tauri-build` rejects an unknown configuration field outright, and it only
    # parses the platform file matching the host, so a stale key here fails the
    # Windows installer job alone — after a full Rust compile. `bundleVCRuntime`
    # survived the Tauri v1 to v2 migration this way: it was a WiX-only option,
    # this bundle is NSIS, and no other platform ever read the file.
    accepted_windows_keys = {
        "digestAlgorithm",
        "certificateThumbprint",
        "timestampUrl",
        "tsp",
        "webviewInstallMode",
        "allowDowngrades",
        "minimumWebview2Version",
        "wix",
        "nsis",
        "signCommand",
    }
    assert set(windows_config["bundle"]["windows"]) <= accepted_windows_keys
    # The same deny-unknown-fields trap one level down, and the same blast
    # radius: NSIS options are only parsed on the Windows host.
    nsis_config = windows_config["bundle"]["windows"]["nsis"]
    accepted_nsis_keys = {
        "template",
        "headerImage",
        "sidebarImage",
        "installerIcon",
        "uninstallerIcon",
        "uninstallerHeaderImage",
        "installMode",
        "languages",
        "customLanguageFiles",
        "displayLanguageSelector",
        "compression",
        "startMenuFolder",
        "installerHooks",
    }
    assert set(nsis_config) <= accepted_nsis_keys
    # Without these MUI falls back to its own stock installer graphic, so the
    # setup executable ships to users wearing a generic NSIS icon rather than
    # the application's own.
    for key in ("installerIcon", "uninstallerIcon"):
        assert nsis_config[key] == "icons/icon.ico"
    assert (TAURI / "icons" / "icon.ico").is_file()
    assert macos_config["bundle"]["targets"] == ["dmg"]
    assert "signingIdentity" not in macos_config["bundle"]["macOS"]
    assert macos_config["bundle"]["macOS"]["minimumSystemVersion"] == "14.0"
    assert linux_config["bundle"]["targets"] == ["appimage", "deb"]
    assert {"icons/icon.icns", "icons/icon.ico", "icons/icon.png"} <= set(config["bundle"]["icon"])
    assert 'name = "mardas-folio"' in cargo
    assert f'version = "{__version__}"' in cargo
    # The identifier the updater matches an installed application by, and the
    # name of its per-user config directory. Changing it orphans both.
    assert config["identifier"] == "io.github.mragetsars.mardas-folio"
    # Cargo.lock carries the crate version too, and `cargo test --locked` in
    # the native desktop jobs fails when it disagrees with Cargo.toml. It sat
    # a release behind once because nothing here held it.
    lock = tomllib.loads((TAURI / "Cargo.lock").read_text(encoding="utf-8"))
    locked = [entry for entry in lock["package"] if entry["name"] == "mardas-folio"]
    assert [entry["version"] for entry in locked] == [__version__]


def test_native_shell_uses_stdio_sidecar_and_single_instance_first() -> None:
    main = (TAURI / "src" / "main.rs").read_text(encoding="utf-8")
    sidecar = (TAURI / "src" / "sidecar.rs").read_text(encoding="utf-8")
    assert main.index(".plugin(single_instance)") < main.index("tauri_plugin_window_state")
    for command in (
        "pick_markdown_file",
        "pick_markdown_files",
        "pick_markdown_output",
        "pick_pdf_output",
        "pick_document_asset",
        "pick_project_directory",
        "sidecar_request",
        "sidecar_cancel",
        "take_launch_files",
        "pick_support_bundle_output",
    ):
        assert command in main
    for command in (
        "pick_markdown_output",
        "pick_text_output",
        "pick_pdf_output",
        "sidecar_request",
        "sidecar_cancel",
    ):
        sync_signature = (
            '#[tauri::command(rename_all = "snake_case")]\n'
            f'fn {command}('
        )
        async_signature = (
            '#[tauri::command(rename_all = "snake_case")]\n'
            f'async fn {command}('
        )
        assert sync_signature in main or async_signature in main

    assert "Stdio::piped()" in sidecar
    assert "MARDAS_RUNTIME_ROOT" in sidecar
    assert "mardas-sidecar.exe" in sidecar
    updates = (TAURI / "src" / "updates.rs").read_text(encoding="utf-8")
    assert "updater_status" in main
    assert "updater_check" in main
    assert "updater_install" in main
    assert 'option_env!("MARDAS_UPDATER_PUBKEY")' in updates
    assert ".pubkey(pubkey)" in updates
    assert ".endpoints(vec![endpoint])" in updates
    assert 'parsed.scheme() != "https"' in updates
    combined = (main + sidecar).casefold()
    assert "webbrowser" not in combined
    assert "threadinghttpserver" not in combined
    assert "127.0.0.1" not in combined


def test_frontend_is_modular_and_workflow_focused() -> None:
    index = (DESKTOP / "frontend" / "index.html").read_text(encoding="utf-8")
    main = (DESKTOP / "frontend" / "js" / "main.mjs").read_text(encoding="utf-8")
    assert 'id="start-view"' in index
    assert 'id="export-view"' in index
    assert 'id="workspace-view"' in index
    assert 'id="recent-list"' in index
    assert 'id="preset-grid"' in index
    assert 'id="validate-button"' in index
    for element_id in (
        "document-tabs",
        "markdown-editor",
        "preview-document",
        "outline-list",
        "frontmatter-form",
        "asset-list",
        "citation-list",
        "problem-list",
        "find-bar",
        "recovery-modal",
        "project-file-tree",
        "project-search-query",
        "project-search-results",
        "citation-search",
        "book-project-modal",
        "chapter-modal",
        "book-chapter-list",
        "book-add-chapter",
        "book-validate",
        "book-preview",
        "book-export",
        "book-output-result",
        "book-open-output",
        "book-reveal-output",
        "book-current-chapter",
        "export-result",
        "template-grid",
        "onboarding-modal",
        "settings-modal",
        "help-modal",
        "command-modal",
        "command-query",
        "save-support-bundle",
        "check-updates",
        "install-update",
        "update-state",
        "update-progress",
        "workspace-toggle-sidebar",
        "sidebar-resizer",
        "preview-resizer",
        "sidebar-problem-badge",
    ):
        assert f'id="{element_id}"' in index
    assert 'type="module" src="./js/main.mjs"' in index
    assert '<link rel="stylesheet" href="./workspace.css">' in index
    assert (DESKTOP / "frontend" / "workspace.css").is_file()
    assert "sidecar_request" in main
    assert "sidecar_cancel" in main
    assert "desktop-open-files" in main
    assert "cancelActiveProjectSearch" in main
    assert 'button.textContent = t("cancelSearch")' in main
    assert 't("searchResultsLimited")' in main
    for method in (
        "document.read",
        "document.save",
        "document.list_assets",
        "document.import_asset",
        "preview.document_text",
        "validate.document_text",
    ):
        authoring_api = DESKTOP / "frontend" / "js" / "core" / "authoring-api.mjs"
        assert method in authoring_api.read_text(encoding="utf-8")
    project_api = DESKTOP / "frontend" / "js" / "core" / "project-api.mjs"
    for method in (
        "project.open",
        "project.refresh",
        "project.read",
        "project.save",
        "project.search",
        "bibliography.index",
    ):
        assert method in project_api.read_text(encoding="utf-8")
    book_api = DESKTOP / "frontend" / "js" / "core" / "book-api.mjs"
    for method in (
        "book.create",
        "book.add_chapter",
        "book.duplicate_chapter",
        "book.reorder_chapters",
        "book.remove_chapter",
        "book.validate",
        "book.preview",
        "book.export",
    ):
        assert method in book_api.read_text(encoding="utf-8")
    for module in (
        "authoring-api.mjs",
        "documents.mjs",
        "editor-commands.mjs",
        "find-replace.mjs",
        "markdown-analysis.mjs",
        "recovery.mjs",
        "session.mjs",
        "editor-adapter.mjs",
        "project-api.mjs",
        "book-api.mjs",
        "preferences.mjs",
        "workspace-layout.mjs",
        "i18n.mjs",
        "templates.mjs",
        "command-palette.mjs",
        "modal-manager.mjs",
        "updater-api.mjs",
    ):
        assert (DESKTOP / "frontend" / "js" / "core" / module).is_file()
    assert "fetch(" not in main
    assert "window.open" not in main
    assert "devUrl" not in index
    assert "https://" not in index
    assert index.count("http://ipc.localhost") == 1


def test_native_workspace_has_explicit_layout_controls_and_accessible_panes() -> None:
    index = (DESKTOP / "frontend" / "index.html").read_text(encoding="utf-8")
    main = (DESKTOP / "frontend" / "js" / "main.mjs").read_text(encoding="utf-8")
    workspace_css = (DESKTOP / "frontend" / "workspace.css").read_text(encoding="utf-8")
    soup = BeautifulSoup(index, "html.parser")

    sidebar = soup.select_one("#author-sidebar")
    assert sidebar is not None
    assert sidebar.get("data-i18n-aria-label") == "documentTools"
    engine = soup.select_one("#engine-state")
    assert engine is not None and engine.get("role") == "status" and engine.get("aria-live") == "polite"
    preview_loading = soup.select_one("#preview-loading")
    assert preview_loading is not None and preview_loading.get("role") == "status"
    tabs = sidebar.select(".sidebar-tabs [data-sidebar]")
    assert len(tabs) == 7
    assert all(tab.get("role") == "tab" for tab in tabs)
    assert all(tab.get("aria-controls") for tab in tabs)
    assert len(sidebar.select("[role='tabpanel']")) == 7

    sidebar_toggle = soup.select_one("#workspace-toggle-sidebar")
    assert sidebar_toggle is not None
    assert sidebar_toggle.get("aria-pressed") == "false"
    assert sidebar_toggle.get("aria-controls")

    # The preview pane is not a standalone switch any more. Showing source and
    # showing the preview were separate toggles whose combinations included
    # states nobody wants, so one radio group names the arrangements instead.
    modes = soup.select("[data-view-mode]")
    assert [button.get("data-view-mode") for button in modes] == ["write", "source", "read", "split"]
    assert all(button.get("role") == "radio" for button in modes)
    assert sum(button.get("aria-checked") == "true" for button in modes) == 1
    group = soup.select_one(".view-modes")
    assert group is not None and group.get("role") == "radiogroup"

    files = soup.select_one("#file-navigator")
    assert files is not None and files.get("data-i18n-aria-label") == "files"
    assert soup.select_one("#open-document-list") is not None
    files_toggle = soup.select_one("#workspace-toggle-files")
    assert files_toggle is not None and files_toggle.get("aria-controls") == "file-navigator"
    reading = soup.select_one("#reading-document")
    assert reading is not None and reading.get("tabindex") == "0"
    for element_id in ("file-resizer", "sidebar-resizer", "preview-resizer"):
        separator = soup.select_one(f"#{element_id}")
        assert separator is not None
        assert separator.get("role") == "separator"
        assert separator.get("aria-orientation") == "vertical"
        assert separator.get("tabindex") == "0"
        assert separator.get("aria-controls")
        assert separator.get("aria-valuemin")
        assert separator.get("aria-valuemax")
        assert separator.get("aria-valuenow")

    assert "readWorkspaceLayout" in main
    assert "writeWorkspaceLayout" in main
    assert "beginPaneResize" in main
    assert "resizePaneWithKeyboard" in main
    assert 'sidebarResizer.setAttribute("aria-valuenow"' in main
    assert 'previewResizer.setAttribute("aria-valuenow"' in main
    assert 'document.body.dataset.view = name' in main
    assert soup.select_one("#mardas-ui-icons") is not None
    assert len(sidebar.select(".sidebar-tab-icon .ui-icon")) == 7
    assert 'body[data-view="workspace"] main' in workspace_css
    assert 'var(--files-track) var(--files-divider) minmax(0, 1fr)' in workspace_css
    assert 'var(--preview-divider) var(--preview-track) var(--sidebar-divider) var(--sidebar-track)' in workspace_css
    assert '@media (max-width: 1100px)' in workspace_css
    assert '@media (max-width: 760px)' in workspace_css
    assert soup.select_one("#exit-focus-mode") is not None


def test_workbench_takes_its_direction_from_the_interface_language() -> None:
    """The workspace mirrors with the locale instead of being pinned left-to-right.

    Every region of the workbench used to declare its own ``direction``, and
    the declarations cancelled out to left-to-right whatever the language was:
    a Persian user got the activity rail, the side bar, the tab strip and the
    format bar on the same edges as an English one, under a title bar that had
    mirrored. Nothing here may re-pin a region; the direction comes from
    ``<html dir>`` and reaches the panes by inheritance.
    """
    styles = (DESKTOP / "frontend" / "styles.css").read_text(encoding="utf-8")
    workspace_css = (DESKTOP / "frontend" / "workspace.css").read_text(encoding="utf-8")
    main = (DESKTOP / "frontend" / "js" / "main.mjs").read_text(encoding="utf-8")

    pinned = (
        ".authoring-grid",
        ".author-sidebar",
        ".editor-pane",
        ".preview-pane",
        ".sidebar-panel",
        ".sidebar-tabs",
        ".format-bar",
        ".editor-status",
        ".find-bar",
        ".codemirror-mount",
        ".document-tabs",
    )
    declares_direction = re.compile(r"(?:^|;|\s)direction\s*:")
    for sheet in (styles, workspace_css):
        for selector in pinned:
            for block in _rule_blocks(sheet, selector):
                assert not declares_direction.search(block), (
                    f"{selector} still pins a direction"
                )

    # The panes swap edges when the layout mirrors, so a drag that widened one
    # has to narrow it. Without a sign taken from the document the handle runs
    # away from the pointer in Persian.
    assert "paneResizeSign" in main
    assert 'document.documentElement.dir === "rtl" ? -1 : 1' in main

    # The preview shows the document, not the interface, so it resolves its own
    # direction from the text rather than inheriting the locale's.
    index = (DESKTOP / "frontend" / "index.html").read_text(encoding="utf-8")
    assert 'id="preview-document" dir="auto"' in index


def test_every_control_is_drawn_with_the_icon_set_the_app_ships() -> None:
    """No control is labelled with a symbol the interface font may not have.

    The interface used to name its actions with whatever character looked
    closest: a hatched square for "insert image", a shaded block for "table",
    an anticlockwise arrow for undo, a gear for settings. Which of those
    render, at what weight and on what baseline, depends on the symbol fonts
    installed on the machine — several have no coverage in the interface font
    and fall back to whatever the system substitutes, up to the missing-glyph
    box. Letterforms that *are* the notation stay: B, I, S, H1-H6, MD, BIB.
    """
    index = (DESKTOP / "frontend" / "index.html").read_text(encoding="utf-8")
    main = (DESKTOP / "frontend" / "js" / "main.mjs").read_text(encoding="utf-8")
    templates = (DESKTOP / "frontend" / "js" / "core" / "templates.mjs").read_text(
        encoding="utf-8"
    )

    sprite = re.search(
        r'<svg class="ui-icon-sprite".*?</svg>', index, re.S
    )
    assert sprite is not None, "the sprite is missing"
    symbols = set(re.findall(r'<symbol id="icon-([a-z0-9-]+)"', sprite.group(0)))
    assert len(symbols) >= 40

    # Every reference resolves. A `<use href="#icon-x">` with no symbol behind
    # it renders as nothing at all, which looks like a blank button.
    for source in (index, main, templates):
        for name in re.findall(r'href="#icon-([a-z0-9-]+)"', source):
            assert name in symbols, f"#icon-{name} has no symbol"
    for name in re.findall(r'spriteIcon\("([a-z0-9-]+)"\)', main):
        assert name in symbols, f"spriteIcon({name!r}) has no symbol"
    for name in re.findall(r'symbol: "([a-z0-9-]+)"', main + templates):
        assert name in symbols, f"symbol {name!r} has no drawing"

    # The same idea drawn twice is how an icon set stops being one.
    drawings: dict[str, str] = {}
    for name, body in re.findall(
        r'<symbol id="icon-([a-z0-9-]+)"[^>]*>(.*?)</symbol>', sprite.group(0), re.S
    ):
        normalized = re.sub(r"\s+", " ", body).strip()
        assert normalized not in drawings, (
            f"icon-{name} repeats the drawing of icon-{drawings[normalized]}"
        )
        drawings[normalized] = name

    # No control keeps a pictographic label. Latin letters, digits and ASCII
    # notation are allowed; anything above U+00FF that is not Arabic script is
    # a symbol pretending to be an icon.
    for match in re.finditer(r"<button\b[^>]*>(.*?)</button>", index, re.S):
        body = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        stray = _pictographs(body)
        assert not stray, f"a button is labelled {body!r} ({stray!r})"

    # ...and none is generated from JS either. `textContent = "\u00d7"` and a
    # `>\u00d7</button>` inside a template string both count: a multiplication
    # sign standing in for a close button is the same defect as a shaded block
    # standing in for a table.
    for source, label in ((main, "main.mjs"), (templates, "templates.mjs")):
        for body in re.findall(r'(?:icon|textContent) *[:=] *"([^"]{1,4})"', source):
            assert not _pictographs(body), f"{label} still writes the glyph {body!r}"
        for body in re.findall(r">([^<>{}`\n]{1,4})</button>", source):
            assert not _pictographs(body), f"{label} still writes the glyph {body!r}"


def test_the_application_asks_its_own_questions() -> None:
    """No native `confirm` on a decision that can destroy work.

    Overwriting a file that changed on disk, closing a document with unsaved
    changes and dropping a chapter from a book were all asked with
    `window.confirm`, which draws the platform's dialog: another typeface,
    another button order, another focus model, and nothing translated past the
    string it is handed. On the screen whose whole claim is that it will not
    overwrite a file without asking, the asking did not look like the product.
    """
    main = (DESKTOP / "frontend" / "js" / "main.mjs").read_text(encoding="utf-8")
    index = (DESKTOP / "frontend" / "index.html").read_text(encoding="utf-8")

    # The comment explaining why may name them; the code may not call them.
    code = re.sub(r"/\*[\s\S]*?\*/", "", main)
    code = re.sub(r"//[^\n]*", "", code)
    for banned in ("globalThis.confirm", "window.confirm", "globalThis.alert", "window.alert"):
        assert banned not in code, f"{banned} is still used"
    assert "function askConfirmation(" in main
    # Cancel is the safe answer to all three questions, so it is where focus
    # lands and what every way out of the dialog resolves to.
    assert 'initialFocus: "#confirm-cancel"' in main
    for element in ("#confirm-title", "#confirm-message", "#confirm-accept", "#confirm-cancel"):
        assert f'id="{element[1:]}"' in index


def test_dates_and_destructive_answers_follow_the_interface() -> None:
    """Two things the recovery dialog was getting wrong.

    `toLocaleString()` with no argument formats for the machine's locale, so a
    Persian interface on an English system printed "11/15/2023, 1:43:20 AM" —
    the one line in that dialog that never followed the language around it.
    And "Discard", which throws away unsaved work for good, was styled as an
    ordinary secondary button while every other destructive answer in the
    product wears the danger colour.
    """
    main = (DESKTOP / "frontend" / "js" / "main.mjs").read_text(encoding="utf-8")
    index = (DESKTOP / "frontend" / "index.html").read_text(encoding="utf-8")

    # The comment explaining the fix may name the call; the code may not make it.
    code = re.sub(r"/\*[\s\S]*?\*/", "", main)
    code = re.sub(r"//[^\n]*", "", code)
    assert "toLocaleString()" not in code, "a date is being formatted for the machine"
    assert "function formatMoment(" in main
    assert 'state.locale === "fa" ? "fa-IR" : "en-GB"' in main

    soup = BeautifulSoup(index, "html.parser")
    for identifier in ("discard-recovery", "confirm-accept"):
        button = soup.select_one(f"#{identifier}")
        assert button is not None, identifier
    discard = soup.select_one("#discard-recovery")
    assert "danger" in discard.get("class", []), "discarding unsaved work is destructive"
    # And the answer that keeps the work is the one focus lands on.
    assert 'initialFocus: "#restore-recovery"' in main


def test_export_status_badge_does_not_rely_on_colour_alone() -> None:
    """A failed export used to show a tick, recoloured.

    ``.status-visual`` painted the same check mark for every state and changed
    only its hue, so "PDF was not created" and "PDF created successfully" were
    the same picture to anyone who does not separate red from green.
    """
    main = (DESKTOP / "frontend" / "js" / "main.mjs").read_text(encoding="utf-8")
    index = (DESKTOP / "frontend" / "index.html").read_text(encoding="utf-8")
    assert 'id="status-symbol"' in index
    assert "STATUS_SYMBOLS" in main
    for state in ("idle", "working", "success", "error"):
        assert re.search(rf"{state}: \"[a-z-]+\"", main), f"no symbol for {state}"


def test_professional_editor_is_locked_bundled_and_offline() -> None:
    package = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((DESKTOP / "package-lock.json").read_text(encoding="utf-8"))
    main = (DESKTOP / "frontend" / "js" / "main.mjs").read_text(encoding="utf-8")
    bundle = DESKTOP / "frontend" / "js" / "vendor" / "codemirror-editor.bundle.mjs"
    notices = (DESKTOP / "frontend" / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    assert package["version"] == __version__
    assert package["private"] is True
    assert package["dependencies"]["codemirror"] == "6.0.2"
    assert all(
        not str(version).startswith(("^", "~", ">", "<", "*"))
        for group in ("dependencies", "devDependencies")
        for version in package[group].values()
    )
    assert lock["lockfileVersion"] == 3
    assert lock["packages"][""]["version"] == __version__
    assert 100_000 < bundle.stat().st_size < 2_000_000
    assert 'import("./vendor/codemirror-editor.bundle.mjs")' in main
    assert "createCodeMirrorEditorAdapter" in main
    assert "CodeMirror 6" in notices
    assert "MIT License" in notices


def test_frontend_build_is_atomic_and_does_not_remove_working_directory(tmp_path: Path) -> None:
    source = DESKTOP / "frontend"
    output = tmp_path / "dist"
    survivor = tmp_path / "survivor.txt"
    survivor.write_text("keep", encoding="utf-8")
    built = build_frontend(source, output, version=__version__)
    payload = verify_frontend(built, expected_version=__version__)
    assert survivor.read_text(encoding="utf-8") == "keep"
    assert payload["version"] == __version__
    assert __version__ in (built / "index.html").read_text(encoding="utf-8")


def test_frontend_verifier_rejects_symlink_root(tmp_path: Path) -> None:
    built = build_frontend(
        DESKTOP / "frontend",
        tmp_path / "real-frontend",
        version=__version__,
    )
    link = tmp_path / "linked-frontend"
    _symlink_or_skip(link, built, directory=True)

    with pytest.raises(ValueError, match="missing or unsafe"):
        verify_frontend(link, expected_version=__version__)


def test_runtime_staging_is_verified_and_atomic(tmp_path: Path) -> None:
    source = _synthetic_runtime(tmp_path / "runtime")
    target = tmp_path / "resources" / "sidecar"
    staged = stage_runtime(source, target, expected_version=__version__)
    assert (staged / ".mardas-staged-runtime.json").is_file()
    assert (staged / "runtime-manifest.json").is_file()
    survivor = tmp_path / "survivor.txt"
    survivor.write_text("keep", encoding="utf-8")
    (source / "runtime" / "chromium" / "headless-shell.bin").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="integrity mismatch"):
        stage_runtime(source, target, expected_version=__version__)
    assert survivor.read_text(encoding="utf-8") == "keep"
    assert (target / "runtime-manifest.json").is_file()


def test_runtime_staging_keeps_the_tracked_placeholder(tmp_path: Path) -> None:
    """Staging must not delete the file that keeps the directory in a checkout.

    `tauri.conf.json` declares `resources/sidecar/` as a bundle resource and the
    Tauri build script rejects a resource path that does not exist, so the
    tracked placeholder is what lets `cargo test` run on a machine that has not
    built the runtime. Staging replaces the whole directory, and when it dropped
    the placeholder a local build deleted it and the deletion was committed,
    which broke every native desktop job.
    """
    source = _synthetic_runtime(tmp_path / "runtime")
    target = tmp_path / "resources" / "sidecar"
    target.mkdir(parents=True)
    (target / "README.md").write_text("staging directory\n", encoding="utf-8")

    staged = stage_runtime(source, target, expected_version=__version__)

    assert (staged / "README.md").read_text(encoding="utf-8") == "staging directory\n"
    assert (staged / ".mardas-staged-runtime.json").is_file()


def test_installer_verifier_accepts_versioned_pe_payload(tmp_path: Path) -> None:
    path = tmp_path / f"Mardas-Folio-{__version__}-windows-x86_64-setup.exe"
    path.write_bytes(b"MZ" + b"\0" * (MIN_INSTALLER_BYTES + 32))
    payload = verify_installer(path, expected_version=__version__)
    assert payload["version"] == __version__
    assert payload["architecture"] == "x86_64"
    assert payload["sha256"] == _sha256(path)


def test_installer_verifier_rejects_symlink_input(tmp_path: Path) -> None:
    name = f"Mardas-Folio-{__version__}-windows-x86_64-setup.exe"
    target = tmp_path / "real" / name
    target.parent.mkdir()
    target.write_bytes(b"MZ" + b"\0" * (MIN_INSTALLER_BYTES + 32))
    link = tmp_path / name
    _symlink_or_skip(link, target)

    with pytest.raises(ValueError, match="missing or unsafe"):
        verify_installer(link, expected_version=__version__)


def test_node_frontend_contracts() -> None:
    """Run the desktop interface suite when its dependencies are present.

    Several of those tests import the editor's own dependencies — `@codemirror`
    and `@lezer` — to drive commands and the Markdown parser against the real
    parser rather than a stand-in. Without `node_modules` they cannot resolve
    those imports and fail, which is why this skips instead of reporting a
    dependency gap as a product defect. The `Native desktop contracts` CI job
    installs the locked dependencies and runs the same suite for real.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed")
    if not (DESKTOP / "node_modules").is_dir():
        pytest.skip("desktop dependencies are not installed; run `npm --prefix apps/desktop ci`")
    tests = sorted(str(path) for path in (DESKTOP / "tests").glob("*.test.mjs"))
    subprocess.run([node, "--test", *tests], cwd=ROOT, check=True)


def test_authoring_dom_ids_are_unique_and_controller_targets_exist() -> None:
    import re

    index = (DESKTOP / "frontend" / "index.html").read_text(encoding="utf-8")
    main = (DESKTOP / "frontend" / "js" / "main.mjs").read_text(encoding="utf-8")
    soup = BeautifulSoup(index, "html.parser")
    ids = [element["id"] for element in soup.find_all(id=True)]
    assert len(ids) == len(set(ids))
    controller_ids = set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"\)', main))
    assert controller_ids <= set(ids)


def test_desktop_accessibility_contracts_cover_navigation_and_modals() -> None:
    index = (DESKTOP / "frontend" / "index.html").read_text(encoding="utf-8")
    modal_manager = (DESKTOP / "frontend" / "js" / "core" / "modal-manager.mjs").read_text(
        encoding="utf-8"
    )
    soup = BeautifulSoup(index, "html.parser")
    skip = soup.select_one('a.skip-link[href="#app-main"]')
    assert skip is not None
    assert soup.select_one("#app-main[tabindex='-1']") is not None
    assert soup.select_one("#toast-region[aria-live='polite']") is not None

    modal_ids = {
        "onboarding-modal",
        "settings-modal",
        "help-modal",
        "command-modal",
        "book-project-modal",
        "chapter-modal",
        "recovery-modal",
        "confirm-modal",
    }
    for modal_id in modal_ids:
        modal = soup.select_one(f"#{modal_id}")
        assert modal is not None
        assert modal.get("role") == "dialog"
        assert modal.get("aria-modal") == "true"
        assert modal.get("aria-hidden") == "true"
        assert modal.get("aria-labelledby")

    for button in soup.find_all("button"):
        accessible_name = (
            button.get("aria-label")
            or button.get("title")
            or button.get("data-i18n-title")
            or button.get_text(" ", strip=True)
        )
        assert accessible_name, f"button #{button.get('id')} has no accessible name"

    assert "background.inert = active" in modal_manager
    assert 'event.key !== "Tab"' in modal_manager
    assert 'event.key === "Escape"' in modal_manager
    assert "previousFocus" in modal_manager

    # A grouping role without a name announces as an unlabelled group, which is
    # worse than no role at all.
    for grouping in soup.select('[role="radiogroup"], [role="tablist"], [role="toolbar"]'):
        assert grouping.get("aria-label") or grouping.get("aria-labelledby"), (
            f"{grouping.get('id') or grouping.get('class')} has a grouping role but no name"
        )


def test_runtime_built_controls_carry_their_own_accessible_names() -> None:
    """Controls the settings browser and menus build are named where they are built.

    None of these exist in the markup, so the static sweep above cannot see
    them. Each is created in one place, and that place is what has to attach
    the name.
    """
    main = (DESKTOP / "frontend" / "js" / "main.mjs").read_text(encoding="utf-8")
    for construct, expectation in {
        "buildToggleControl": r'setAttribute\("aria-checked"',
        "buildSwatchControl": r'setAttribute\("aria-label", choiceLabel\(choice\)\)',
        "buildOptionRow": r'reset\.setAttribute\("aria-label"',
        "renderOptionRail": r'setAttribute\("role", "tab"\)',
        "openEditorContextMenu": r'setAttribute\("role", "menuitem"\)',
    }.items():
        start = main.index(f"function {construct}")
        body = main[start : start + 3000]
        assert re.search(expectation, body), f"{construct} builds an unnamed control"

    # Both tri-state groups point at the label rendered beside them.
    assert 'aria-labelledby", `${advancedControlId(field.key)}-label`' in main
    assert 'label.id = `${advancedControlId(field.key)}-label`' in main


def test_desktop_ux_is_offline_and_exposes_guided_entry_points() -> None:
    index = (DESKTOP / "frontend" / "index.html").read_text(encoding="utf-8")
    main = (DESKTOP / "frontend" / "js" / "main.mjs").read_text(encoding="utf-8")
    styles = (DESKTOP / "frontend" / "styles.css").read_text(encoding="utf-8")
    assert 'id="template-grid"' in index
    assert 'id="settings-search"' in index
    assert 'id="restart-onboarding"' in index
    assert 'id="command-button"' in index
    assert 'id="help-button"' in index
    assert 'id="settings-button"' in index
    assert "createDocumentFromTemplate" in main
    assert "openCommandPalette" in main
    assert "openOnboarding" in main
    assert "saveSupportBundle" in main
    assert '"system.support_bundle"' in main
    assert 'event.key === "F1"' in main
    assert 'key === "p" && event.shiftKey' in main
    assert 'data-reduced-motion="reduce"' in styles
    assert 'data-theme="dark"' in styles
    assert "https://" not in index
    assert "fetch(" not in main
    # Recovery/session restore takes precedence over first-run onboarding.
    assert main.count("openOnboarding();") == 1


def _frontmatter_cases() -> list[dict[str, object]]:
    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "frontmatter_cases.json").read_text(encoding="utf-8")
    )
    return list(fixture["cases"])


@pytest.mark.parametrize("case", _frontmatter_cases(), ids=lambda case: str(case["name"]))
def test_engine_front_matter_matches_the_desktop_fixture(case: dict[str, object]) -> None:
    """The engine defines where a document body starts.

    The editor's CodeMirror block parser and the desktop outline helper are held
    to this same table by ``apps/desktop/tests/markdown-frontmatter.test.mjs``,
    so a heading cannot appear in the outline but be absent from the PDF.
    """
    from mardas_folio.markdown import FRONTMATTER_RE

    matched = FRONTMATTER_RE.match(str(case["text"])) is not None
    assert matched is bool(case["frontmatter"])


def test_editor_parses_front_matter_and_owns_its_syntax_palette() -> None:
    """CodeMirror ships a light-only palette that fails the dark workspace.

    ``defaultHighlightStyle`` renders link and code-fence tokens at 1.35:1 and
    Markdown punctuation at 1.84:1 against the dark editing surface, and
    underlines every heading and link. The editor therefore registers its own
    highlighter and reads colours from ``--cm-*`` custom properties.
    """
    editor = (DESKTOP / "editor-src" / "codemirror-editor.mjs").read_text(encoding="utf-8")
    theme = (DESKTOP / "editor-src" / "editor-theme.mjs").read_text(encoding="utf-8")
    workspace_css = (DESKTOP / "frontend" / "workspace.css").read_text(encoding="utf-8")

    live = (DESKTOP / "editor-src" / "live-preview.mjs").read_text(encoding="utf-8")

    # The engine accepts more than CommonMark and GFM: `$x$` and `$$…$$`
    # become MathJax and `[^id]` becomes a numbered footnote. Without a rule
    # for each, the editor showed them as literal punctuation in the middle of
    # a sentence, and a footnote reference rendered as a bare `^1` because the
    # brackets around it were hidden as link marks.
    assert "extensions: [frontmatter, mathAndFootnotes]" in editor
    extras = (DESKTOP / "editor-src" / "markdown-extras.mjs").read_text(encoding="utf-8")
    for node in ("InlineMath", "BlockMath", "FootnoteReference"):
        assert f'"{node}"' in extras or f"name: \"{node}\"" in extras
    assert "codeLanguages: CODE_LANGUAGES" in editor
    # The app publishes GitHub-flavoured Markdown, so the editor has to parse
    # the same dialect; `markdown()` alone is CommonMark and drops tables,
    # task lists and strikethrough from the syntax tree entirely.
    assert "base: markdownLanguage" in editor
    # Mixed Persian/English lines need their own resolved direction. The facet
    # lives with the mode extensions because it cannot measure hidden lines.
    assert "EditorView.perLineTextDirection.of(true)" in live
    assert 'attributes: { dir: "auto" }' in live
    # The theme follows the workspace instead of being fixed at startup.
    assert "setTheme(mode)" in editor
    assert "appearance.reconfigure" in editor

    assert "syntaxHighlighting(mardasHighlightStyle)" in theme
    assert "textDecoration: \"underline\"" not in theme

    assert "--cm-heading:" in workspace_css
    assert workspace_css.count("--cm-heading:") == 2, "light and dark must both declare the palette"


def test_switch_inputs_cannot_overflow_or_swallow_clicks() -> None:
    """A visually hidden switch input must not inherit ``input{width:100%}``.

    Absolutely positioned with no positioned ancestor, that rule resolved
    against the viewport and produced a 1440px-wide invisible control: the
    export view scrolled horizontally and a full-width strip of the page
    intercepted clicks.
    """
    styles = (DESKTOP / "frontend" / "styles.css").read_text(encoding="utf-8")

    def declarations(selector: str) -> dict[str, str]:
        match = re.search(rf"(?m)^{re.escape(selector)}\s*\{{([^}}]*)\}}", styles)
        assert match is not None, f"missing rule for {selector}"
        return dict(re.findall(r"([\w-]+)\s*:\s*([^;]+);?", match.group(1)))

    toggle_rule = declarations(".toggle")
    assert toggle_rule["position"] == "relative"

    input_rule = declarations(".toggle input")
    assert input_rule["width"] == "1px"
    assert input_rule["height"] == "1px"
    assert input_rule["min-height"] == "0"
    assert input_rule["pointer-events"] == "none"
    # Still focusable: display:none or visibility:hidden would drop it from the
    # tab order and break the keyboard path to the setting.
    assert input_rule.get("display") != "none"
    assert input_rule.get("visibility") != "hidden"


def test_live_preview_mode_is_presentation_only() -> None:
    """Live preview hides Markdown syntax without rewriting the document.

    The buffer has to stay plain Markdown: recovery snapshots, conflict-safe
    saving and the publishing engine all read it directly, so a WYSIWYG mode
    that edited the text to match what is displayed would corrupt the file.
    """
    live = (DESKTOP / "editor-src" / "live-preview.mjs").read_text(encoding="utf-8")
    editor = (DESKTOP / "editor-src" / "codemirror-editor.mjs").read_text(encoding="utf-8")
    index = (DESKTOP / "frontend" / "index.html").read_text(encoding="utf-8")
    main = (DESKTOP / "frontend" / "js" / "main.mjs").read_text(encoding="utf-8")

    assert "Decoration.replace" in live
    assert "EditorView.atomicRanges.of" in live
    assert ".dispatch(" not in live, "the preview layer must never write to the document"

    assert "preview.reconfigure" in editor
    assert "setMode(value)" in editor

    # Reachable from the toolbar and the command palette, and remembered.
    assert 'data-view-mode="write"' in index
    assert '"button[data-view-mode]"' in main
    assert '"view-split"' in main
    # The writing tools belong to the document, not to the window chrome.
    assert '<div class="format-bar"' in index
    assert index.index('class="format-bar"') > index.index('class="editor-pane"')
    assert "viewMode" in (DESKTOP / "frontend" / "js" / "core" / "preferences.mjs").read_text(
        encoding="utf-8"
    )


def test_every_engine_render_option_has_a_control() -> None:
    """No publishing option may be reachable only from the CLI.

    The engine accepts 53 render options; the interface used to send nine and
    the rest needed a hand-edited ``mardas.toml``. The fixture is generated from
    ``RENDER_OPTION_SPECS`` and the desktop suite holds the settings panel to
    it, so this check guards the Python side of that contract.
    """
    from mardas_folio.config import RENDER_OPTION_SPECS

    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "render_options.json").read_text(encoding="utf-8")
    )
    assert set(fixture["options"]) == set(RENDER_OPTION_SPECS), (
        "regenerate tests/fixtures/render_options.json; the engine option list moved"
    )

    schema = (
        DESKTOP / "frontend" / "js" / "core" / "render-options.mjs"
    ).read_text(encoding="utf-8")
    missing = [key for key in RENDER_OPTION_SPECS if f'key: "{key}"' not in schema]
    assert missing == [], f"these engine options have no interface control: {missing}"


def test_editor_recognises_every_callout_the_engine_publishes() -> None:
    """A callout must look like a callout while it is being written.

    The engine turns ``> [!WARNING]`` into a coloured admonition. If the editor
    only knows some of the kinds, the rest are written as plain quotations and
    the difference appears for the first time in the PDF.
    """
    engine_source = (ROOT / "src" / "mardas_folio" / "markdown.py").read_text(encoding="utf-8")
    engine_kinds = set(re.findall(r'"callout_([a-z]+)"', engine_source))
    assert engine_kinds, "the engine's callout label table moved"
    live = (DESKTOP / "editor-src" / "live-preview.mjs").read_text(encoding="utf-8")
    block = live.split("const CALLOUT_KINDS = new Set([", 1)[1].split("]);", 1)[0]
    editor_kinds = set(re.findall(r'"([a-z-]+)"', block))
    assert engine_kinds <= editor_kinds, (
        f"the editor does not recognise these callouts: {sorted(engine_kinds - editor_kinds)}"
    )

    styles = (DESKTOP / "frontend" / "workspace.css").read_text(encoding="utf-8")
    unstyled = [kind for kind in engine_kinds if f".cm-md-callout-{kind}" not in styles]
    assert unstyled == [], f"these callouts have no colour: {sorted(unstyled)}"


def test_palette_swatches_show_the_colour_the_engine_prints() -> None:
    """A palette is a colour decision, so it is offered as colour.

    The settings panel draws a swatch per palette instead of listing seven
    English words. Those swatches are only honest if they are the accents the
    renderer actually uses, so the copy in the interface is held against the
    engine's own table.
    """
    from mardas_folio.appearance import PALETTES

    main = (DESKTOP / "frontend" / "js" / "main.mjs").read_text(encoding="utf-8")
    block = main.split("const PALETTE_ACCENTS = Object.freeze({", 1)[1].split("});", 1)[0]
    shown = dict(
        re.findall(r'(\w+):\s*"(#[0-9a-fA-F]{6})"', block)
    )
    expected = {name: palette["accent"] for name, palette in PALETTES.items()}
    assert shown == expected, "the palette swatches have drifted from the engine's accents"


def test_settings_panel_explains_every_option_it_offers() -> None:
    """An option nobody can interpret is an option nobody sets.

    Every engine option carries a one-sentence help key, and every one of those
    keys has to resolve in both interface languages — an option whose
    explanation renders as ``help.margin_x`` is worse than no explanation.
    """
    schema = (
        DESKTOP / "frontend" / "js" / "core" / "render-options.mjs"
    ).read_text(encoding="utf-8")
    help_keys = set(re.findall(r'helpKey:\s*"([^"]+)"', schema))
    assert len(help_keys) >= 50, "options lost their help text"

    strings = (DESKTOP / "frontend" / "js" / "core" / "i18n.mjs").read_text(encoding="utf-8")
    for key in sorted(help_keys):
        assert strings.count(f'"{key}":') >= 2, f"{key} is not translated in both languages"


def test_editor_images_load_through_a_bounded_asset_scope() -> None:
    """Rendering local images must not hand the webview the filesystem.

    The asset protocol ships with an empty scope. Opening a document widens it
    by a bounded inventory of individual images below that document's own
    directory. Nested asset folders work without granting text or symlinks.
    """
    config = json.loads((TAURI / "tauri.conf.json").read_text(encoding="utf-8"))
    security = config["app"]["security"]
    assert security["assetProtocol"]["enable"] is True
    assert security["assetProtocol"]["scope"] == [], "the static scope must stay empty"
    assert "img-src 'self' data: asset: http://asset.localhost" in security["csp"]

    main_rs = (TAURI / "src" / "main.rs").read_text(encoding="utf-8")
    assert "fn allow_document_images" in main_rs
    assert "asset_protocol_scope()" in main_rs
    grant = main_rs.split("async fn allow_document_images", 1)[1].split("fn document_image_paths", 1)[0]
    assert ".allow_file(image)" in grant
    assert "allow_directory" not in grant, "never grant a directory wildcard"
    assert "document_image_paths(Path::new(&path), 4096)" in grant
    inventory = main_rs.split("fn document_image_paths", 1)[1].split("#[tauri::command]", 1)[0]
    assert "inspected > max_entries" in inventory
    assert "depth < 8" in inventory
    assert "kind.is_symlink()" in inventory
    assert "canonical.starts_with(&directory)" in inventory
    assert "kind.is_file()" in inventory
    assert '"png" | "jpg" | "jpeg" | "webp" | "gif" | "svg"' in inventory
    assert "canonicalize()" in main_rs, "resolve the directory before trusting it"

    main_js = (DESKTOP / "frontend" / "js" / "main.mjs").read_text(encoding="utf-8")
    assert '"allow_document_images"' in main_js
    # Remote sources and parent-directory escapes are refused in the interface
    # too, so a document cannot pull the webview off the machine.
    assert "normalized.split(\"/\").includes(\"..\")" in main_js
    assert "/^[a-z][a-z0-9+.-]*:/i" in main_js

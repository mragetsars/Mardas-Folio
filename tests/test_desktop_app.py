from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

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
from mardas_md2pdf import __version__  # noqa: E402

DESKTOP = ROOT / "apps" / "desktop"
TAURI = DESKTOP / "src-tauri"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    assert macos_config["bundle"]["targets"] == ["dmg"]
    assert "signingIdentity" not in macos_config["bundle"]["macOS"]
    assert macos_config["bundle"]["macOS"]["minimumSystemVersion"] == "14.0"
    assert linux_config["bundle"]["targets"] == ["appimage", "deb"]
    assert {"icons/icon.icns", "icons/icon.ico", "icons/icon.png"} <= set(config["bundle"]["icon"])
    assert 'name = "mardas-studio"' in cargo
    assert f'version = "{__version__}"' in cargo


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
        "workspace-toggle-preview",
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

    for element_id in ("workspace-toggle-sidebar", "workspace-toggle-preview"):
        button = soup.select_one(f"#{element_id}")
        assert button is not None
        assert button.get("aria-pressed") == "true"
        assert button.get("aria-controls")

    for element_id in ("sidebar-resizer", "preview-resizer"):
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
    assert 'grid-template-columns: var(--sidebar-track) var(--sidebar-divider) minmax(360px, 1fr) var(--preview-divider) var(--preview-track)' in workspace_css
    assert '@media (max-width: 1060px)' in workspace_css
    assert '.author-sidebar:focus-within .sidebar-panel.active' in workspace_css
    assert '@media (max-width: 980px)' in workspace_css
    assert '@media (max-width: 900px)' in workspace_css
    assert 'padding-left: calc(var(--tab-sidebar-offset) + 10px)' in workspace_css
    assert 'padding-right: calc(var(--tab-preview-offset) + 10px)' in workspace_css


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


def test_installer_verifier_accepts_versioned_pe_payload(tmp_path: Path) -> None:
    path = tmp_path / f"Mardas-Studio-{__version__}-windows-x86_64-setup.exe"
    path.write_bytes(b"MZ" + b"\0" * (MIN_INSTALLER_BYTES + 32))
    payload = verify_installer(path, expected_version=__version__)
    assert payload["version"] == __version__
    assert payload["architecture"] == "x86_64"
    assert payload["sha256"] == _sha256(path)


def test_installer_verifier_rejects_symlink_input(tmp_path: Path) -> None:
    name = f"Mardas-Studio-{__version__}-windows-x86_64-setup.exe"
    target = tmp_path / "real" / name
    target.parent.mkdir()
    target.write_bytes(b"MZ" + b"\0" * (MIN_INSTALLER_BYTES + 32))
    link = tmp_path / name
    _symlink_or_skip(link, target)

    with pytest.raises(ValueError, match="missing or unsafe"):
        verify_installer(link, expected_version=__version__)


def test_node_frontend_contracts() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed")
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

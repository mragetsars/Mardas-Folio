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
    assert {"md", "markdown"}.issubset(set(config["bundle"]["fileAssociations"][0]["ext"]))
    assert config["bundle"]["windows"]["webviewInstallMode"]["type"] == "downloadBootstrapper"
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
    ):
        assert command in main
    assert "Stdio::piped()" in sidecar
    assert "MARDAS_RUNTIME_ROOT" in sidecar
    assert "mardas-sidecar.exe" in sidecar
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
    ):
        assert f'id="{element_id}"' in index
    assert 'type="module" src="./js/main.mjs"' in index
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
        "templates.mjs",
        "command-palette.mjs",
        "modal-manager.mjs",
    ):
        assert (DESKTOP / "frontend" / "js" / "core" / module).is_file()
    assert "fetch(" not in main
    assert "window.open" not in main
    assert "devUrl" not in index
    assert "https://" not in index
    assert index.count("http://ipc.localhost") == 1


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
    assert 'event.key === "F1"' in main
    assert 'key === "p" && event.shiftKey' in main
    assert 'data-reduced-motion="reduce"' in styles
    assert 'data-theme="dark"' in styles
    assert "https://" not in index
    assert "fetch(" not in main
    # Recovery/session restore takes precedence over first-run onboarding.
    assert main.count("openOnboarding();") == 1

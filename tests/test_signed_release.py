from __future__ import annotations

import importlib.util
import io
import json
import os
import tarfile
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load(name: str):
    path = SCRIPTS / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_payload(path: Path, prefix: bytes) -> None:
    path.write_bytes(prefix + os.urandom(70 * 1024))


def _write_mac_updater(path: Path) -> None:
    data = os.urandom(90 * 1024)
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo("Mardas Studio.app/Contents/MacOS/mardas-studio")
        info.mode = 0o755
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))


def _signed_release_files(root: Path, version: str) -> None:
    _write_payload(
        root / f"Mardas-Studio-{version}-windows-x86_64-setup.exe",
        b"MZ",
    )
    _write_payload(
        root / f"Mardas-Studio-{version}-linux-x86_64.AppImage",
        b"\x7fELF",
    )
    for arch in ("arm64", "x86_64"):
        _write_mac_updater(
            root / f"Mardas-Studio-{version}-macos-{arch}-updater.tar.gz"
        )
    for payload in list(root.iterdir()):
        (root / f"{payload.name}.sig").write_text(
            f"signed:{payload.name}", encoding="utf-8"
        )


def test_signed_update_assembly_uses_verified_native_payloads(tmp_path: Path) -> None:
    module = _load("assemble_signed_updates.py")
    version = "1.30.0"
    _signed_release_files(tmp_path, version)

    latest = module.assemble(
        tmp_path,
        version=version,
        repository="mragetsars/Mardas-MD2PDF",
        tag=f"v{version}",
        notes="Release notes",
        pub_date="2026-08-08T00:00:00Z",
    )
    payload = json.loads(latest.read_text(encoding="utf-8"))

    assert payload["version"] == version
    assert sorted(payload["platforms"]) == [
        "darwin-aarch64",
        "darwin-x86_64",
        "linux-x86_64",
        "windows-x86_64",
    ]
    assert payload["platforms"]["windows-x86_64"]["url"].endswith(
        f"/v{version}/Mardas-Studio-{version}-windows-x86_64-setup.exe"
    )
    assert payload["platforms"]["darwin-aarch64"]["url"].endswith(
        f"/v{version}/Mardas-Studio-{version}-macos-arm64-updater.tar.gz"
    )
    assert "signed:" in payload["platforms"]["linux-x86_64"]["signature"]


def test_signed_update_assembly_rejects_missing_signature_and_tag_mismatch(tmp_path: Path) -> None:
    module = _load("assemble_signed_updates.py")
    version = "1.30.0"
    _signed_release_files(tmp_path, version)
    (tmp_path / f"Mardas-Studio-{version}-linux-x86_64.AppImage.sig").unlink()

    with pytest.raises(ValueError, match="signature"):
        module.assemble(tmp_path, version=version)

    _signed_release_files(tmp_path, version)
    with pytest.raises(ValueError, match="exactly"):
        module.assemble(tmp_path, version=version, tag="v9.9.9")


def test_release_preflight_separates_draft_and_public_signing_requirements() -> None:
    module = _load("release_preflight.py")
    draft_env = {
        "TAURI_SIGNING_PRIVATE_KEY": "private",
        "MARDAS_UPDATER_PUBKEY": "public",
        "MARDAS_UPDATE_ENDPOINT": "https://example.invalid/latest.json",
    }

    draft = module.report(module.evaluate(draft_env, mode="draft"), mode="draft")
    assert draft["ready"] is True
    assert draft["blocking"] == []

    public = module.report(module.evaluate(draft_env, mode="public"), mode="public")
    assert public["ready"] is False
    assert set(public["blocking"]) == {
        "windows_code_signing",
        "macos_code_signing",
        "macos_notarization",
    }

    production_env = {
        **draft_env,
        "MARDAS_WINDOWS_CERTIFICATE_THUMBPRINT": "thumbprint",
        "APPLE_SIGNING_IDENTITY": "Developer ID Application: Example",
        "APPLE_API_ISSUER": "issuer",
        "APPLE_API_KEY": "key",
        "APPLE_API_KEY_PATH": "/secure/key.p8",
    }
    production = module.report(
        module.evaluate(production_env, mode="public"), mode="public"
    )
    assert production["ready"] is True


def test_release_preflight_rejects_insecure_update_endpoint() -> None:
    module = _load("release_preflight.py")
    env = {
        "TAURI_SIGNING_PRIVATE_KEY": "private",
        "MARDAS_UPDATER_PUBKEY": "public",
        "MARDAS_UPDATE_ENDPOINT": "http://example.invalid/latest.json",
    }
    payload = module.report(module.evaluate(env, mode="draft"), mode="draft")
    assert payload["ready"] is False
    assert "updater_https_endpoint" in payload["blocking"]


def test_release_note_extraction_is_version_scoped() -> None:
    module = _load("extract_release_notes.py")
    text = """# Changelog

## [1.30.0] - 2026-08-08

### Added
- Signed updates.

## [1.29.0] - 2026-08-07

### Added
- Old feature.
"""
    notes = module.extract_release_notes(text, version="1.30.0")
    assert notes.startswith("# Mardas Studio 1.30.0")
    assert "Signed updates." in notes
    assert "Old feature." not in notes
    with pytest.raises(ValueError, match="does not contain"):
        module.extract_release_notes(text, version="2.0.0")


def test_release_workflow_stages_signed_updater_assets_in_draft_only() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    for marker in (
        "release-preflight:",
        "python scripts/release_preflight.py --mode draft",
        "TAURI_SIGNING_PRIVATE_KEY",
        "MARDAS_UPDATER_PUBKEY",
        "--create-updater-artifacts",
        "assemble_signed_updates.py",
        "--require-update-manifest",
        "publish-draft:",
        "gh release create",
        "--draft",
        "--verify-tag",
        "Refusing to overwrite a published GitHub Release",
    ):
        assert marker in workflow
    assert "gh release create" in workflow
    assert "gh release upload" in workflow
    assert "gh release edit" in workflow
    assert "gh release create" not in workflow.split("publish-draft:", 1)[0]



def test_native_builder_requires_https_and_materializes_updater_config(tmp_path: Path) -> None:
    module = _load("build_native_desktop.py")
    assert module._validate_update_endpoint("https://example.invalid/latest.json") == (
        "https://example.invalid/latest.json"
    )
    with pytest.raises(SystemExit, match="HTTPS"):
        module._validate_update_endpoint("http://example.invalid/latest.json")
    with pytest.raises(SystemExit, match="public key"):
        module._read_updater_pubkey(None, {})
    assert module._read_updater_pubkey(None, {"MARDAS_UPDATER_PUBKEY": "public"}) == "public"

    config = module._updater_build_config(tmp_path)
    try:
        payload = json.loads(config.read_text(encoding="utf-8"))
        assert payload == {"bundle": {"createUpdaterArtifacts": True}}
    finally:
        config.unlink(missing_ok=True)

def test_updater_rust_boundary_is_secret_driven_and_https_only() -> None:
    updates = (
        ROOT / "apps" / "desktop" / "src-tauri" / "src" / "updates.rs"
    ).read_text(encoding="utf-8")
    cargo = (ROOT / "apps" / "desktop" / "src-tauri" / "Cargo.toml").read_text(
        encoding="utf-8"
    )
    main = (ROOT / "apps" / "desktop" / "src-tauri" / "src" / "main.rs").read_text(
        encoding="utf-8"
    )

    assert 'option_env!("MARDAS_UPDATER_PUBKEY")' in updates
    assert 'option_env!("MARDAS_UPDATE_ENDPOINT")' in updates
    assert 'parsed.scheme() != "https"' in updates
    assert "download_and_install" in updates
    assert "desktop-update-progress" in updates
    assert "TAURI_SIGNING_PRIVATE_KEY" not in updates
    assert 'tauri-plugin-updater = "=2.10.1"' in cargo
    assert "updates::updater_status" in main
    assert "updates::updater_check" in main
    assert "updates::updater_install" in main

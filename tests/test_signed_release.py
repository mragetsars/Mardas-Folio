from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import subprocess
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
        info = tarfile.TarInfo("Mardas Folio.app/Contents/MacOS/mardas-folio")
        info.mode = 0o755
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))


def _signed_release_files(root: Path, version: str) -> None:
    _write_payload(
        root / f"Mardas-Folio-{version}-windows-x86_64-setup.exe",
        b"MZ",
    )
    _write_payload(
        root / f"Mardas-Folio-{version}-linux-x86_64.AppImage",
        b"\x7fELF",
    )
    for arch in ("arm64", "x86_64"):
        _write_mac_updater(
            root / f"Mardas-Folio-{version}-macos-{arch}-updater.tar.gz"
        )
    for payload in list(root.iterdir()):
        (root / f"{payload.name}.sig").write_text(
            f"signed:{payload.name}", encoding="utf-8"
        )


def _fake_pkcs12() -> str:
    return base64.b64encode(b"\x30" + b"test-pkcs12" * 64).decode("ascii")


def _fake_api_key() -> str:
    return "-----BEGIN PRIVATE KEY-----\n" + ("A" * 128) + "\n-----END PRIVATE KEY-----\n"


def test_signed_update_assembly_uses_verified_native_payloads(tmp_path: Path) -> None:
    module = _load("assemble_signed_updates.py")
    version = "1.30.0"
    _signed_release_files(tmp_path, version)

    latest = module.assemble(
        tmp_path,
        version=version,
        repository="mragetsars/Mardas-Folio",
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
        f"/v{version}/Mardas-Folio-{version}-windows-x86_64-setup.exe"
    )
    assert payload["platforms"]["darwin-aarch64"]["url"].endswith(
        f"/v{version}/Mardas-Folio-{version}-macos-arm64-updater.tar.gz"
    )
    assert "signed:" in payload["platforms"]["linux-x86_64"]["signature"]


def test_signed_update_assembly_rejects_missing_signature_and_tag_mismatch(tmp_path: Path) -> None:
    module = _load("assemble_signed_updates.py")
    version = "1.30.0"
    _signed_release_files(tmp_path, version)
    (tmp_path / f"Mardas-Folio-{version}-linux-x86_64.AppImage.sig").unlink()

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
        "MARDAS_WINDOWS_CERTIFICATE": _fake_pkcs12(),
        "MARDAS_WINDOWS_CERTIFICATE_PASSWORD": "windows-password",
        "MARDAS_WINDOWS_CERTIFICATE_THUMBPRINT": "A" * 40,
        "MARDAS_WINDOWS_DIGEST_ALGORITHM": "sha256",
        "MARDAS_WINDOWS_TIMESTAMP_URL": "https://timestamp.example.invalid",
        "APPLE_CERTIFICATE": _fake_pkcs12(),
        "APPLE_CERTIFICATE_PASSWORD": "certificate-password",
        "KEYCHAIN_PASSWORD": "keychain-password",
        "APPLE_SIGNING_IDENTITY": "Developer ID Application: Example (ABCDEFGHIJ)",
        "APPLE_API_ISSUER": "01234567-89ab-cdef-0123-456789abcdef",
        "APPLE_API_KEY": "K123456789",
        "APPLE_API_KEY_P8": _fake_api_key(),
        "APPLE_TEAM_ID": "ABCDEFGHIJ",
    }
    production = module.report(
        module.evaluate(production_env, mode="public"), mode="public"
    )
    assert production["ready"] is True

    apple_id_environment = dict(production_env)
    for name in ("APPLE_API_ISSUER", "APPLE_API_KEY", "APPLE_API_KEY_P8"):
        apple_id_environment.pop(name)
    apple_id_environment.update(
        {
            "APPLE_ID": "release@example.invalid",
            "APPLE_PASSWORD": "app-specific-password",
        }
    )
    apple_id_release = module.report(
        module.evaluate(apple_id_environment, mode="public"), mode="public"
    )
    assert apple_id_release["ready"] is True

    production_env["MARDAS_WINDOWS_CERTIFICATE_THUMBPRINT"] = "not-a-thumbprint"
    malformed = module.report(
        module.evaluate(production_env, mode="public"), mode="public"
    )
    assert "windows_code_signing" in malformed["blocking"]


def test_release_preflight_rejects_ambiguous_notarization_and_free_sign_command() -> None:
    module = _load("release_preflight.py")
    env = {
        "TAURI_SIGNING_PRIVATE_KEY": "private",
        "MARDAS_UPDATER_PUBKEY": "public",
        "MARDAS_WINDOWS_SIGN_COMMAND": "unsafe-tool %1",
        "APPLE_SIGNING_IDENTITY": "Developer ID Application: Example (ABCDEFGHIJ)",
        "APPLE_API_ISSUER": "01234567-89ab-cdef-0123-456789abcdef",
        "APPLE_API_KEY": "K123456789",
        "APPLE_API_KEY_P8": _fake_api_key(),
        "APPLE_ID": "release@example.invalid",
        "APPLE_PASSWORD": "app-password",
        "APPLE_TEAM_ID": "ABCDEFGHIJ",
    }
    payload = module.report(module.evaluate(env, mode="public"), mode="public")
    assert "windows_code_signing" in payload["blocking"]
    assert "macos_notarization" in payload["blocking"]


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
    assert notes.startswith("# Mardas Folio 1.30.0")
    assert "Signed updates." in notes
    assert "Old feature." not in notes
    with pytest.raises(ValueError, match="does not contain"):
        module.extract_release_notes(text, version="2.0.0")


def test_release_workflow_stages_signed_updater_assets_in_draft_only() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")

    for marker in (
        "release-preflight:",
        "python scripts/release_preflight.py --mode \"$MARDAS_RELEASE_MODE\"",
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
        "release_mode:",
        "MARDAS_RELEASE_MODE: ${{ inputs.release_mode || 'draft' }}",
        "Import-PfxCertificate",
        "MARDAS_WINDOWS_CERTIFICATE_THUMBPRINT",
        "APPLE_SIGNING_IDENTITY",
        "security set-key-partition-list",
        "APPLE_API_KEY_PATH",
        "Notarize and staple macOS disk image",
        "scripts/notarize_macos_dmg.py",
        "scripts/verify_platform_signing.py",
        "--verify-evidence-set",
        "Mardas-Folio-*-signing-evidence.json",
    ):
        assert marker in workflow
    assert "MARDAS_WINDOWS_SIGN_COMMAND" not in workflow
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

    apple_id_config, apple_id_contract = module._native_build_config(
        tmp_path,
        create_updater_artifacts=False,
        release_mode="public",
        platform_name="macos",
        environment={
            "APPLE_SIGNING_IDENTITY": "Developer ID Application: Example (ABCDEFGHIJ)",
            "APPLE_ID": "release@example.invalid",
            "APPLE_PASSWORD": "must-not-be-serialized",
            "APPLE_TEAM_ID": "ABCDEFGHIJ",
        },
    )
    assert apple_id_config is not None
    try:
        assert apple_id_contract["notarization_method"] == "apple-id"
        assert "must-not-be-serialized" not in apple_id_config.read_text(encoding="utf-8")
    finally:
        apple_id_config.unlink(missing_ok=True)


def test_native_builder_materializes_only_public_tauri_signing_settings(
    tmp_path: Path,
) -> None:
    module = _load("build_native_desktop.py")
    endpoint = "https://updates.example.invalid/latest.json"
    windows_environment = {
        "MARDAS_WINDOWS_CERTIFICATE_THUMBPRINT": "a" * 40,
        "MARDAS_WINDOWS_DIGEST_ALGORITHM": "sha256",
        "MARDAS_WINDOWS_TIMESTAMP_URL": "https://timestamp.example.invalid",
        "MARDAS_WINDOWS_CERTIFICATE_PASSWORD": "must-not-be-serialized",
        "MARDAS_WINDOWS_SIGN_COMMAND": "unsafe-tool %1",
        # The updater public key is not a secret — it ships inside every
        # binary — and the bundler rejects an empty one.
        "MARDAS_UPDATER_PUBKEY": "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXkK",
        "MARDAS_UPDATE_ENDPOINT": endpoint,
    }
    config, contract = module._native_build_config(
        tmp_path,
        create_updater_artifacts=True,
        release_mode="public",
        platform_name="windows",
        environment=windows_environment,
    )
    assert config is not None
    try:
        payload = json.loads(config.read_text(encoding="utf-8"))
        assert payload == {
            "bundle": {
                "createUpdaterArtifacts": True,
                "windows": {
                    "certificateThumbprint": "A" * 40,
                    "digestAlgorithm": "sha256",
                    "timestampUrl": "https://timestamp.example.invalid",
                },
            },
            "plugins": {
                "updater": {
                    "pubkey": windows_environment["MARDAS_UPDATER_PUBKEY"],
                    "endpoints": [endpoint],
                }
            },
        }
        assert "must-not-be-serialized" not in config.read_text(encoding="utf-8")
        assert "signCommand" not in config.read_text(encoding="utf-8")
        assert contract["status"] == "pending-verification"
        assert contract["verified"] is False
    finally:
        config.unlink(missing_ok=True)

    draft_config, draft_contract = module._native_build_config(
        tmp_path,
        create_updater_artifacts=False,
        release_mode="draft",
        platform_name="windows",
        environment={},
    )
    assert draft_config is None
    assert draft_contract["status"] == "not-requested"
    assert draft_contract["verified"] is False


def test_native_builder_validates_macos_notarization_key_without_serializing_it(
    tmp_path: Path,
) -> None:
    module = _load("build_native_desktop.py")
    key = tmp_path / "AuthKey_K123456789.p8"
    key.write_text(_fake_api_key(), encoding="utf-8")
    environment = {
        "APPLE_SIGNING_IDENTITY": "Developer ID Application: Example (ABCDEFGHIJ)",
        "APPLE_API_ISSUER": "01234567-89ab-cdef-0123-456789abcdef",
        "APPLE_API_KEY": "K123456789",
        "APPLE_API_KEY_PATH": str(key),
        "APPLE_TEAM_ID": "ABCDEFGHIJ",
    }
    config, contract = module._native_build_config(
        tmp_path,
        create_updater_artifacts=False,
        release_mode="public",
        platform_name="macos",
        environment=environment,
    )
    assert config is not None
    try:
        payload = json.loads(config.read_text(encoding="utf-8"))
        assert payload == {
            "bundle": {
                "macOS": {
                    "signingIdentity": "Developer ID Application: Example (ABCDEFGHIJ)"
                }
            }
        }
        assert str(key) not in config.read_text(encoding="utf-8")
        assert contract["notarization_method"] == "app-store-connect-api"
    finally:
        config.unlink(missing_ok=True)


def test_native_builder_removes_temporary_config_when_tauri_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load("build_native_desktop.py")
    config = tmp_path / ".mardas-native-build-test.json"
    config.write_text("{}", encoding="utf-8")

    def failed(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(module.subprocess, "run", failed)
    with pytest.raises(subprocess.CalledProcessError):
        module._run_tauri_build(
            ["cargo", "tauri", "build", "--", "--locked"],
            environment={},
            build_config=config,
        )
    assert not config.exists()


def test_native_builder_requires_a_regular_locked_cargo_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load("build_native_desktop.py")
    assert module.CARGO_LOCK.is_file()
    module.require_cargo_lock()

    missing = tmp_path / "Cargo.lock"
    monkeypatch.setattr(module, "CARGO_LOCK", missing)
    with pytest.raises(SystemExit, match="regular committed"):
        module.require_cargo_lock()

    missing.write_text("version = 2\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="invalid"):
        module.require_cargo_lock()

    with pytest.raises(SystemExit, match="must use"):
        module._run_tauri_build(
            ["cargo", "tauri", "build"],
            environment={},
            build_config=None,
        )

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

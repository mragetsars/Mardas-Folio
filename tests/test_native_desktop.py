from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path

import pytest

from scripts.verify_native_desktop import (
    MIN_NATIVE_BYTES,
    classify_native_artifact,
    verify_native_artifact,
)


def _pad(prefix: bytes, *, size: int = MIN_NATIVE_BYTES + 4096) -> bytes:
    if len(prefix) > size:
        raise ValueError("prefix too large")
    return prefix + b"\0" * (size - len(prefix))


def test_updater_build_config_carries_the_public_key(tmp_path: Path) -> None:
    """A release build must put the real key into the configuration.

    The committed `tauri.conf.json` keeps an empty `plugins.updater.pubkey` so
    ordinary source builds stay offline, and the Rust side reads the real key
    from a compile-time variable. But `tauri-plugin-updater` validates the
    configured key too, and an empty one fails the build outright with
    "Missing comment in public key" — which is how every native desktop job
    failed the first time a release ran with an updater key configured.
    """
    from scripts.build_native_desktop import _native_build_config

    endpoint = "https://github.com/mragetsars/Mardas-Folio/releases/latest/download/latest.json"
    environment = {
        "MARDAS_UPDATER_PUBKEY": "dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXkK",
        "MARDAS_UPDATE_ENDPOINT": endpoint,
    }

    path, _ = _native_build_config(
        tmp_path,
        create_updater_artifacts=True,
        release_mode="draft",
        platform_name="linux",
        environment=environment,
    )

    assert path is not None
    config = json.loads(path.read_text(encoding="utf-8"))
    assert config["bundle"]["createUpdaterArtifacts"] is True
    assert config["plugins"]["updater"]["pubkey"] == environment["MARDAS_UPDATER_PUBKEY"]
    assert config["plugins"]["updater"]["endpoints"] == [endpoint]

    # Without updater artifacts there is nothing to configure, and the build
    # must stay on the committed offline configuration.
    unsigned, _ = _native_build_config(
        tmp_path,
        create_updater_artifacts=False,
        release_mode="draft",
        platform_name="linux",
        environment={},
    )
    assert unsigned is None


def test_blank_signing_credentials_are_removed_from_the_build_environment() -> None:
    """An empty credential must look absent, not present-and-empty.

    Tauri treats a *defined* `APPLE_SIGNING_IDENTITY` as an instruction to
    codesign, so forwarding an unconfigured secret makes it run
    `codesign --sign ""` and fail with "The specified item could not be found
    in the keychain". Both macOS release jobs failed that way while the CI
    jobs, which never define the variable at all, built fine.
    """
    from scripts.build_native_desktop import _drop_empty_signing_variables

    environment = {
        "APPLE_SIGNING_IDENTITY": "",
        "APPLE_CERTIFICATE": "   ",
        "KEYCHAIN_PASSWORD": "",
        "MARDAS_WINDOWS_CERTIFICATE_THUMBPRINT": "",
        "APPLE_TEAM_ID": "ABCDE12345",
        "PATH": "/usr/bin",
    }

    _drop_empty_signing_variables(environment)

    assert "APPLE_SIGNING_IDENTITY" not in environment
    assert "APPLE_CERTIFICATE" not in environment
    assert "KEYCHAIN_PASSWORD" not in environment
    assert "MARDAS_WINDOWS_CERTIFICATE_THUMBPRINT" not in environment
    # A configured credential must survive, or public releases cannot sign.
    assert environment["APPLE_TEAM_ID"] == "ABCDE12345"
    assert environment["PATH"] == "/usr/bin"


def test_macos_updater_needs_the_app_target_built() -> None:
    """macOS publishes a DMG but the updater payload comes from `app`.

    Asked for `dmg` alone with `createUpdaterArtifacts` set, Tauri warns that
    no updater-enabled target was built, deletes the `.app` after building the
    disk image, and produces no `.app.tar.gz` at all — which failed both macOS
    release jobs. `app` is a build input, so it must not appear in the list of
    artifacts that get published.
    """
    from scripts.build_native_desktop import default_bundles, updater_build_targets

    macos = default_bundles("macos")
    assert macos == ("dmg",)

    with_updater = updater_build_targets("macos", macos, create_updater_artifacts=True)
    assert with_updater == ("app", "dmg")
    assert "app" not in macos, "the published artifact list must stay the DMG alone"

    # Without updater artifacts there is nothing extra to build.
    assert updater_build_targets("macos", macos, create_updater_artifacts=False) == ("dmg",)

    # NSIS and AppImage are already updater-enabled; they must not be altered.
    for platform_name in ("windows", "linux"):
        bundles = default_bundles(platform_name)
        assert (
            updater_build_targets(platform_name, bundles, create_updater_artifacts=True) == bundles
        )


def test_native_artifact_classification() -> None:
    version = "1.29.0"
    cases = {
        f"Mardas-Folio-{version}-windows-x86_64-setup.exe": ("desktop-installer", "windows"),
        f"Mardas-Folio-{version}-windows-x86_64-portable.zip": ("desktop-portable", "windows"),
        f"Mardas-Folio-{version}-macos-arm64.dmg": ("desktop-dmg", "macos"),
        f"Mardas-Folio-{version}-linux-x86_64.AppImage": ("desktop-appimage", "linux"),
        f"Mardas-Folio-{version}-linux-x86_64.deb": ("desktop-deb", "linux"),
    }
    for name, expected in cases.items():
        kind, platform_name, _architecture = classify_native_artifact(
            name, expected_version=version
        )
        assert (kind, platform_name) == expected


def test_native_binary_signatures_are_verified(tmp_path: Path) -> None:
    version = "1.29.0"
    installer = tmp_path / f"Mardas-Folio-{version}-windows-x86_64-setup.exe"
    installer.write_bytes(_pad(b"MZ"))
    appimage = tmp_path / f"Mardas-Folio-{version}-linux-x86_64.AppImage"
    appimage.write_bytes(_pad(b"\x7fELF"))
    deb = tmp_path / f"Mardas-Folio-{version}-linux-x86_64.deb"
    deb.write_bytes(_pad(b"!<arch>\n"))
    dmg = tmp_path / f"Mardas-Folio-{version}-macos-arm64.dmg"
    body = bytearray(_pad(b"DMG"))
    body[-512:-508] = b"koly"
    dmg.write_bytes(body)

    assert verify_native_artifact(installer, expected_version=version)["kind"] == "desktop-installer"
    assert verify_native_artifact(appimage, expected_version=version)["kind"] == "desktop-appimage"
    assert verify_native_artifact(deb, expected_version=version)["kind"] == "desktop-deb"
    assert verify_native_artifact(dmg, expected_version=version)["kind"] == "desktop-dmg"

    installer.write_bytes(_pad(b"NO"))
    with pytest.raises(ValueError, match="PE header"):
        verify_native_artifact(installer, expected_version=version)


def test_native_artifact_verifier_rejects_symlink_input(tmp_path: Path) -> None:
    version = "1.29.0"
    name = f"Mardas-Folio-{version}-linux-x86_64.AppImage"
    target = tmp_path / "real" / name
    target.parent.mkdir()
    target.write_bytes(_pad(b"\x7fELF"))
    link = tmp_path / name
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symbolic links are unavailable: {exc}")

    with pytest.raises(ValueError, match="missing or unsafe"):
        verify_native_artifact(link, expected_version=version)


def test_portable_archive_requires_exact_integrity_manifest(tmp_path: Path) -> None:
    version = "1.29.0"
    architecture = "x86_64"
    root = f"Mardas-Folio-{version}-windows-{architecture}-portable"
    path = tmp_path / f"{root}.zip"
    files = {
        "Mardas Folio.exe": b"MZ" + os.urandom(MIN_NATIVE_BYTES + 4096),
        "README.txt": b"portable\n",
        "sidecar/runtime-manifest.json": b'{"version":"1.29.0"}\n',
        "sidecar/mardas-sidecar.exe": b"MZsidecar",
    }
    inventory = [
        {"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, data in sorted(files.items())
    ]
    manifest = {
        "schema_version": 1,
        "product": "Mardas Folio portable",
        "version": version,
        "platform": "windows",
        "architecture": architecture,
        "webview2_bundled": False,
        "files": inventory,
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(f"{root}/{name}", data)
        archive.writestr(
            f"{root}/PORTABLE-MANIFEST.json",
            json.dumps(manifest).encode("utf-8"),
        )

    payload = verify_native_artifact(path, expected_version=version)
    assert payload["kind"] == "desktop-portable"
    assert payload["webview2_bundled"] is False

    with zipfile.ZipFile(path, "a") as archive:
        archive.writestr(f"{root}/unexpected.txt", b"tamper")
    with pytest.raises(ValueError, match="exactly describe"):
        verify_native_artifact(path, expected_version=version)

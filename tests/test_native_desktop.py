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

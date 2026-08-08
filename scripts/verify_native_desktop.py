#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

MIN_NATIVE_BYTES = 64 * 1024
MAX_NATIVE_BYTES = 4 * 1024 * 1024 * 1024
MAX_PORTABLE_FILES = 25_000
MAX_PORTABLE_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024

_PATTERNS = (
    ("desktop-installer", "windows", re.compile(
        r"^Mardas-Studio-(?P<version>[^-]+)-windows-(?P<arch>[^-]+)-setup\.exe$"
    )),
    ("desktop-portable", "windows", re.compile(
        r"^Mardas-Studio-(?P<version>[^-]+)-windows-(?P<arch>[^-]+)-portable\.zip$"
    )),
    ("desktop-dmg", "macos", re.compile(
        r"^Mardas-Studio-(?P<version>[^-]+)-macos-(?P<arch>[^-]+)\.dmg$"
    )),
    ("desktop-appimage", "linux", re.compile(
        r"^Mardas-Studio-(?P<version>[^-]+)-linux-(?P<arch>[^-]+)\.AppImage$"
    )),
    ("desktop-deb", "linux", re.compile(
        r"^Mardas-Studio-(?P<version>[^-]+)-linux-(?P<arch>[^-]+)\.deb$"
    )),
    ("desktop-macos-updater", "macos", re.compile(
        r"^Mardas-Studio-(?P<version>[^-]+)-macos-(?P<arch>[^-]+)-updater\.tar\.gz$"
    )),
    ("desktop-update-signature", "windows", re.compile(
        r"^Mardas-Studio-(?P<version>[^-]+)-windows-(?P<arch>[^-]+)-setup\.exe\.sig$"
    )),
    ("desktop-update-signature", "linux", re.compile(
        r"^Mardas-Studio-(?P<version>[^-]+)-linux-(?P<arch>[^-]+)\.AppImage\.sig$"
    )),
    ("desktop-update-signature", "macos", re.compile(
        r"^Mardas-Studio-(?P<version>[^-]+)-macos-(?P<arch>[^-]+)-updater\.tar\.gz\.sig$"
    )),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_member(name: str) -> PurePosixPath:
    pure = PurePosixPath(name.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ValueError(f"Unsafe portable ZIP path: {name!r}")
    return pure


def classify_native_artifact(name: str, *, expected_version: str) -> tuple[str, str, str]:
    for kind, platform_name, pattern in _PATTERNS:
        match = pattern.fullmatch(name)
        if match is None:
            continue
        if match.group("version") != expected_version:
            raise ValueError("Native desktop artifact version does not match the release")
        return kind, platform_name, match.group("arch")
    raise ValueError(f"Unrecognized native desktop artifact name: {name}")


def _verify_portable(path: Path, *, expected_version: str, architecture: str) -> dict[str, Any]:
    expected_root = f"Mardas-Studio-{expected_version}-windows-{architecture}-portable"
    with zipfile.ZipFile(path) as archive:
        infos = [item for item in archive.infolist() if not item.is_dir()]
        if not infos or len(infos) > MAX_PORTABLE_FILES:
            raise ValueError("Portable archive file inventory is empty or too large")
        if sum(item.file_size for item in infos) > MAX_PORTABLE_UNCOMPRESSED_BYTES:
            raise ValueError("Portable archive expands beyond the allowed size")
        names: set[str] = set()
        for item in infos:
            name = _safe_member(item.filename).as_posix()
            if name in names:
                raise ValueError(f"Duplicate portable archive member: {name}")
            names.add(name)
            mode = (item.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ValueError(f"Portable archive contains a symlink: {name}")
        required = {
            f"{expected_root}/Mardas Studio.exe",
            f"{expected_root}/PORTABLE-MANIFEST.json",
            f"{expected_root}/sidecar/runtime-manifest.json",
        }
        missing = sorted(required - names)
        if missing:
            raise ValueError("Portable archive is missing required files: " + ", ".join(missing))
        manifest = json.loads(
            archive.read(f"{expected_root}/PORTABLE-MANIFEST.json").decode("utf-8")
        )
        if manifest.get("schema_version") != 1:
            raise ValueError("Portable manifest schema is unsupported")
        if manifest.get("version") != expected_version:
            raise ValueError("Portable manifest version is incorrect")
        if manifest.get("platform") != "windows" or manifest.get("architecture") != architecture:
            raise ValueError("Portable manifest platform metadata is incorrect")
        if manifest.get("webview2_bundled") is not False:
            raise ValueError("Portable archive must not claim to bundle WebView2")
        inventory = manifest.get("files")
        if not isinstance(inventory, list) or not inventory:
            raise ValueError("Portable manifest file inventory is invalid")
        expected_inventory_names = names - {f"{expected_root}/PORTABLE-MANIFEST.json"}
        observed_inventory_names: set[str] = set()
        for item in inventory:
            if not isinstance(item, dict):
                raise ValueError("Portable manifest file record is invalid")
            relative = str(item.get("path", ""))
            member_name = f"{expected_root}/{_safe_member(relative).as_posix()}"
            if member_name in observed_inventory_names:
                raise ValueError(f"Duplicate portable manifest path: {relative}")
            observed_inventory_names.add(member_name)
            if member_name not in names:
                raise ValueError(f"Portable manifest references a missing file: {relative}")
            data = archive.read(member_name)
            if int(item.get("size", -1)) != len(data):
                raise ValueError(f"Portable member size mismatch: {relative}")
            if str(item.get("sha256", "")) != hashlib.sha256(data).hexdigest():
                raise ValueError(f"Portable member checksum mismatch: {relative}")
        if observed_inventory_names != expected_inventory_names:
            raise ValueError("Portable manifest does not exactly describe the archive")
    return {"portable_manifest": True, "webview2_bundled": False}


def verify_native_artifact(path: Path, *, expected_version: str) -> dict[str, Any]:
    candidate = path.expanduser()
    metadata = candidate.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"Native desktop artifact is missing or unsafe: {candidate}")
    path = candidate.resolve(strict=True)
    kind, platform_name, architecture = classify_native_artifact(
        path.name, expected_version=expected_version
    )
    size = path.stat().st_size
    if kind == "desktop-update-signature":
        if size <= 0 or size > 64 * 1024:
            raise ValueError("Updater signature is empty or exceeds the size limit")
        try:
            signature = path.read_text(encoding="utf-8").strip()
        except UnicodeDecodeError as exc:
            raise ValueError("Updater signature is not UTF-8 text") from exc
        if not signature or "\x00" in signature:
            raise ValueError("Updater signature is invalid")
        return {
            "schema_version": 1,
            "product": "Mardas Studio",
            "kind": kind,
            "version": expected_version,
            "platform": platform_name,
            "architecture": architecture,
            "name": path.name,
            "size": size,
            "sha256": sha256_file(path),
            "signature_present": True,
        }

    if size < MIN_NATIVE_BYTES or size > MAX_NATIVE_BYTES:
        raise ValueError(f"Native desktop artifact size is outside the allowed range: {size}")

    extra: dict[str, Any] = {}
    if kind == "desktop-installer":
        with path.open("rb") as handle:
            if handle.read(2) != b"MZ":
                raise ValueError("Windows installer does not contain a PE header")
    elif kind == "desktop-portable":
        extra = _verify_portable(
            path, expected_version=expected_version, architecture=architecture
        )
    elif kind == "desktop-dmg":
        if size < 512:
            raise ValueError("macOS DMG is too small")
        with path.open("rb") as handle:
            handle.seek(-512, 2)
            if handle.read(4) != b"koly":
                raise ValueError("macOS DMG is missing the UDIF trailer")
    elif kind == "desktop-appimage":
        with path.open("rb") as handle:
            if handle.read(4) != b"\x7fELF":
                raise ValueError("Linux AppImage does not contain an ELF header")
    elif kind == "desktop-deb":
        with path.open("rb") as handle:
            if handle.read(8) != b"!<arch>\n":
                raise ValueError("Linux Debian package does not contain an ar header")
    elif kind == "desktop-macos-updater":
        try:
            with tarfile.open(path, "r:gz") as archive:
                members = archive.getmembers()
                if not members or len(members) > MAX_PORTABLE_FILES:
                    raise ValueError("macOS updater archive inventory is empty or too large")
                total = 0
                has_app_root = False
                for member in members:
                    pure = _safe_member(member.name)
                    total += max(0, member.size)
                    if total > MAX_PORTABLE_UNCOMPRESSED_BYTES:
                        raise ValueError("macOS updater archive expands beyond the allowed size")
                    if any(part.endswith(".app") for part in pure.parts):
                        has_app_root = True
                if not has_app_root:
                    raise ValueError("macOS updater archive does not contain an application bundle")
        except tarfile.TarError as exc:
            raise ValueError("macOS updater archive is not a valid tar.gz file") from exc
        extra["updater_bundle"] = True

    return {
        "schema_version": 1,
        "product": "Mardas Studio",
        "kind": kind,
        "version": expected_version,
        "platform": platform_name,
        "architecture": architecture,
        "name": path.name,
        "size": size,
        "sha256": sha256_file(path),
        **extra,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a normalized Mardas Studio native desktop artifact"
    )
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = verify_native_artifact(args.artifact, expected_version=args.version)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, zipfile.BadZipFile, tarfile.TarError) as exc:
        print(f"Native desktop artifact verification failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Native desktop artifact verified: {args.artifact.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

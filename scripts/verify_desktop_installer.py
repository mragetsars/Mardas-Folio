#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

MIN_INSTALLER_BYTES = 1024 * 1024
MAX_INSTALLER_BYTES = 2 * 1024 * 1024 * 1024
_NAME_RE = re.compile(r"^Mardas-Studio-(?P<version>[^-]+)-windows-(?P<arch>[^-]+)-setup\.exe$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_installer(path: Path, *, expected_version: str) -> dict[str, object]:
    path = path.expanduser().resolve(strict=True)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Desktop installer is missing or unsafe: {path}")
    match = _NAME_RE.fullmatch(path.name)
    if match is None or match.group("version") != expected_version:
        raise ValueError("Desktop installer filename or version is invalid")
    size = path.stat().st_size
    if size < MIN_INSTALLER_BYTES or size > MAX_INSTALLER_BYTES:
        raise ValueError(f"Desktop installer size is outside the allowed range: {size}")
    if path.read_bytes()[:2] != b"MZ":
        raise ValueError("Desktop installer does not contain a Windows PE header")
    return {
        "schema_version": 1,
        "product": "Mardas Studio Windows installer",
        "version": expected_version,
        "platform": "windows",
        "architecture": match.group("arch"),
        "name": path.name,
        "size": size,
        "sha256": sha256(path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify a Mardas Studio NSIS installer")
    parser.add_argument("installer", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        payload = verify_installer(args.installer, expected_version=args.version)
    except (OSError, ValueError) as exc:
        print(f"Desktop installer verification failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Desktop installer verified: {args.installer.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

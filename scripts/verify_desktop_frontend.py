#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import stat
import sys
from pathlib import Path, PurePosixPath

from build_desktop_frontend import MAX_FILES, MAX_FILE_BYTES, MAX_TOTAL_BYTES, project_version, sha256


def verify_frontend(root: Path, *, expected_version: str | None = None) -> dict[str, object]:
    candidate = root.expanduser()
    metadata = candidate.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"Desktop frontend is missing or unsafe: {candidate}")
    root = candidate.resolve(strict=True)
    manifest_path = root / "frontend-manifest.json"
    if manifest_path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("Desktop frontend manifest exceeds the size limit")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_version = expected_version or project_version()
    if payload.get("schema_version") != 1 or payload.get("version") != expected_version:
        raise ValueError("Desktop frontend manifest version is incorrect")
    entries = payload.get("files")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_FILES:
        raise ValueError("Desktop frontend manifest file inventory is invalid")

    names: set[str] = set()
    total = 0
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("Desktop frontend manifest entry is not an object")
        name = str(item.get("path", ""))
        pure = PurePosixPath(name.replace("\\", "/"))
        if not name or pure.is_absolute() or ".." in pure.parts or name in names:
            raise ValueError(f"Unsafe or duplicate desktop frontend path: {name!r}")
        names.add(name)
        path = root / pure
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Desktop frontend file is missing: {name}")
        size = path.stat().st_size
        total += size
        if size != int(item.get("size", -1)) or size > MAX_FILE_BYTES:
            raise ValueError(f"Desktop frontend size mismatch: {name}")
        if str(item.get("sha256", "")) != sha256(path):
            raise ValueError(f"Desktop frontend checksum mismatch: {name}")
    if total > MAX_TOTAL_BYTES:
        raise ValueError("Desktop frontend exceeds the total size limit")

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "frontend-manifest.json"
    }
    if names != actual:
        raise ValueError(
            f"Desktop frontend inventory mismatch; missing={sorted(names-actual)}, extra={sorted(actual-names)}"
        )
    required = {
        "THIRD_PARTY_NOTICES.md",
        "assets/app-icon.svg",
        "index.html",
        "js/main.mjs",
        "js/vendor/codemirror-editor.bundle.mjs",
        "styles.css",
        "workspace.css",
    }
    if not required.issubset(names):
        raise ValueError(f"Desktop frontend is missing required files: {sorted(required-names)}")
    index = (root / "index.html").read_text(encoding="utf-8")
    if "__MARDAS_VERSION__" in index or expected_version not in index:
        raise ValueError("Desktop frontend version token was not resolved")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the Mardas Studio frontend inventory")
    parser.add_argument("root", type=Path)
    parser.add_argument("--version")
    args = parser.parse_args(argv)
    try:
        verify_frontend(args.root, expected_version=args.version)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"Desktop frontend verification failed: {exc}", file=sys.stderr)
        return 2
    print(f"Desktop frontend verified: {args.root.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from runtime_manifest import validate_local_symlink  # noqa: E402
from verify_standalone_runtime import load_and_verify_manifest  # noqa: E402

DEFAULT_TARGET = ROOT / "apps" / "desktop" / "src-tauri" / "resources" / "sidecar"
MARKER = ".mardas-staged-runtime.json"


def _copy_tree(source: Path, target: Path) -> None:
    for path in sorted(
        source.rglob("*"),
        key=lambda item: (item.as_posix().casefold(), item.as_posix()),
    ):
        relative = path.relative_to(source)
        destination = target / relative
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            destination.parent.mkdir(parents=True, exist_ok=True)
            link_target = validate_local_symlink(source, path)
            destination.symlink_to(
                Path(link_target),
                target_is_directory=path.resolve(strict=True).is_dir(),
            )
        elif stat.S_ISDIR(mode):
            destination.mkdir(parents=True, exist_ok=True)
        elif stat.S_ISREG(mode):
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        else:
            raise ValueError(f"Standalone runtime contains an unsupported entry: {path}")


def stage_runtime(source: Path, target: Path = DEFAULT_TARGET, *, expected_version: str) -> Path:
    source = source.expanduser()
    if source.is_symlink():
        raise ValueError("Standalone runtime source must not be a symlink")
    source = source.resolve(strict=True)
    target = target.expanduser().resolve(strict=False)
    if not source.is_dir():
        raise ValueError(f"Standalone runtime source is not a directory: {source}")
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("Standalone runtime source and desktop resource target must not overlap")
    manifest = load_and_verify_manifest(source, expected_version=expected_version, require_browser=True)

    target.parent.mkdir(parents=True, exist_ok=True)
    staging: Path | None = Path(
        tempfile.mkdtemp(prefix=".mardas-sidecar-resource-", dir=target.parent)
    )
    try:
        _copy_tree(source, staging)
        marker = {
            "schema_version": 1,
            "version": expected_version,
            "source_manifest": manifest,
        }
        (staging / MARKER).write_text(
            json.dumps(marker, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        backup = target.with_name(f".{target.name}.previous")
        if backup.exists():
            shutil.rmtree(backup)
        if target.exists():
            target.replace(backup)
        try:
            assert staging is not None
            staging.replace(target)
            staging = None
        except Exception:
            if not target.exists() and backup.exists():
                backup.replace(target)
            raise
        shutil.rmtree(backup, ignore_errors=True)
        return target
    finally:
        if staging is not None and staging.exists():
            resolved = staging.resolve(strict=False)
            expected_parent = target.parent.resolve(strict=False)
            if resolved.parent != expected_parent or not resolved.name.startswith(
                ".mardas-sidecar-resource-"
            ):
                raise RuntimeError(f"Refusing to remove unsafe runtime staging path: {resolved}")
            shutil.rmtree(resolved)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage a verified standalone runtime for Tauri")
    parser.add_argument("source", type=Path)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    try:
        target = stage_runtime(args.source, args.target, expected_version=args.version)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"Desktop runtime staging failed: {exc}", file=sys.stderr)
        return 2
    print(f"Desktop sidecar runtime staged: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

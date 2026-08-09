#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "apps" / "desktop" / "frontend"
DEFAULT_OUTPUT = ROOT / "apps" / "desktop" / "dist"
MAX_FILES = 1_000
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024


def project_version() -> str:
    namespace: dict[str, str] = {}
    exec((ROOT / "src" / "mardas_md2pdf" / "__init__.py").read_text(encoding="utf-8"), namespace)
    return str(namespace["__version__"])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_files(source: Path) -> Iterable[Path]:
    count = 0
    total = 0
    for path in sorted(source.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if path.is_symlink():
            raise ValueError(f"Desktop frontend must not contain symlinks: {path}")
        if not path.is_file():
            continue
        count += 1
        size = path.stat().st_size
        total += size
        if count > MAX_FILES:
            raise ValueError(f"Desktop frontend contains more than {MAX_FILES} files")
        if size > MAX_FILE_BYTES:
            raise ValueError(f"Desktop frontend file exceeds size limit: {path}")
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Desktop frontend exceeds the total size limit")
        yield path


def _safe_remove_staging(staging: Path | None, *, expected_parent: Path) -> None:
    if staging is None or not staging.exists():
        return
    resolved = staging.resolve(strict=False)
    parent = expected_parent.resolve(strict=False)
    if resolved.parent != parent or not resolved.name.startswith(".mardas-desktop-dist-"):
        raise RuntimeError(f"Refusing to remove unsafe frontend staging path: {resolved}")
    shutil.rmtree(resolved)


def build_frontend(
    source: Path = DEFAULT_SOURCE,
    output: Path = DEFAULT_OUTPUT,
    *,
    version: str | None = None,
) -> Path:
    source = source.expanduser().resolve(strict=True)
    output = output.expanduser().resolve(strict=False)
    if not source.is_dir():
        raise ValueError(f"Desktop frontend source is not a directory: {source}")
    if source == output or source in output.parents or output in source.parents:
        raise ValueError("Desktop frontend source and output must not overlap")

    version = version or project_version()
    output.parent.mkdir(parents=True, exist_ok=True)
    staging: Path | None = Path(
        tempfile.mkdtemp(prefix=".mardas-desktop-dist-", dir=output.parent)
    )
    try:
        manifest_files: list[dict[str, object]] = []
        for path in source_files(source):
            relative = path.relative_to(source)
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if relative.as_posix() == "index.html":
                text = path.read_text(encoding="utf-8")
                if "__MARDAS_VERSION__" not in text:
                    raise ValueError("Desktop index.html is missing the version placeholder")
                target.write_text(
                    text.replace("__MARDAS_VERSION__", version),
                    encoding="utf-8",
                    newline="\n",
                )
            else:
                shutil.copyfile(path, target)
            os.chmod(target, 0o644)

        for path in sorted(staging.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if path.is_file():
                manifest_files.append(
                    {
                        "path": path.relative_to(staging).as_posix(),
                        "size": path.stat().st_size,
                        "sha256": sha256(path),
                    }
                )
        manifest = {
            "schema_version": 1,
            "product": "Mardas Folio desktop frontend",
            "version": version,
            "files": manifest_files,
        }
        manifest_path = staging / "frontend-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.chmod(manifest_path, 0o644)

        backup = output.with_name(f".{output.name}.previous")
        if backup.exists():
            shutil.rmtree(backup)
        if output.exists():
            output.replace(backup)
        try:
            staging.replace(output)
            staging = None
        except Exception:
            if not output.exists() and backup.exists():
                backup.replace(output)
            raise
        shutil.rmtree(backup, ignore_errors=True)
        return output
    finally:
        _safe_remove_staging(staging, expected_parent=output.parent)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the offline Mardas Folio frontend")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--version")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = build_frontend(args.source, args.output, version=args.version)
    print(f"Desktop frontend built: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

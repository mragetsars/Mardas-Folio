#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from generate_update_manifest import (  # noqa: E402
    build_update_manifest,
    verify_update_manifest,
    write_manifest,
)
from verify_native_desktop import verify_native_artifact  # noqa: E402

_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _release_url(repository: str, tag: str, name: str) -> str:
    if not _REPOSITORY_RE.fullmatch(repository):
        raise ValueError("Repository must use OWNER/REPO form")
    if not re.fullmatch(r"v[0-9A-Za-z.+-]+", tag):
        raise ValueError("Release tag is invalid")
    return f"https://github.com/{repository}/releases/download/{tag}/{name}"


def _require_pair(directory: Path, payload_name: str, *, version: str) -> tuple[Path, Path]:
    payload = directory / payload_name
    signature = directory / f"{payload_name}.sig"
    if not payload.is_file() or payload.is_symlink():
        raise ValueError(f"Updater payload is missing or unsafe: {payload_name}")
    if not signature.is_file() or signature.is_symlink():
        raise ValueError(f"Updater signature is missing or unsafe: {signature.name}")
    verify_native_artifact(payload, expected_version=version)
    verify_native_artifact(signature, expected_version=version)
    return payload, signature


def assemble(
    directory: Path,
    *,
    version: str,
    repository: str = "mragetsars/Mardas-MD2PDF",
    tag: str | None = None,
    notes: str | None = None,
    pub_date: str | None = None,
    require_macos_x86_64: bool = True,
) -> Path:
    directory = directory.expanduser().resolve(strict=True)
    if not directory.is_dir():
        raise ValueError(f"Release artifact directory is not a directory: {directory}")
    tag = tag or f"v{version}"
    if tag != f"v{version}":
        raise ValueError("Release tag must exactly match v<version>")

    targets: list[tuple[str, str, Path]] = []
    specs = [
        (
            "windows-x86_64",
            f"Mardas-Studio-{version}-windows-x86_64-setup.exe",
        ),
        (
            "linux-x86_64",
            f"Mardas-Studio-{version}-linux-x86_64.AppImage",
        ),
        (
            "darwin-aarch64",
            f"Mardas-Studio-{version}-macos-arm64-updater.tar.gz",
        ),
    ]
    if require_macos_x86_64:
        specs.append(
            (
                "darwin-x86_64",
                f"Mardas-Studio-{version}-macos-x86_64-updater.tar.gz",
            )
        )

    for target, payload_name in specs:
        payload, signature = _require_pair(directory, payload_name, version=version)
        targets.append(
            (target, _release_url(repository, tag, payload.name), signature)
        )

    payload = build_update_manifest(
        version=version,
        platform_specs=targets,
        notes=notes,
        pub_date=pub_date,
    )
    output = directory / "latest.json"
    write_manifest(output, payload)
    verify_update_manifest(output, expected_version=version)
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assemble a signed Tauri latest.json from verified Mardas Studio release assets"
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--repository", default="mragetsars/Mardas-MD2PDF")
    parser.add_argument("--tag")
    parser.add_argument("--notes-file", type=Path)
    parser.add_argument("--pub-date")
    parser.add_argument("--allow-missing-macos-x86-64", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    notes = None
    if args.notes_file is not None:
        path = args.notes_file.expanduser().resolve(strict=True)
        if path.is_symlink() or not path.is_file():
            print("Update notes file is missing or unsafe.", file=sys.stderr)
            return 2
        if path.stat().st_size > 128 * 1024:
            print("Update notes file exceeds the size limit.", file=sys.stderr)
            return 2
        notes = path.read_text(encoding="utf-8")
    try:
        output = assemble(
            args.artifact_dir,
            version=args.version,
            repository=args.repository,
            tag=args.tag,
            notes=notes,
            pub_date=args.pub_date,
            require_macos_x86_64=not args.allow_missing_macos_x86_64,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Signed update assembly failed: {exc}", file=sys.stderr)
        return 2
    print(f"Signed update manifest: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

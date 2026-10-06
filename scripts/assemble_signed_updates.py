#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import binascii
import os
import re
import shutil
import subprocess
import sys
import tempfile
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
MAX_UPDATER_KEY_BYTES = 32 * 1024


def _decode_tauri_minisign(value: str, *, label: str, maximum: int) -> bytes:
    """Tauri wraps the entire minisign text document in base64."""
    if not value or len(value.encode("utf-8")) > maximum or "\x00" in value:
        raise ValueError(f"Updater {label} is missing or exceeds the size limit")
    try:
        decoded = base64.b64decode(value.strip(), validate=True)
        decoded.decode("utf-8")
    except (binascii.Error, UnicodeError, ValueError) as exc:
        raise ValueError(f"Updater {label} is not a valid Tauri minisign document") from exc
    if not decoded or b"\x00" in decoded:
        raise ValueError(f"Updater {label} is not a valid Tauri minisign document")
    return decoded


def _verify_signature(payload: Path, signature: Path, *, public_key: str) -> None:
    """Delegate Ed25519 and trusted-comment verification to official minisign."""
    executable = shutil.which("minisign")
    if executable is None:
        raise ValueError("Official minisign CLI is required to verify updater signatures")
    public_text = _decode_tauri_minisign(
        public_key, label="public key", maximum=MAX_UPDATER_KEY_BYTES
    )
    signature_text = _decode_tauri_minisign(
        signature.read_text(encoding="utf-8").strip(), label="signature", maximum=64 * 1024
    )
    with tempfile.TemporaryDirectory(prefix="mardas-updater-verification-") as temporary:
        directory = Path(temporary)
        public_path = directory / "updater.pub"
        signature_path = directory / "payload.minisig"
        public_path.write_bytes(public_text)
        signature_path.write_bytes(signature_text)
        try:
            completed = subprocess.run(
                [executable, "-Vm", str(payload), "-p", str(public_path), "-x", str(signature_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"Could not verify updater signature for {payload.name}") from exc
    if completed.returncode != 0:
        raise ValueError(f"Updater signature verification failed for {payload.name}")


def _release_url(repository: str, tag: str, name: str) -> str:
    if not _REPOSITORY_RE.fullmatch(repository):
        raise ValueError("Repository must use OWNER/REPO form")
    if not re.fullmatch(r"v[0-9A-Za-z.+-]+", tag):
        raise ValueError("Release tag is invalid")
    return f"https://github.com/{repository}/releases/download/{tag}/{name}"


def _require_pair(
    directory: Path, payload_name: str, *, version: str, public_key: str
) -> tuple[Path, Path]:
    payload = directory / payload_name
    signature = directory / f"{payload_name}.sig"
    if not payload.is_file() or payload.is_symlink():
        raise ValueError(f"Updater payload is missing or unsafe: {payload_name}")
    if not signature.is_file() or signature.is_symlink():
        raise ValueError(f"Updater signature is missing or unsafe: {signature.name}")
    verify_native_artifact(payload, expected_version=version)
    verify_native_artifact(signature, expected_version=version)
    _verify_signature(payload, signature, public_key=public_key)
    return payload, signature


def assemble(
    directory: Path,
    *,
    version: str,
    repository: str = "mragetsars/Mardas-Folio",
    tag: str | None = None,
    notes: str | None = None,
    pub_date: str | None = None,
    require_macos_x86_64: bool = True,
    public_key: str | None = None,
) -> Path:
    directory = directory.expanduser().resolve(strict=True)
    if not directory.is_dir():
        raise ValueError(f"Release artifact directory is not a directory: {directory}")
    tag = tag or f"v{version}"
    if tag != f"v{version}":
        raise ValueError("Release tag must exactly match v<version>")
    public_key = public_key if public_key is not None else os.environ.get("MARDAS_UPDATER_PUBKEY", "")
    _decode_tauri_minisign(public_key, label="public key", maximum=MAX_UPDATER_KEY_BYTES)

    targets: list[tuple[str, str, Path]] = []
    specs = [
        (
            "windows-x86_64",
            f"Mardas-Folio-{version}-windows-x86_64-setup.exe",
        ),
        (
            "linux-x86_64",
            f"Mardas-Folio-{version}-linux-x86_64.AppImage",
        ),
        (
            "darwin-aarch64",
            f"Mardas-Folio-{version}-macos-arm64-updater.tar.gz",
        ),
    ]
    if require_macos_x86_64:
        specs.append(
            (
                "darwin-x86_64",
                f"Mardas-Folio-{version}-macos-x86_64-updater.tar.gz",
            )
        )

    for target, payload_name in specs:
        payload, signature = _require_pair(
            directory, payload_name, version=version, public_key=public_key
        )
        targets.append(
            (target, _release_url(repository, tag, payload.name), signature)
        )

    payload = build_update_manifest(
        version=version,
        platform_specs=targets,
        notes=notes or "",
        pub_date=pub_date,
    )
    output = directory / "latest.json"
    write_manifest(output, payload)
    verify_update_manifest(output, expected_version=version)
    return output


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assemble a signed Tauri latest.json from verified Mardas Folio release assets"
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--repository", default="mragetsars/Mardas-Folio")
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

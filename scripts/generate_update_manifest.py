#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


SUPPORTED_TARGETS = {
    "windows-x86_64",
    "windows-aarch64",
    "linux-x86_64",
    "linux-aarch64",
    "darwin-x86_64",
    "darwin-aarch64",
}
MAX_SIGNATURE_BYTES = 64 * 1024
MAX_NOTES_BYTES = 128 * 1024


class UpdateManifestError(ValueError):
    pass



_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def _validate_version(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("v"):
        cleaned = cleaned[1:]
    if not _SEMVER_RE.fullmatch(cleaned):
        raise UpdateManifestError(f"Invalid semantic update version: {value!r}")
    return cleaned


def _validate_https_url(value: str) -> str:
    url = value.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise UpdateManifestError(f"Update URL must be an HTTPS URL without embedded credentials: {value!r}")
    if parsed.fragment:
        raise UpdateManifestError("Update URLs must not contain fragments")
    return url


def _read_signature(path: Path) -> str:
    path = path.expanduser().resolve(strict=True)
    if path.is_symlink() or not path.is_file():
        raise UpdateManifestError(f"Signature file is missing or unsafe: {path}")
    if path.stat().st_size <= 0 or path.stat().st_size > MAX_SIGNATURE_BYTES:
        raise UpdateManifestError("Signature file is empty or exceeds the size limit")
    signature = path.read_text(encoding="utf-8").strip()
    if not signature or "\x00" in signature:
        raise UpdateManifestError("Signature file is empty or invalid")
    return signature


def _validate_pub_date(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UpdateManifestError("pub_date must be RFC 3339 / ISO-8601 compatible") from exc
    if parsed.tzinfo is None:
        raise UpdateManifestError("pub_date must contain a timezone")
    return candidate


def _parse_platform_spec(spec: str) -> tuple[str, str, Path]:
    # TARGET=HTTPS_URL,SIGNATURE_FILE
    if "=" not in spec or "," not in spec:
        raise UpdateManifestError(
            "Platform specification must be TARGET=HTTPS_URL,SIGNATURE_FILE"
        )
    target, rest = spec.split("=", 1)
    url, signature_path = rest.rsplit(",", 1)
    target = target.strip()
    if target not in SUPPORTED_TARGETS:
        raise UpdateManifestError(
            f"Unsupported updater target {target!r}; expected one of {sorted(SUPPORTED_TARGETS)}"
        )
    return target, _validate_https_url(url), Path(signature_path.strip())


def build_update_manifest(
    *,
    version: str,
    platform_specs: list[tuple[str, str, Path]],
    notes: str = "",
    pub_date: str | None = None,
) -> dict[str, object]:
    normalized_version = _validate_version(version)
    if len(notes.encode("utf-8")) > MAX_NOTES_BYTES:
        raise UpdateManifestError("Release notes exceed the size limit")
    normalized_date = _validate_pub_date(pub_date)
    platforms: dict[str, dict[str, str]] = {}
    for target, url, signature_path in platform_specs:
        if target not in SUPPORTED_TARGETS:
            raise UpdateManifestError(
                f"Unsupported updater target {target!r}; expected one of {sorted(SUPPORTED_TARGETS)}"
            )
        if target in platforms:
            raise UpdateManifestError(f"Duplicate updater target: {target}")
        platforms[target] = {
            "url": _validate_https_url(url),
            "signature": _read_signature(signature_path),
        }
    if not platforms:
        raise UpdateManifestError("At least one signed updater target is required")
    payload: dict[str, object] = {
        "version": normalized_version,
        "platforms": {key: platforms[key] for key in sorted(platforms)},
    }
    if notes:
        payload["notes"] = notes
    if normalized_date is not None:
        payload["pub_date"] = normalized_date
    return payload


def write_manifest(path: Path, payload: dict[str, object]) -> None:
    path = path.expanduser().resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def verify_update_manifest(path: Path, *, expected_version: str | None = None) -> dict[str, object]:
    path = path.expanduser().resolve(strict=True)
    if path.is_symlink() or not path.is_file():
        raise UpdateManifestError(f"Update manifest is missing or unsafe: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise UpdateManifestError("Update manifest must be a JSON object")
    version = _validate_version(str(payload.get("version", "")))
    if expected_version is not None and version != _validate_version(expected_version):
        raise UpdateManifestError(
            f"Update manifest version mismatch: {version} != {_validate_version(expected_version)}"
        )
    platforms = payload.get("platforms")
    if not isinstance(platforms, dict) or not platforms:
        raise UpdateManifestError("Update manifest platforms must be a non-empty object")
    for target, item in platforms.items():
        if target not in SUPPORTED_TARGETS:
            raise UpdateManifestError(f"Unsupported updater target in manifest: {target!r}")
        if not isinstance(item, dict):
            raise UpdateManifestError(f"Updater target {target!r} must be an object")
        _validate_https_url(str(item.get("url", "")))
        signature = str(item.get("signature", "")).strip()
        if not signature or len(signature.encode("utf-8")) > MAX_SIGNATURE_BYTES:
            raise UpdateManifestError(f"Updater target {target!r} has an invalid signature")
    if "pub_date" in payload:
        _validate_pub_date(str(payload["pub_date"]))
    if len(str(payload.get("notes", "")).encode("utf-8")) > MAX_NOTES_BYTES:
        raise UpdateManifestError("Release notes exceed the size limit")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate or verify a signed static Tauri updater latest.json manifest"
    )
    parser.add_argument("--version")
    parser.add_argument(
        "--platform",
        action="append",
        default=[],
        metavar="TARGET=HTTPS_URL,SIGNATURE_FILE",
        help="Repeat for each signed updater target",
    )
    parser.add_argument("--notes", default="")
    parser.add_argument("--notes-file", type=Path)
    parser.add_argument("--pub-date")
    parser.add_argument("--output", type=Path, default=Path("latest.json"))
    parser.add_argument("--verify", type=Path)
    parser.add_argument("--expected-version")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.verify:
            payload = verify_update_manifest(args.verify, expected_version=args.expected_version)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0
        if not args.version:
            raise UpdateManifestError("--version is required when generating a manifest")
        notes = args.notes
        if args.notes_file:
            notes_path = args.notes_file.expanduser().resolve(strict=True)
            if notes_path.is_symlink() or not notes_path.is_file():
                raise UpdateManifestError("Release notes file is missing or unsafe")
            notes = notes_path.read_text(encoding="utf-8")
        specs = [_parse_platform_spec(value) for value in args.platform]
        payload = build_update_manifest(
            version=args.version,
            platform_specs=specs,
            notes=notes,
            pub_date=args.pub_date,
        )
        write_manifest(args.output, payload)
        verify_update_manifest(args.output, expected_version=args.version)
        print(f"Signed updater manifest created: {args.output.resolve()}")
        return 0
    except (OSError, json.JSONDecodeError, UpdateManifestError) as exc:
        print(f"Updater manifest error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

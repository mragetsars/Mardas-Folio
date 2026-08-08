#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_UPDATE_ENDPOINT = (
    "https://github.com/mragetsars/Mardas-MD2PDF/releases/latest/download/latest.json"
)
WINDOWS_THUMBPRINT_RE = re.compile(r"^[0-9A-Fa-f]{40}$")
APPLE_IDENTITY_RE = re.compile(
    r"^Developer ID Application: [^\x00-\x1f\x7f]{1,350} \((?P<team>[A-Z0-9]{10})\)$"
)
APPLE_API_ISSUER_RE = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
APPLE_API_KEY_RE = re.compile(r"^[A-Z0-9]{10}$")
TEAM_ID_RE = re.compile(r"^[A-Z0-9]{10}$")
APPLE_ID_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class Check:
    name: str
    ready: bool
    required: bool
    detail: str


def _present(env: dict[str, str], name: str) -> bool:
    return bool(env.get(name, "").strip())


def _bounded_secret(env: dict[str, str], name: str, *, maximum: int = 64 * 1024) -> bool:
    value = env.get(name, "")
    return bool(value) and "\x00" not in value and len(value.encode("utf-8")) <= maximum


def _safe_public_line(value: str, *, maximum: int = 4096) -> bool:
    return (
        bool(value)
        and len(value.encode("utf-8")) <= maximum
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def _https(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and not parsed.username
        and parsed.password is None
        and not parsed.fragment
    )


def _timestamp_url(value: str) -> bool:
    candidate = value.strip()
    if not _safe_public_line(candidate) or any(character.isspace() for character in candidate):
        return False
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and not parsed.username
        and parsed.password is None
        and not parsed.fragment
    )


def _base64_pkcs12(value: str) -> bool:
    compact = "".join(value.split())
    if not compact or len(compact) > 8 * 1024 * 1024:
        return False
    try:
        decoded = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError):
        return False
    return 256 <= len(decoded) <= 5 * 1024 * 1024 and decoded.startswith(b"0")


def _private_key_pem(value: str) -> bool:
    size = len(value.encode("utf-8"))
    if not 64 <= size <= 64 * 1024 or "\x00" in value:
        return False
    return "-----BEGIN PRIVATE KEY-----" in value and "-----END PRIVATE KEY-----" in value


def _safe_path_text(value: str) -> bool:
    if not value or len(value.encode("utf-8")) > 4096 or any(
        character in value for character in ("\x00", "\r", "\n")
    ):
        return False
    candidate = Path(value).expanduser()
    if not candidate.is_absolute() or candidate.is_symlink():
        return False
    try:
        candidate = candidate.resolve(strict=True)
        if not candidate.is_file() or not 64 <= candidate.stat().st_size <= 64 * 1024:
            return False
        return _private_key_pem(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return False


def evaluate(env: dict[str, str], *, mode: str) -> list[Check]:
    production = mode == "public"
    updater_key = _present(env, "TAURI_SIGNING_PRIVATE_KEY")
    updater_pubkey = _present(env, "MARDAS_UPDATER_PUBKEY")
    endpoint = env.get("MARDAS_UPDATE_ENDPOINT", DEFAULT_UPDATE_ENDPOINT)
    windows_signing = (
        _base64_pkcs12(env.get("MARDAS_WINDOWS_CERTIFICATE", ""))
        and _bounded_secret(env, "MARDAS_WINDOWS_CERTIFICATE_PASSWORD")
        and bool(
            WINDOWS_THUMBPRINT_RE.fullmatch(
                env.get("MARDAS_WINDOWS_CERTIFICATE_THUMBPRINT", "").strip()
            )
        )
        and env.get("MARDAS_WINDOWS_DIGEST_ALGORITHM", "sha256").strip().lower()
        == "sha256"
        and _timestamp_url(env.get("MARDAS_WINDOWS_TIMESTAMP_URL", ""))
    )
    mac_certificate = (
        _base64_pkcs12(env.get("APPLE_CERTIFICATE", ""))
        and _bounded_secret(env, "APPLE_CERTIFICATE_PASSWORD")
        and _bounded_secret(env, "KEYCHAIN_PASSWORD")
        and _safe_public_line(env.get("APPLE_SIGNING_IDENTITY", "").strip())
        and bool(APPLE_IDENTITY_RE.fullmatch(env.get("APPLE_SIGNING_IDENTITY", "").strip()))
    )
    api_values = tuple(
        env.get(name, "").strip()
        for name in ("APPLE_API_ISSUER", "APPLE_API_KEY", "APPLE_API_KEY_P8")
    )
    api_path = env.get("APPLE_API_KEY_PATH", "").strip()
    api_present = any(api_values) or bool(api_path)
    api_material = _private_key_pem(api_values[2]) or _safe_path_text(api_path)
    notarization_api_complete = (
        bool(APPLE_API_ISSUER_RE.fullmatch(env.get("APPLE_API_ISSUER", "").strip()))
        and bool(APPLE_API_KEY_RE.fullmatch(env.get("APPLE_API_KEY", "").strip()))
        and api_material
    )
    identity_match = APPLE_IDENTITY_RE.fullmatch(
        env.get("APPLE_SIGNING_IDENTITY", "").strip()
    )
    apple_id = env.get("APPLE_ID", "").strip()
    team_id = env.get("APPLE_TEAM_ID", "").strip()
    apple_id_present = any(env.get(name, "").strip() for name in ("APPLE_ID", "APPLE_PASSWORD"))
    team_consistent = (
        not team_id
        or (
            bool(TEAM_ID_RE.fullmatch(team_id))
            and identity_match is not None
            and identity_match.group("team") == team_id
        )
    )
    notarization_id_complete = (
        bool(APPLE_ID_RE.fullmatch(apple_id))
        and _bounded_secret(env, "APPLE_PASSWORD")
        and bool(TEAM_ID_RE.fullmatch(team_id))
        and identity_match is not None
        and identity_match.group("team") == team_id
    )
    notarization_ready = (
        notarization_api_complete != notarization_id_complete
        and (not api_present or notarization_api_complete)
        and (not apple_id_present or notarization_id_complete)
        and team_consistent
    )

    return [
        Check(
            "updater_private_key",
            updater_key,
            True,
            "Tauri updater signing private key is configured outside the repository.",
        ),
        Check(
            "updater_public_key",
            updater_pubkey,
            True,
            "Updater public key can be embedded into production desktop builds.",
        ),
        Check(
            "updater_https_endpoint",
            _https(endpoint),
            True,
            "Updater endpoint must be HTTPS and contain no embedded credentials.",
        ),
        Check(
            "windows_code_signing",
            windows_signing,
            production,
            "Public Windows releases require an imported PFX, SHA-1 thumbprint, "
            "SHA-256 digest, and timestamp service.",
        ),
        Check(
            "macos_code_signing",
            mac_certificate,
            production,
            "Public macOS releases require an imported Developer ID Application "
            "certificate and keychain.",
        ),
        Check(
            "macos_notarization",
            notarization_ready,
            production,
            "Public macOS releases require exactly one complete App Store Connect API or "
            "Apple ID notarization credential set.",
        ),
    ]


def report(checks: list[Check], *, mode: str) -> dict[str, Any]:
    blocking = [item.name for item in checks if item.required and not item.ready]
    return {
        "schema_version": 1,
        "mode": mode,
        "ready": not blocking,
        "blocking": blocking,
        "checks": [asdict(item) for item in checks],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check secret-driven Mardas Studio release readiness without printing secrets"
    )
    parser.add_argument("--mode", choices=("draft", "public"), default="draft")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    payload = report(evaluate(dict(os.environ), mode=args.mode), mode=args.mode)
    if args.json is not None:
        output = args.json.expanduser().resolve(strict=False)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    for item in payload["checks"]:
        state = "PASS" if item["ready"] else ("BLOCKED" if item["required"] else "NOT CONFIGURED")
        print(f"{state:14} {item['name']}: {item['detail']}")
    if not payload["ready"]:
        print(
            "Release readiness blocked by: " + ", ".join(payload["blocking"]),
            file=sys.stderr,
        )
        return 2
    print(f"Mardas Studio {args.mode} release preflight: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

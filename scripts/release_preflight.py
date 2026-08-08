#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_UPDATE_ENDPOINT = (
    "https://github.com/mragetsars/Mardas-MD2PDF/releases/latest/download/latest.json"
)


@dataclass(frozen=True)
class Check:
    name: str
    ready: bool
    required: bool
    detail: str


def _present(env: dict[str, str], name: str) -> bool:
    return bool(env.get(name, "").strip())


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


def evaluate(env: dict[str, str], *, mode: str) -> list[Check]:
    production = mode == "public"
    updater_key = _present(env, "TAURI_SIGNING_PRIVATE_KEY")
    updater_pubkey = _present(env, "MARDAS_UPDATER_PUBKEY")
    endpoint = env.get("MARDAS_UPDATE_ENDPOINT", DEFAULT_UPDATE_ENDPOINT)
    windows_signing = _present(env, "MARDAS_WINDOWS_CERTIFICATE_THUMBPRINT") or _present(
        env, "MARDAS_WINDOWS_SIGN_COMMAND"
    )
    mac_certificate = _present(env, "APPLE_CERTIFICATE") and _present(
        env, "APPLE_CERTIFICATE_PASSWORD"
    )
    mac_identity = _present(env, "APPLE_SIGNING_IDENTITY") or mac_certificate
    notarization_api = all(
        _present(env, name) for name in ("APPLE_API_ISSUER", "APPLE_API_KEY", "APPLE_API_KEY_PATH")
    )
    notarization_id = all(
        _present(env, name) for name in ("APPLE_ID", "APPLE_PASSWORD", "APPLE_TEAM_ID")
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
            "Production Windows releases should be Authenticode-signed.",
        ),
        Check(
            "macos_code_signing",
            mac_identity,
            production,
            "Production macOS releases require a Developer ID signing identity.",
        ),
        Check(
            "macos_notarization",
            notarization_api or notarization_id,
            production,
            "Production macOS releases require notarization credentials.",
        ),
    ]


def report(checks: list[Check], *, mode: str) -> dict[str, object]:
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

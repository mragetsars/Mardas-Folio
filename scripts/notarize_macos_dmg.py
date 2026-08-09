#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess  # nosec B404 - fixed executables and fixed argument arrays only.
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any, Mapping, Sequence

NATIVE_MANIFEST_NAME = "desktop-native-manifest.json"
MAX_JSON_BYTES = 1024 * 1024
MAX_SIGNING_VALUE_BYTES = 4096
APPLE_IDENTITY_RE = re.compile(
    r"^Developer ID Application: [^\x00-\x1f\x7f]{1,350} \((?P<team>[A-Z0-9]{10})\)$"
)
APPLE_API_ISSUER_RE = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
APPLE_API_KEY_RE = re.compile(r"^[A-Z0-9]{10}$")
APPLE_TEAM_ID_RE = re.compile(r"^[A-Z0-9]{10}$")
APPLE_ID_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SUBMISSION_ID_RE = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)


class MacOSNotarizationError(RuntimeError):
    """Raised when a public macOS DMG cannot be notarized safely."""


@dataclass(frozen=True)
class NotarizationPlan:
    method: str
    command: tuple[str, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise MacOSNotarizationError(f"Required native manifest is missing or unsafe: {path.name}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_JSON_BYTES:
        raise MacOSNotarizationError("Native manifest is empty or exceeds the size limit")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MacOSNotarizationError("Native manifest is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise MacOSNotarizationError("Native manifest root must be an object")
    return payload


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    fd, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _bounded_line(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if (
        not value
        or len(value.encode("utf-8")) > MAX_SIGNING_VALUE_BYTES
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise MacOSNotarizationError(f"{name} is missing or malformed")
    return value


def _api_key_path(environment: Mapping[str, str]) -> Path:
    raw = _bounded_line(environment, "APPLE_API_KEY_PATH")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute() or candidate.is_symlink():
        raise MacOSNotarizationError("APPLE_API_KEY_PATH must be absolute and non-symbolic")
    try:
        resolved = candidate.resolve(strict=True)
        size = resolved.stat().st_size
        content = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise MacOSNotarizationError("APPLE_API_KEY_PATH is missing or unreadable") from exc
    if (
        not resolved.is_file()
        or not 64 <= size <= 64 * 1024
        or "\x00" in content
        or "-----BEGIN PRIVATE KEY-----" not in content
        or "-----END PRIVATE KEY-----" not in content
    ):
        raise MacOSNotarizationError("APPLE_API_KEY_PATH is not a bounded PEM private key")
    return resolved


def _notarization_plan(
    *,
    dmg: Path,
    contract: Mapping[str, Any],
    environment: Mapping[str, str],
) -> NotarizationPlan:
    identity = str(contract.get("identity", ""))
    identity_match = APPLE_IDENTITY_RE.fullmatch(identity)
    if identity_match is None:
        raise MacOSNotarizationError("Native manifest has an invalid Developer ID identity")
    expected_team = identity_match.group("team")
    method = str(contract.get("notarization_method", ""))
    api_names = ("APPLE_API_ISSUER", "APPLE_API_KEY", "APPLE_API_KEY_PATH")
    api_present = any(environment.get(name, "").strip() for name in api_names)
    apple_id_present = any(
        environment.get(name, "").strip() for name in ("APPLE_ID", "APPLE_PASSWORD")
    )

    if method == "app-store-connect-api":
        if not api_present or apple_id_present:
            raise MacOSNotarizationError(
                "App Store Connect API notarization requires one unambiguous credential set"
            )
        issuer = _bounded_line(environment, "APPLE_API_ISSUER")
        key_id = _bounded_line(environment, "APPLE_API_KEY")
        key_path = _api_key_path(environment)
        configured_team = environment.get("APPLE_TEAM_ID", "").strip()
        if (
            APPLE_API_ISSUER_RE.fullmatch(issuer) is None
            or APPLE_API_KEY_RE.fullmatch(key_id) is None
            or configured_team
            and (
                APPLE_TEAM_ID_RE.fullmatch(configured_team) is None
                or configured_team != expected_team
            )
        ):
            raise MacOSNotarizationError("App Store Connect API credential metadata is invalid")
        return NotarizationPlan(
            method=method,
            command=(
                "xcrun",
                "notarytool",
                "submit",
                str(dmg),
                "--wait",
                "--output-format",
                "json",
                "--issuer",
                issuer,
                "--key-id",
                key_id,
                "--key",
                str(key_path),
            ),
        )

    if method == "apple-id":
        if api_present or not apple_id_present:
            raise MacOSNotarizationError(
                "Apple ID notarization requires one unambiguous credential set"
            )
        apple_id = _bounded_line(environment, "APPLE_ID")
        password = _bounded_line(environment, "APPLE_PASSWORD")
        team_id = _bounded_line(environment, "APPLE_TEAM_ID")
        if (
            APPLE_ID_RE.fullmatch(apple_id) is None
            or APPLE_TEAM_ID_RE.fullmatch(team_id) is None
            or team_id != expected_team
        ):
            raise MacOSNotarizationError("Apple ID credential metadata is invalid")
        return NotarizationPlan(
            method=method,
            command=(
                "xcrun",
                "notarytool",
                "submit",
                str(dmg),
                "--wait",
                "--output-format",
                "json",
                "--apple-id",
                apple_id,
                "--password",
                password,
                "--team-id",
                team_id,
            ),
        )

    raise MacOSNotarizationError("Native manifest has no supported notarization method")


def _run_command(command: Sequence[str], *, action: str) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(  # nosec B603
            list(command),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (FileNotFoundError, PermissionError, OSError) as exc:
        raise MacOSNotarizationError(f"Required macOS tool is unavailable during {action}") from exc
    if completed.returncode != 0:
        # Do not include command arguments or tool output here. Apple ID mode necessarily passes
        # an app-specific password as a notarytool argument, and failure output is not trusted.
        raise MacOSNotarizationError(f"macOS {action} command failed")
    return completed


def _accepted_submission(output: str) -> str:
    if not output or len(output.encode("utf-8")) > MAX_JSON_BYTES or "\x00" in output:
        raise MacOSNotarizationError("notarytool returned empty or oversized output")
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise MacOSNotarizationError("notarytool did not return valid JSON") from exc
    if not isinstance(payload, dict) or payload.get("status") != "Accepted":
        raise MacOSNotarizationError("Apple notarization status was not Accepted")
    submission_id = str(payload.get("id", ""))
    if SUBMISSION_ID_RE.fullmatch(submission_id) is None:
        raise MacOSNotarizationError("Apple notarization response has no valid submission ID")
    return submission_id.lower()


def _resolve_normalized_dmg(
    artifact_dir: Path, manifest: Mapping[str, Any]
) -> tuple[Path, dict[str, Any]]:
    version = str(manifest.get("version", ""))
    architecture = str(manifest.get("architecture", ""))
    if (
        not re.fullmatch(r"[A-Za-z0-9.]+", version)
        or not re.fullmatch(r"[A-Za-z0-9_]+", architecture)
    ):
        raise MacOSNotarizationError("Native manifest version or architecture is invalid")
    expected_name = f"Mardas-Folio-{version}-macos-{architecture}.dmg"
    raw_records = manifest.get("artifacts")
    if not isinstance(raw_records, list):
        raise MacOSNotarizationError("Native manifest has no artifact inventory")
    records = [
        record
        for record in raw_records
        if isinstance(record, dict) and record.get("kind") == "desktop-dmg"
    ]
    if len(records) != 1:
        raise MacOSNotarizationError("Native manifest must contain exactly one DMG artifact")
    record = records[0]
    name = str(record.get("name", ""))
    if name != expected_name or PurePath(name).name != name:
        raise MacOSNotarizationError("Native manifest DMG name is not normalized")
    candidates = list(artifact_dir.glob("Mardas-Folio-*-macos-*.dmg"))
    if len(candidates) != 1 or candidates[0].name != expected_name:
        raise MacOSNotarizationError("Artifact directory must contain exactly one normalized DMG")
    dmg = candidates[0]
    if dmg.is_symlink() or not dmg.is_file():
        raise MacOSNotarizationError("Normalized DMG is missing or unsafe")
    if record.get("size") != dmg.stat().st_size or record.get("sha256") != sha256_file(dmg):
        raise MacOSNotarizationError("Normalized DMG does not match the native manifest")
    return dmg, record


def notarize_macos_dmg(
    artifact_dir: Path,
    *,
    mode: str,
    environment: Mapping[str, str] | None = None,
    platform_name: str | None = None,
) -> Path:
    if mode != "public":
        raise MacOSNotarizationError("DMG notarization is scoped to public releases")
    observed_platform = platform_name or {
        "Darwin": "macos",
        "Windows": "windows",
        "Linux": "linux",
    }.get(platform.system(), "unsupported")
    if observed_platform != "macos":
        raise MacOSNotarizationError("DMG notarization must run on a macOS release runner")

    unresolved = artifact_dir.expanduser()
    if unresolved.is_symlink():
        raise MacOSNotarizationError("Artifact directory must not be a symbolic link")
    try:
        resolved_dir = unresolved.resolve(strict=True)
    except OSError as exc:
        raise MacOSNotarizationError("Artifact directory does not exist") from exc
    if not resolved_dir.is_dir():
        raise MacOSNotarizationError("Artifact directory is not a directory")

    manifest_path = resolved_dir / NATIVE_MANIFEST_NAME
    manifest = _read_json(manifest_path)
    if (
        manifest.get("schema_version") != 1
        or manifest.get("product") != "Mardas Folio native desktop artifacts"
        or manifest.get("platform") != "macos"
        or manifest.get("release_mode") != "public"
    ):
        raise MacOSNotarizationError("Native manifest is not a public macOS release manifest")
    contract = manifest.get("os_signing")
    if not isinstance(contract, dict) or (
        contract.get("release_mode") != "public"
        or contract.get("required") is not True
        or contract.get("requested") is not True
        or contract.get("verified") is not False
        or contract.get("status") != "pending-verification"
        or contract.get("method") != "developer-id"
    ):
        raise MacOSNotarizationError("Native manifest signing contract is invalid")

    dmg, record = _resolve_normalized_dmg(resolved_dir, manifest)
    runner_environment = dict(os.environ if environment is None else environment)
    plan = _notarization_plan(dmg=dmg, contract=contract, environment=runner_environment)
    completed = _run_command(plan.command, action="notarization submission")
    submission_id = _accepted_submission(completed.stdout)
    _run_command(
        ("xcrun", "stapler", "staple", "-v", str(dmg)),
        action="notary ticket stapling",
    )
    _run_command(
        ("xcrun", "stapler", "validate", str(dmg)),
        action="notary ticket validation",
    )

    record["size"] = dmg.stat().st_size
    record["sha256"] = sha256_file(dmg)
    updated_contract = dict(contract)
    updated_contract["dmg_notarization"] = {
        "artifact": dmg.name,
        "method": plan.method,
        "status": "Accepted",
        "submission_id": submission_id,
        "ticket_stapled": True,
    }
    manifest["os_signing"] = updated_contract
    _atomic_write_json(manifest_path, manifest)
    return dmg


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Notarize and staple one normalized public macOS DMG without logging secrets"
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("public",), required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        dmg = notarize_macos_dmg(args.artifact_dir, mode=args.mode)
    except MacOSNotarizationError as exc:
        print(f"macOS DMG notarization failed: {exc}", file=sys.stderr)
        return 2
    print(f"Notarized and stapled macOS DMG: {dmg.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

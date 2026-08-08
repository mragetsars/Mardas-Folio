#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess  # nosec B404 - fixed executables and fixed argument arrays only.
import sys
import tempfile
import zipfile
from pathlib import Path, PurePath
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT_DIR = ROOT / "build" / "desktop-native"
DEFAULT_TAURI_ROOT = ROOT / "apps" / "desktop" / "src-tauri"
NATIVE_MANIFEST_NAME = "desktop-native-manifest.json"
MAX_JSON_BYTES = 1024 * 1024
WINDOWS_THUMBPRINT_RE = re.compile(r"^[0-9A-F]{40}$")
TIMESTAMP_THUMBPRINT_RE = re.compile(r"^[0-9A-F]{40}$")
APPLE_IDENTITY_RE = re.compile(
    r"^Developer ID Application: [^\x00-\x1f\x7f]{1,350} \((?P<team>[A-Z0-9]{10})\)$"
)
EVIDENCE_NAME_RE = re.compile(
    r"^Mardas-Studio-(?P<version>[^-]+)-(?P<platform>windows|macos|linux)-"
    r"(?P<arch>[A-Za-z0-9_]+)-signing-evidence\.json$"
)
SUBMISSION_ID_RE = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-"
    r"[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)


class SigningVerificationError(RuntimeError):
    """Raised when an OS trust-signing assertion cannot be proved."""


def platform_tag() -> str:
    system = platform.system()
    try:
        return {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}[system]
    except KeyError as exc:
        raise SigningVerificationError(f"Unsupported signing verification platform: {system}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SigningVerificationError(f"Required signing JSON is missing or unsafe: {path.name}")
    if path.stat().st_size <= 0 or path.stat().st_size > MAX_JSON_BYTES:
        raise SigningVerificationError(f"Signing JSON is empty or too large: {path.name}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SigningVerificationError(f"Signing JSON is invalid: {path.name}") from exc
    if not isinstance(payload, dict):
        raise SigningVerificationError(f"Signing JSON root must be an object: {path.name}")
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


def _bounded_output(value: str) -> str:
    cleaned = value.replace("\x00", "").strip()
    return cleaned[-4000:]


def _run_command(
    command: Sequence[str], *, extra_environment: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    if extra_environment:
        environment.update(extra_environment)
    try:
        completed = subprocess.run(  # nosec B603
            list(command),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )
    except (FileNotFoundError, PermissionError, OSError) as exc:
        raise SigningVerificationError(f"Required signing tool is unavailable: {command[0]}") from exc
    if completed.returncode != 0:
        detail = _bounded_output("\n".join((completed.stdout, completed.stderr)))
        suffix = f": {detail}" if detail else ""
        raise SigningVerificationError(f"Signing verification command failed ({command[0]}){suffix}")
    return completed


def _artifact_records(
    manifest: Mapping[str, Any], artifact_dir: Path
) -> list[dict[str, Any]]:
    raw_records = manifest.get("artifacts")
    if not isinstance(raw_records, list) or not raw_records:
        raise SigningVerificationError("Native manifest has no artifact inventory")
    records: list[dict[str, Any]] = []
    names: set[str] = set()
    for raw in raw_records:
        if not isinstance(raw, dict):
            raise SigningVerificationError("Native manifest contains a malformed artifact record")
        name = str(raw.get("name", ""))
        if not name or PurePath(name).name != name or name in names:
            raise SigningVerificationError(f"Native manifest artifact name is unsafe: {name!r}")
        names.add(name)
        path = artifact_dir / name
        if path.is_symlink() or not path.is_file():
            raise SigningVerificationError(f"Native artifact is missing or unsafe: {name}")
        size = path.stat().st_size
        digest = sha256_file(path)
        if raw.get("size") != size or raw.get("sha256") != digest:
            raise SigningVerificationError(f"Native artifact no longer matches its manifest: {name}")
        records.append(
            {
                "kind": str(raw.get("kind", "")),
                "name": name,
                "size": size,
                "sha256": digest,
            }
        )
    return records


def _single_artifact(
    records: Sequence[Mapping[str, Any]], *, kind: str, required: bool = True
) -> Mapping[str, Any] | None:
    matches = [item for item in records if item.get("kind") == kind]
    if len(matches) > 1 or (required and len(matches) != 1):
        raise SigningVerificationError(f"Expected exactly one {kind} artifact")
    return matches[0] if matches else None


WINDOWS_SIGNATURE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$signature = Get-AuthenticodeSignature -LiteralPath $env:MARDAS_SIGNING_ARTIFACT
[ordered]@{
  Status = [string]$signature.Status
  StatusMessage = [string]$signature.StatusMessage
  SignerThumbprint = [string]$signature.SignerCertificate.Thumbprint
  SignerSubject = [string]$signature.SignerCertificate.Subject
  TimeStamperThumbprint = [string]$signature.TimeStamperCertificate.Thumbprint
  TimeStamperSubject = [string]$signature.TimeStamperCertificate.Subject
} | ConvertTo-Json -Compress
""".strip()


def _windows_signature(path: Path, *, expected_thumbprint: str) -> dict[str, Any]:
    powershell = shutil.which("pwsh") or shutil.which("powershell.exe")
    if powershell is None:
        raise SigningVerificationError("PowerShell is required for Authenticode verification")
    completed = _run_command(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            WINDOWS_SIGNATURE_SCRIPT,
        ],
        extra_environment={"MARDAS_SIGNING_ARTIFACT": str(path)},
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise SigningVerificationError("PowerShell returned invalid Authenticode evidence") from exc
    if not isinstance(payload, dict):
        raise SigningVerificationError("PowerShell returned malformed Authenticode evidence")
    signer_thumbprint = str(payload.get("SignerThumbprint", "")).replace(" ", "").upper()
    timestamp_thumbprint = (
        str(payload.get("TimeStamperThumbprint", "")).replace(" ", "").upper()
    )
    if str(payload.get("Status", "")) != "Valid":
        raise SigningVerificationError(f"Authenticode status is not Valid for {path.name}")
    if signer_thumbprint != expected_thumbprint:
        raise SigningVerificationError(f"Authenticode signer mismatch for {path.name}")
    if not TIMESTAMP_THUMBPRINT_RE.fullmatch(timestamp_thumbprint):
        raise SigningVerificationError(f"Authenticode timestamp is missing for {path.name}")
    signer_subject = str(payload.get("SignerSubject", "")).strip()
    timestamp_subject = str(payload.get("TimeStamperSubject", "")).strip()
    if (
        not signer_subject
        or not timestamp_subject
        or any("\x00" in value or len(value.encode("utf-8")) > 4096 for value in (
            signer_subject,
            timestamp_subject,
        ))
    ):
        raise SigningVerificationError(f"Authenticode certificate metadata is invalid for {path.name}")
    return {
        "artifact": path.name,
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "certificate_thumbprint": signer_thumbprint,
        "certificate_subject": signer_subject,
        "timestamp_certificate_thumbprint": timestamp_thumbprint,
        "timestamp_certificate_subject": timestamp_subject,
        "status": "Valid",
    }


def _portable_executable_digest(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            members = [
                item
                for item in archive.infolist()
                if not item.is_dir() and item.filename.endswith("/Mardas Studio.exe")
            ]
            if len(members) != 1:
                raise SigningVerificationError(
                    "Portable package does not contain exactly one desktop executable"
                )
            item = members[0]
            if (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise SigningVerificationError("Portable desktop executable is a symbolic link")
            if item.file_size <= 0 or item.file_size > 1024 * 1024 * 1024:
                raise SigningVerificationError("Portable desktop executable size is invalid")
            digest = hashlib.sha256()
            with archive.open(item) as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise SigningVerificationError("Portable package is not a valid ZIP file") from exc


def _verify_windows(
    artifact_dir: Path,
    tauri_root: Path,
    records: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any],
    environment: Mapping[str, str],
) -> dict[str, Any]:
    expected = str(contract.get("certificate_thumbprint", "")).replace(" ", "").upper()
    configured = environment.get("MARDAS_WINDOWS_CERTIFICATE_THUMBPRINT", "")
    configured = configured.replace(" ", "").strip().upper()
    digest = environment.get("MARDAS_WINDOWS_DIGEST_ALGORITHM", "").strip().lower()
    timestamp_url = environment.get("MARDAS_WINDOWS_TIMESTAMP_URL", "").strip()
    if (
        not WINDOWS_THUMBPRINT_RE.fullmatch(expected)
        or configured != expected
        or contract.get("digest_algorithm") != "sha256"
        or digest != "sha256"
        or contract.get("timestamp_url") != timestamp_url
    ):
        raise SigningVerificationError("Windows signing thumbprint contract does not match the runner")
    installer = _single_artifact(records, kind="desktop-installer")
    assert installer is not None
    executable = tauri_root / "target" / "release" / "mardas-studio.exe"
    if executable.is_symlink() or not executable.is_file():
        raise SigningVerificationError("Signed Windows desktop executable is missing or unsafe")
    signatures = [
        _windows_signature(artifact_dir / str(installer["name"]), expected_thumbprint=expected),
        _windows_signature(executable, expected_thumbprint=expected),
    ]
    portable = _single_artifact(records, kind="desktop-portable")
    assert portable is not None
    portable_digest = _portable_executable_digest(artifact_dir / str(portable["name"]))
    portable_match = portable_digest == sha256_file(executable)
    if not portable_match:
        raise SigningVerificationError(
            "Portable package does not contain the verified signed desktop executable"
        )
    return {
        "checks": {
            "authenticode": signatures,
            "portable_executable_matches_verified_binary": portable_match,
        },
        "signer": {
            "certificate_thumbprint": expected,
            "certificate_subject": signatures[0]["certificate_subject"],
        },
    }


def _run_macos_check(command: Sequence[str]) -> str:
    completed = _run_command(command)
    return "\n".join((completed.stdout, completed.stderr))


def _codesign_details(path: Path, *, expected_identity: str) -> dict[str, str]:
    output = _run_macos_check(["codesign", "--display", "--verbose=4", str(path)])
    authorities = [
        line.partition("=")[2].strip()
        for line in output.splitlines()
        if line.strip().startswith("Authority=")
    ]
    values: dict[str, str] = {}
    for key in ("TeamIdentifier", "CDHash"):
        matches = [
            line.partition("=")[2].strip()
            for line in output.splitlines()
            if line.strip().startswith(f"{key}=")
        ]
        if matches:
            values[key] = matches[0]
    identity_match = APPLE_IDENTITY_RE.fullmatch(expected_identity)
    if (
        identity_match is None
        or not authorities
        or authorities[0] != expected_identity
        or values.get("TeamIdentifier") != identity_match.group("team")
        or not re.fullmatch(r"(?:[0-9A-Fa-f]{40}|[0-9A-Fa-f]{64})", values.get("CDHash", ""))
    ):
        raise SigningVerificationError(f"codesign identity metadata is invalid for {path.name}")
    return {
        "authority": authorities[0],
        "team_identifier": values["TeamIdentifier"],
        "cdhash": values["CDHash"].upper(),
    }


def _verify_macos(
    artifact_dir: Path,
    tauri_root: Path,
    records: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any],
    environment: Mapping[str, str],
) -> dict[str, Any]:
    identity = str(contract.get("identity", ""))
    if environment.get("APPLE_SIGNING_IDENTITY", "").strip() != identity:
        raise SigningVerificationError("macOS signing identity contract does not match the runner")
    if APPLE_IDENTITY_RE.fullmatch(identity) is None:
        raise SigningVerificationError("macOS signing identity contract is invalid")
    app_directory = tauri_root / "target" / "release" / "bundle" / "macos"
    apps = [path for path in app_directory.glob("*.app") if path.is_dir() and not path.is_symlink()]
    if len(apps) != 1:
        raise SigningVerificationError("Expected exactly one macOS application bundle")
    app = apps[0]
    dmg_record = _single_artifact(records, kind="desktop-dmg")
    assert dmg_record is not None
    dmg = artifact_dir / str(dmg_record["name"])
    submission = contract.get("dmg_notarization")
    if not isinstance(submission, dict) or (
        submission.get("artifact") != dmg.name
        or submission.get("method") != contract.get("notarization_method")
        or submission.get("status") != "Accepted"
        or SUBMISSION_ID_RE.fullmatch(str(submission.get("submission_id", ""))) is None
        or submission.get("ticket_stapled") is not True
    ):
        raise SigningVerificationError("Native manifest has no accepted DMG notarization record")

    _run_macos_check(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)])
    app_details = _codesign_details(app, expected_identity=identity)
    _run_macos_check(["codesign", "--verify", "--strict", "--verbose=2", str(dmg)])
    dmg_details = _codesign_details(dmg, expected_identity=identity)
    _run_macos_check(["spctl", "--assess", "--type", "execute", "--verbose=4", str(app)])
    _run_macos_check(
        [
            "spctl",
            "--assess",
            "--type",
            "open",
            "--context",
            "context:primary-signature",
            "--verbose=4",
            str(dmg),
        ]
    )
    _run_macos_check(["xcrun", "stapler", "validate", str(app)])
    _run_macos_check(["xcrun", "stapler", "validate", str(dmg)])
    return {
        "checks": {
            "app_codesign": True,
            "dmg_codesign": True,
            "app_gatekeeper_assessment": True,
            "dmg_gatekeeper_assessment": True,
            "app_notary_ticket_stapled": True,
            "dmg_notary_ticket_stapled": True,
            "dmg_notary_submission": dict(submission),
        },
        "signer": {
            "identity": identity,
            "team_identifier": app_details["team_identifier"],
            "app_cdhash": app_details["cdhash"],
            "dmg_cdhash": dmg_details["cdhash"],
        },
    }


def _validate_contract(
    contract: Mapping[str, Any], *, mode: str, platform_name: str
) -> tuple[str, bool]:
    if contract.get("release_mode") != mode or contract.get("verified") is not False:
        raise SigningVerificationError("Native signing contract has an invalid release state")
    required = mode == "public" and platform_name in {"windows", "macos"}
    expected_status = "pending-verification" if required else (
        "not-required" if mode == "public" else "not-requested"
    )
    if (
        contract.get("required") is not required
        or contract.get("requested") is not required
        or contract.get("status") != expected_status
    ):
        raise SigningVerificationError("Native signing contract does not match the release mode")
    return expected_status, required


def verify_runner_signing(
    artifact_dir: Path,
    *,
    tauri_root: Path,
    mode: str,
    platform_name: str,
    environment: Mapping[str, str] | None = None,
) -> Path:
    if mode not in {"draft", "public"} or platform_name not in {"windows", "macos", "linux"}:
        raise SigningVerificationError("Unsupported release mode or platform")
    artifact_dir = artifact_dir.expanduser().resolve(strict=True)
    tauri_root = tauri_root.expanduser().resolve(strict=True)
    manifest_path = artifact_dir / NATIVE_MANIFEST_NAME
    manifest = _read_json(manifest_path)
    if (
        manifest.get("schema_version") != 1
        or manifest.get("product") != "Mardas Studio native desktop artifacts"
        or manifest.get("platform") != platform_name
        or manifest.get("release_mode") != mode
    ):
        raise SigningVerificationError("Native manifest release metadata is invalid")
    version = str(manifest.get("version", ""))
    architecture = str(manifest.get("architecture", ""))
    if not version or not re.fullmatch(r"[A-Za-z0-9.]+", version):
        raise SigningVerificationError("Native manifest version is invalid")
    if not re.fullmatch(r"[A-Za-z0-9_]+", architecture):
        raise SigningVerificationError("Native manifest architecture is invalid")
    contract = manifest.get("os_signing")
    if not isinstance(contract, dict):
        raise SigningVerificationError("Native manifest has no OS signing contract")
    _, required = _validate_contract(contract, mode=mode, platform_name=platform_name)
    records = _artifact_records(manifest, artifact_dir)
    environment = dict(os.environ if environment is None else environment)
    details: dict[str, Any] = {"checks": {}, "signer": None}
    verified = False
    status = "not-requested" if mode == "draft" else "not-required"
    if required and platform_name == "windows":
        details = _verify_windows(artifact_dir, tauri_root, records, contract, environment)
        verified = True
        status = "verified"
    elif required and platform_name == "macos":
        details = _verify_macos(artifact_dir, tauri_root, records, contract, environment)
        verified = True
        status = "verified"

    evidence_name = (
        f"Mardas-Studio-{version}-{platform_name}-{architecture}-signing-evidence.json"
    )
    evidence_path = artifact_dir / evidence_name
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "product": "Mardas Studio OS signing evidence",
        "version": version,
        "platform": platform_name,
        "architecture": architecture,
        "release_mode": mode,
        "required": required,
        "requested": required,
        "verified": verified,
        "status": status,
        "method": contract.get("method"),
        "digest_algorithm": contract.get("digest_algorithm"),
        "timestamp_url": contract.get("timestamp_url"),
        "notarization_method": contract.get("notarization_method"),
        "artifacts": records,
        **details,
    }
    _atomic_write_json(evidence_path, evidence)
    evidence_digest = sha256_file(evidence_path)
    updated_contract = dict(contract)
    updated_contract.update(
        {
            "verified": verified,
            "status": status,
            "evidence": {"name": evidence_name, "sha256": evidence_digest},
        }
    )
    if details.get("signer") is not None:
        updated_contract["signer"] = details["signer"]
    updated_manifest = dict(manifest)
    updated_manifest["os_signing"] = updated_contract
    _atomic_write_json(manifest_path, updated_manifest)
    return evidence_path


def _parse_expected_counts(values: Sequence[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        platform_name, separator, raw_count = value.partition("=")
        if separator != "=" or platform_name not in {"windows", "macos", "linux"}:
            raise SigningVerificationError(
                f"Expected platform count must use PLATFORM=COUNT: {value!r}"
            )
        try:
            count = int(raw_count)
        except ValueError as exc:
            raise SigningVerificationError(f"Expected platform count is invalid: {value!r}") from exc
        if not 1 <= count <= 10 or platform_name in counts:
            raise SigningVerificationError(f"Expected platform count is invalid: {value!r}")
        counts[platform_name] = count
    if set(counts) != {"windows", "macos", "linux"}:
        raise SigningVerificationError("Evidence set must require Windows, macOS, and Linux")
    return counts


def _validate_verified_evidence(
    payload: Mapping[str, Any], *, platform_name: str, artifact_dir: Path
) -> None:
    checks = payload.get("checks")
    signer = payload.get("signer")
    if not isinstance(checks, dict) or not isinstance(signer, dict):
        raise SigningVerificationError("Verified signing evidence has no proof details")
    if platform_name == "windows":
        thumbprint = str(signer.get("certificate_thumbprint", ""))
        signatures = checks.get("authenticode")
        records = payload.get("artifacts")
        timestamp_url = str(payload.get("timestamp_url", ""))
        parsed_timestamp = urlparse(timestamp_url)
        if (
            payload.get("method") != "certificate-thumbprint"
            or payload.get("digest_algorithm") != "sha256"
            or parsed_timestamp.scheme not in {"http", "https"}
            or not parsed_timestamp.netloc
            or parsed_timestamp.username
            or parsed_timestamp.password
            or parsed_timestamp.fragment
            or any(character.isspace() for character in timestamp_url)
            or not WINDOWS_THUMBPRINT_RE.fullmatch(thumbprint)
            or not isinstance(signatures, list)
            or len(signatures) != 2
            or not isinstance(records, list)
            or checks.get("portable_executable_matches_verified_binary") is not True
        ):
            raise SigningVerificationError("Windows signing evidence proof is incomplete")
        signatures_by_name: dict[str, Mapping[str, Any]] = {}
        for signature in signatures:
            if (
                not isinstance(signature, dict)
                or signature.get("status") != "Valid"
                or signature.get("certificate_thumbprint") != thumbprint
                or not re.fullmatch(r"[0-9a-f]{64}", str(signature.get("sha256", "")))
                or not TIMESTAMP_THUMBPRINT_RE.fullmatch(
                    str(signature.get("timestamp_certificate_thumbprint", ""))
                )
            ):
                raise SigningVerificationError("Windows Authenticode proof is incomplete")
            artifact_name = str(signature.get("artifact", ""))
            if not artifact_name or artifact_name in signatures_by_name:
                raise SigningVerificationError("Windows Authenticode proof is ambiguous")
            signatures_by_name[artifact_name] = signature
        installer_records = [item for item in records if item.get("kind") == "desktop-installer"]
        portable_records = [item for item in records if item.get("kind") == "desktop-portable"]
        if len(installer_records) != 1 or len(portable_records) != 1:
            raise SigningVerificationError("Windows evidence artifact inventory is incomplete")
        installer = installer_records[0]
        installer_signature = signatures_by_name.get(str(installer.get("name", "")))
        binary_signature = signatures_by_name.get("mardas-studio.exe")
        if (
            installer_signature is None
            or installer_signature.get("sha256") != installer.get("sha256")
            or binary_signature is None
            or binary_signature.get("sha256")
            != _portable_executable_digest(
                artifact_dir / str(portable_records[0].get("name", ""))
            )
        ):
            raise SigningVerificationError("Windows signature proof is not bound to release payloads")
    elif platform_name == "macos":
        identity = str(signer.get("identity", ""))
        identity_match = APPLE_IDENTITY_RE.fullmatch(identity)
        submission = checks.get("dmg_notary_submission")
        records = payload.get("artifacts")
        required_checks = {
            "app_codesign",
            "dmg_codesign",
            "app_gatekeeper_assessment",
            "dmg_gatekeeper_assessment",
            "app_notary_ticket_stapled",
            "dmg_notary_ticket_stapled",
        }
        if (
            payload.get("method") != "developer-id"
            or payload.get("notarization_method")
            not in {"app-store-connect-api", "apple-id"}
            or identity_match is None
            or signer.get("team_identifier") != identity_match.group("team")
            or any(checks.get(name) is not True for name in required_checks)
            or not isinstance(submission, dict)
            or submission.get("status") != "Accepted"
            or submission.get("method") != payload.get("notarization_method")
            or SUBMISSION_ID_RE.fullmatch(str(submission.get("submission_id", ""))) is None
            or submission.get("ticket_stapled") is not True
            or not isinstance(records, list)
            or not any(
                isinstance(record, dict)
                and record.get("kind") == "desktop-dmg"
                and record.get("name") == submission.get("artifact")
                for record in records
            )
        ):
            raise SigningVerificationError("macOS signing evidence proof is incomplete")
    else:
        raise SigningVerificationError("Linux must not claim OS trust-signing verification")


def verify_evidence_set(
    artifact_dir: Path,
    *,
    version: str,
    mode: str,
    expected_counts: Mapping[str, int],
) -> list[Path]:
    if mode not in {"draft", "public"}:
        raise SigningVerificationError(f"Unsupported evidence release mode: {mode}")
    artifact_dir = artifact_dir.expanduser().resolve(strict=True)
    evidence_paths = sorted(artifact_dir.glob("Mardas-Studio-*-signing-evidence.json"))
    if not evidence_paths:
        raise SigningVerificationError("Release has no platform signing evidence")
    observed_counts = {"windows": 0, "macos": 0, "linux": 0}
    targets: set[tuple[str, str]] = set()
    for path in evidence_paths:
        match = EVIDENCE_NAME_RE.fullmatch(path.name)
        if match is None or match.group("version") != version:
            raise SigningVerificationError(f"Signing evidence filename is invalid: {path.name}")
        payload = _read_json(path)
        platform_name = match.group("platform")
        architecture = match.group("arch")
        if (
            payload.get("schema_version") != 1
            or payload.get("product") != "Mardas Studio OS signing evidence"
            or payload.get("version") != version
            or payload.get("platform") != platform_name
            or payload.get("architecture") != architecture
            or payload.get("release_mode") != mode
        ):
            raise SigningVerificationError(f"Signing evidence metadata is invalid: {path.name}")
        target = (platform_name, architecture)
        if target in targets:
            raise SigningVerificationError(f"Duplicate signing evidence target: {target}")
        targets.add(target)
        observed_counts[platform_name] += 1
        os_signing_required = mode == "public" and platform_name in {"windows", "macos"}
        expected_status = "verified" if os_signing_required else (
            "not-required" if mode == "public" else "not-requested"
        )
        if (
            payload.get("required") is not os_signing_required
            or payload.get("requested") is not os_signing_required
            or payload.get("verified") is not os_signing_required
            or payload.get("status") != expected_status
        ):
            raise SigningVerificationError(f"Signing evidence state is invalid: {path.name}")
        if not os_signing_required and payload.get("signer") is not None:
            raise SigningVerificationError(f"Unsigned evidence must not claim a signer: {path.name}")
        records = payload.get("artifacts")
        if not isinstance(records, list) or not records:
            raise SigningVerificationError(f"Signing evidence has no artifact inventory: {path.name}")
        for record in records:
            if not isinstance(record, dict):
                raise SigningVerificationError(f"Signing evidence artifact is malformed: {path.name}")
            name = str(record.get("name", ""))
            if not name or PurePath(name).name != name:
                raise SigningVerificationError(f"Signing evidence artifact name is unsafe: {name!r}")
            artifact = artifact_dir / name
            if artifact.is_symlink() or not artifact.is_file():
                raise SigningVerificationError(f"Evidence references a missing artifact: {name}")
            if (
                record.get("size") != artifact.stat().st_size
                or record.get("sha256") != sha256_file(artifact)
            ):
                raise SigningVerificationError(f"Evidence artifact integrity failed: {name}")
        if os_signing_required:
            try:
                _validate_verified_evidence(
                    payload,
                    platform_name=platform_name,
                    artifact_dir=artifact_dir,
                )
            except SigningVerificationError as exc:
                raise SigningVerificationError(
                    f"Verified signing evidence is incomplete: {path.name}"
                ) from exc
    if observed_counts != dict(expected_counts):
        raise SigningVerificationError(
            f"Signing evidence target counts are incomplete: {observed_counts!r}"
        )
    return evidence_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify OS trust signatures and record non-secret release evidence"
    )
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--tauri-root", type=Path, default=DEFAULT_TAURI_ROOT)
    parser.add_argument("--mode", choices=("draft", "public"), default="draft")
    parser.add_argument("--verify-evidence-set", action="store_true")
    parser.add_argument("--version")
    parser.add_argument(
        "--expected-platform-count",
        action="append",
        default=[],
        metavar="PLATFORM=COUNT",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.verify_evidence_set:
            if not args.version:
                raise SigningVerificationError("--version is required for evidence-set verification")
            counts = _parse_expected_counts(args.expected_platform_count)
            paths = verify_evidence_set(
                args.artifact_dir,
                version=args.version,
                mode=args.mode,
                expected_counts=counts,
            )
            print(f"Platform signing evidence set verified: {len(paths)} target(s)")
        else:
            if args.version or args.expected_platform_count:
                raise SigningVerificationError(
                    "--version and --expected-platform-count require --verify-evidence-set"
                )
            path = verify_runner_signing(
                args.artifact_dir,
                tauri_root=args.tauri_root,
                mode=args.mode,
                platform_name=platform_tag(),
            )
            print(f"Platform signing evidence recorded: {path.name}")
    except (SigningVerificationError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Platform signing verification failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

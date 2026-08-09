from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load():
    path = SCRIPTS / "verify_platform_signing.py"
    spec = importlib.util.spec_from_file_location("verify_platform_signing", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_manifest(
    module,
    artifact_dir: Path,
    *,
    platform_name: str,
    architecture: str,
    mode: str,
    artifacts: list[tuple[str, str, bytes]],
    contract: dict[str, object],
) -> None:
    records = []
    for name, kind, data in artifacts:
        path = artifact_dir / name
        path.write_bytes(data)
        records.append(
            {
                "schema_version": 1,
                "product": "Mardas Folio",
                "kind": kind,
                "version": "1.31.0",
                "platform": platform_name,
                "architecture": architecture,
                "name": name,
                "size": len(data),
                "sha256": module.sha256_file(path),
            }
        )
    manifest = {
        "schema_version": 1,
        "product": "Mardas Folio native desktop artifacts",
        "version": "1.31.0",
        "platform": platform_name,
        "architecture": architecture,
        "release_mode": mode,
        "os_signing": contract,
        "signed_updater_artifacts": False,
        "artifacts": records,
    }
    (artifact_dir / "desktop-native-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


@pytest.mark.parametrize(
    ("mode", "expected_status"),
    (("draft", "not-requested"), ("public", "not-required")),
)
def test_non_signing_target_records_explicit_evidence_without_calling_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected_status: str,
) -> None:
    module = _load()
    artifact_dir = tmp_path / "artifacts"
    tauri_root = tmp_path / "tauri"
    artifact_dir.mkdir()
    tauri_root.mkdir()
    _write_manifest(
        module,
        artifact_dir,
        platform_name="linux",
        architecture="x86_64",
        mode=mode,
        artifacts=[("Mardas-Folio-1.31.0-linux-x86_64.AppImage", "desktop-appimage", b"app")],
        contract={
            "release_mode": mode,
            "required": False,
            "requested": False,
            "verified": False,
            "status": expected_status,
            "method": None,
        },
    )

    def unexpected(*args, **kwargs):
        raise AssertionError("a non-signing target must not invoke a signing tool")

    monkeypatch.setattr(module, "_run_command", unexpected)
    evidence_path = module.verify_runner_signing(
        artifact_dir,
        tauri_root=tauri_root,
        mode=mode,
        platform_name="linux",
        environment={},
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    manifest = json.loads(
        (artifact_dir / "desktop-native-manifest.json").read_text(encoding="utf-8")
    )
    assert evidence["status"] == expected_status
    assert evidence["verified"] is False
    assert evidence["signer"] is None
    assert manifest["os_signing"]["status"] == expected_status
    assert manifest["os_signing"]["verified"] is False
    assert manifest["os_signing"]["evidence"]["sha256"] == module.sha256_file(evidence_path)


def test_windows_authenticode_timestamp_and_portable_payload_are_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    artifact_dir = tmp_path / "artifacts"
    tauri_root = tmp_path / "tauri"
    artifact_dir.mkdir()
    executable = tauri_root / "target" / "release" / "mardas-folio.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"signed-binary")
    portable_name = "Mardas-Folio-1.31.0-windows-x86_64-portable.zip"
    portable = artifact_dir / portable_name
    with zipfile.ZipFile(portable, "w") as archive:
        archive.writestr(
            "Mardas-Folio-1.31.0-windows-x86_64-portable/Mardas Folio.exe",
            executable.read_bytes(),
        )
    portable_data = portable.read_bytes()
    portable.unlink()
    _write_manifest(
        module,
        artifact_dir,
        platform_name="windows",
        architecture="x86_64",
        mode="public",
        artifacts=[
            (
                "Mardas-Folio-1.31.0-windows-x86_64-setup.exe",
                "desktop-installer",
                b"signed-installer",
            ),
            (portable_name, "desktop-portable", portable_data),
        ],
        contract={
            "release_mode": "public",
            "required": True,
            "requested": True,
            "verified": False,
            "status": "pending-verification",
            "method": "certificate-thumbprint",
            "certificate_thumbprint": "A" * 40,
            "digest_algorithm": "sha256",
            "timestamp_url": "https://timestamp.example.invalid",
        },
    )
    signature = json.dumps(
        {
            "Status": "Valid",
            "StatusMessage": "Signature verified.",
            "SignerThumbprint": "A" * 40,
            "SignerSubject": "CN=Example Publisher",
            "TimeStamperThumbprint": "B" * 40,
            "TimeStamperSubject": "CN=Example Timestamp",
        }
    )

    monkeypatch.setattr(module.shutil, "which", lambda name: "pwsh")
    monkeypatch.setattr(
        module,
        "_run_command",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, signature, ""),
    )
    evidence_path = module.verify_runner_signing(
        artifact_dir,
        tauri_root=tauri_root,
        mode="public",
        platform_name="windows",
        environment={
            "MARDAS_WINDOWS_CERTIFICATE_THUMBPRINT": "A" * 40,
            "MARDAS_WINDOWS_DIGEST_ALGORITHM": "sha256",
            "MARDAS_WINDOWS_TIMESTAMP_URL": "https://timestamp.example.invalid",
        },
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["verified"] is True
    assert evidence["status"] == "verified"
    assert len(evidence["checks"]["authenticode"]) == 2
    assert evidence["checks"]["portable_executable_matches_verified_binary"] is True
    module._validate_verified_evidence(
        evidence, platform_name="windows", artifact_dir=artifact_dir
    )

    invalid_signature = json.loads(signature)
    invalid_signature["TimeStamperThumbprint"] = ""
    monkeypatch.setattr(
        module,
        "_run_command",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, json.dumps(invalid_signature), ""
        ),
    )
    with pytest.raises(module.SigningVerificationError, match="timestamp"):
        module._windows_signature(executable, expected_thumbprint="A" * 40)


def test_macos_requires_codesign_gatekeeper_and_stapled_notary_tickets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    artifact_dir = tmp_path / "artifacts"
    tauri_root = tmp_path / "tauri"
    artifact_dir.mkdir()
    app = tauri_root / "target" / "release" / "bundle" / "macos" / "Mardas Folio.app"
    app.mkdir(parents=True)
    identity = "Developer ID Application: Example (ABCDEFGHIJ)"
    _write_manifest(
        module,
        artifact_dir,
        platform_name="macos",
        architecture="arm64",
        mode="public",
        artifacts=[("Mardas-Folio-1.31.0-macos-arm64.dmg", "desktop-dmg", b"signed-dmg")],
        contract={
            "release_mode": "public",
            "required": True,
            "requested": True,
            "verified": False,
            "status": "pending-verification",
            "method": "developer-id",
            "identity": identity,
            "notarization_method": "app-store-connect-api",
            "dmg_notarization": {
                "artifact": "Mardas-Folio-1.31.0-macos-arm64.dmg",
                "method": "app-store-connect-api",
                "status": "Accepted",
                "submission_id": "01234567-89ab-cdef-0123-456789abcdef",
                "ticket_stapled": True,
            },
        },
    )
    commands: list[list[str]] = []

    def successful(command, **kwargs):
        commands.append(list(command))
        details = ""
        if command[0] == "codesign" and "--display" in command:
            details = (
                f"Authority={identity}\n"
                "Authority=Developer ID Certification Authority\n"
                "TeamIdentifier=ABCDEFGHIJ\n"
                f"CDHash={'A' * 40}\n"
            )
        return subprocess.CompletedProcess(command, 0, "", details)

    monkeypatch.setattr(module, "_run_command", successful)
    evidence_path = module.verify_runner_signing(
        artifact_dir,
        tauri_root=tauri_root,
        mode="public",
        platform_name="macos",
        environment={"APPLE_SIGNING_IDENTITY": identity},
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["verified"] is True
    assert evidence["checks"] == {
        "app_codesign": True,
        "dmg_codesign": True,
        "app_gatekeeper_assessment": True,
        "dmg_gatekeeper_assessment": True,
        "app_notary_ticket_stapled": True,
        "dmg_notary_ticket_stapled": True,
        "dmg_notary_submission": {
            "artifact": "Mardas-Folio-1.31.0-macos-arm64.dmg",
            "method": "app-store-connect-api",
            "status": "Accepted",
            "submission_id": "01234567-89ab-cdef-0123-456789abcdef",
            "ticket_stapled": True,
        },
    }
    assert sum(command[:2] == ["xcrun", "stapler"] for command in commands) == 2
    assert sum(command[0] == "spctl" for command in commands) == 2
    module._validate_verified_evidence(
        evidence, platform_name="macos", artifact_dir=artifact_dir
    )


def test_public_verification_failure_leaves_manifest_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    artifact_dir = tmp_path / "artifacts"
    tauri_root = tmp_path / "tauri"
    artifact_dir.mkdir()
    app = tauri_root / "target" / "release" / "bundle" / "macos" / "Mardas Folio.app"
    app.mkdir(parents=True)
    identity = "Developer ID Application: Example (ABCDEFGHIJ)"
    _write_manifest(
        module,
        artifact_dir,
        platform_name="macos",
        architecture="arm64",
        mode="public",
        artifacts=[("Mardas-Folio-1.31.0-macos-arm64.dmg", "desktop-dmg", b"dmg")],
        contract={
            "release_mode": "public",
            "required": True,
            "requested": True,
            "verified": False,
            "status": "pending-verification",
            "method": "developer-id",
            "identity": identity,
            "notarization_method": "app-store-connect-api",
            "dmg_notarization": {
                "artifact": "Mardas-Folio-1.31.0-macos-arm64.dmg",
                "method": "app-store-connect-api",
                "status": "Accepted",
                "submission_id": "01234567-89ab-cdef-0123-456789abcdef",
                "ticket_stapled": True,
            },
        },
    )

    def failed(command, **kwargs):
        raise module.SigningVerificationError("Signing verification command failed")

    monkeypatch.setattr(module, "_run_command", failed)
    with pytest.raises(module.SigningVerificationError, match="command failed"):
        module.verify_runner_signing(
            artifact_dir,
            tauri_root=tauri_root,
            mode="public",
            platform_name="macos",
            environment={"APPLE_SIGNING_IDENTITY": identity},
        )
    manifest = json.loads(
        (artifact_dir / "desktop-native-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["os_signing"]["status"] == "pending-verification"
    assert not list(artifact_dir.glob("*-signing-evidence.json"))


def test_release_evidence_set_is_complete_and_bound_to_artifact_hashes(
    tmp_path: Path,
) -> None:
    module = _load()
    targets = (
        ("windows", "x86_64"),
        ("macos", "arm64"),
        ("macos", "x86_64"),
        ("linux", "x86_64"),
    )
    for platform_name, architecture in targets:
        artifact_name = f"Mardas-Folio-1.31.0-{platform_name}-{architecture}.bin"
        artifact = tmp_path / artifact_name
        artifact.write_bytes(f"{platform_name}-{architecture}".encode())
        evidence = {
            "schema_version": 1,
            "product": "Mardas Folio OS signing evidence",
            "version": "1.31.0",
            "platform": platform_name,
            "architecture": architecture,
            "release_mode": "draft",
            "required": False,
            "requested": False,
            "verified": False,
            "status": "not-requested",
            "method": None,
            "artifacts": [
                {
                    "kind": "test",
                    "name": artifact_name,
                    "size": artifact.stat().st_size,
                    "sha256": module.sha256_file(artifact),
                }
            ],
            "checks": {},
            "signer": None,
        }
        path = (
            tmp_path
            / f"Mardas-Folio-1.31.0-{platform_name}-{architecture}-signing-evidence.json"
        )
        path.write_text(json.dumps(evidence), encoding="utf-8")

    paths = module.verify_evidence_set(
        tmp_path,
        version="1.31.0",
        mode="draft",
        expected_counts={"windows": 1, "macos": 2, "linux": 1},
    )
    assert len(paths) == 4

    artifact = tmp_path / "Mardas-Folio-1.31.0-linux-x86_64.bin"
    artifact.write_bytes(b"tampered")
    with pytest.raises(module.SigningVerificationError, match="integrity"):
        module.verify_evidence_set(
            tmp_path,
            version="1.31.0",
            mode="draft",
            expected_counts={"windows": 1, "macos": 2, "linux": 1},
        )

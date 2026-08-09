from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
IDENTITY = "Developer ID Application: Example (ABCDEFGHIJ)"
SUBMISSION_ID = "01234567-89ab-cdef-0123-456789abcdef"


def _load():
    path = SCRIPTS / "notarize_macos_dmg.py"
    spec = importlib.util.spec_from_file_location("notarize_macos_dmg", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_manifest(
    module,
    artifact_dir: Path,
    *,
    method: str,
    architecture: str = "arm64",
) -> Path:
    name = f"Mardas-Folio-1.31.0-macos-{architecture}.dmg"
    dmg = artifact_dir / name
    dmg.write_bytes(b"signed-dmg-before-stapling")
    manifest = {
        "schema_version": 1,
        "product": "Mardas Folio native desktop artifacts",
        "version": "1.31.0",
        "platform": "macos",
        "architecture": architecture,
        "release_mode": "public",
        "os_signing": {
            "release_mode": "public",
            "required": True,
            "requested": True,
            "verified": False,
            "status": "pending-verification",
            "method": "developer-id",
            "identity": IDENTITY,
            "notarization_method": method,
        },
        "signed_updater_artifacts": True,
        "artifacts": [
            {
                "schema_version": 1,
                "product": "Mardas Folio",
                "kind": "desktop-dmg",
                "version": "1.31.0",
                "platform": "macos",
                "architecture": architecture,
                "name": name,
                "size": dmg.stat().st_size,
                "sha256": module.sha256_file(dmg),
            }
        ],
    }
    (artifact_dir / "desktop-native-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return dmg


def _api_environment(key_path: Path) -> dict[str, str]:
    return {
        "APPLE_API_ISSUER": SUBMISSION_ID,
        "APPLE_API_KEY": "K123456789",
        "APPLE_API_KEY_PATH": str(key_path),
        "APPLE_TEAM_ID": "ABCDEFGHIJ",
    }


def _write_api_key(path: Path) -> None:
    path.write_text(
        "-----BEGIN PRIVATE KEY-----\n"
        + "A" * 96
        + "\n-----END PRIVATE KEY-----\n",
        encoding="utf-8",
    )


def test_api_notarization_uses_fixed_argv_and_atomically_refreshes_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    dmg = _write_manifest(module, artifact_dir, method="app-store-connect-api")
    key_path = tmp_path / "AuthKey_K123456789.p8"
    _write_api_key(key_path)
    commands: list[list[str]] = []
    invocations: list[dict[str, object]] = []

    def successful(command, **kwargs):
        commands.append(list(command))
        invocations.append(dict(kwargs))
        if command[:3] == ["xcrun", "notarytool", "submit"]:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps({"status": "Accepted", "id": SUBMISSION_ID}),
                "",
            )
        if command[:3] == ["xcrun", "stapler", "staple"]:
            dmg.write_bytes(dmg.read_bytes() + b"-stapled-ticket")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(module.subprocess, "run", successful)
    result = module.notarize_macos_dmg(
        artifact_dir,
        mode="public",
        platform_name="macos",
        environment=_api_environment(key_path),
    )

    assert result == dmg
    assert commands == [
        [
            "xcrun",
            "notarytool",
            "submit",
            str(dmg),
            "--wait",
            "--output-format",
            "json",
            "--issuer",
            SUBMISSION_ID,
            "--key-id",
            "K123456789",
            "--key",
            str(key_path),
        ],
        ["xcrun", "stapler", "staple", "-v", str(dmg)],
        ["xcrun", "stapler", "validate", str(dmg)],
    ]
    assert all(invocation.get("check") is False for invocation in invocations)
    assert all(invocation.get("capture_output") is True for invocation in invocations)
    assert all("shell" not in invocation for invocation in invocations)

    manifest = json.loads(
        (artifact_dir / "desktop-native-manifest.json").read_text(encoding="utf-8")
    )
    record = manifest["artifacts"][0]
    assert record["size"] == dmg.stat().st_size
    assert record["sha256"] == module.sha256_file(dmg)
    assert manifest["os_signing"]["dmg_notarization"] == {
        "artifact": dmg.name,
        "method": "app-store-connect-api",
        "status": "Accepted",
        "submission_id": SUBMISSION_ID,
        "ticket_stapled": True,
    }
    assert not list(artifact_dir.glob(".desktop-native-manifest.json.*.tmp"))


def test_apple_id_route_is_structured_and_command_failure_does_not_leak_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _load()
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    _write_manifest(module, artifact_dir, method="apple-id")
    apple_id = "release@example.invalid"
    password = "secret-app-password"
    environment = {
        "APPLE_ID": apple_id,
        "APPLE_PASSWORD": password,
        "APPLE_TEAM_ID": "ABCDEFGHIJ",
    }
    commands: list[list[str]] = []

    def failed(command, **kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 1, password, apple_id)

    monkeypatch.setattr(module.subprocess, "run", failed)
    with pytest.raises(module.MacOSNotarizationError) as caught:
        module.notarize_macos_dmg(
            artifact_dir,
            mode="public",
            platform_name="macos",
            environment=environment,
        )
    captured = capsys.readouterr()
    combined = str(caught.value) + captured.out + captured.err
    assert password not in combined
    assert apple_id not in combined
    assert commands == [
        [
            "xcrun",
            "notarytool",
            "submit",
            str(artifact_dir / "Mardas-Folio-1.31.0-macos-arm64.dmg"),
            "--wait",
            "--output-format",
            "json",
            "--apple-id",
            apple_id,
            "--password",
            password,
            "--team-id",
            "ABCDEFGHIJ",
        ]
    ]


@pytest.mark.parametrize(
    "output",
    (
        "not-json",
        json.dumps({"status": "In Progress", "id": SUBMISSION_ID}),
        json.dumps({"status": "Invalid", "id": SUBMISSION_ID}),
        json.dumps({"status": "Accepted", "id": "not-a-uuid"}),
    ),
)
def test_only_accepted_well_formed_notarytool_json_can_reach_stapling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output: str,
) -> None:
    module = _load()
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    _write_manifest(module, artifact_dir, method="app-store-connect-api")
    key_path = tmp_path / "AuthKey_K123456789.p8"
    _write_api_key(key_path)
    commands: list[list[str]] = []

    def response(command, **kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(module.subprocess, "run", response)
    with pytest.raises(module.MacOSNotarizationError):
        module.notarize_macos_dmg(
            artifact_dir,
            mode="public",
            platform_name="macos",
            environment=_api_environment(key_path),
        )
    assert len(commands) == 1
    assert commands[0][:3] == ["xcrun", "notarytool", "submit"]


def test_scope_ambiguity_and_multiple_normalized_dmgs_fail_before_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load()
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    _write_manifest(module, artifact_dir, method="app-store-connect-api")
    key_path = tmp_path / "AuthKey_K123456789.p8"
    _write_api_key(key_path)
    environment = {
        **_api_environment(key_path),
        "APPLE_ID": "release@example.invalid",
        "APPLE_PASSWORD": "secret-app-password",
    }

    def unexpected(*args, **kwargs):
        raise AssertionError("invalid scope or credentials must not invoke Apple tools")

    monkeypatch.setattr(module.subprocess, "run", unexpected)
    with pytest.raises(module.MacOSNotarizationError, match="public"):
        module.notarize_macos_dmg(
            artifact_dir,
            mode="draft",
            platform_name="macos",
            environment=environment,
        )
    with pytest.raises(module.MacOSNotarizationError, match="macOS"):
        module.notarize_macos_dmg(
            artifact_dir,
            mode="public",
            platform_name="linux",
            environment=environment,
        )
    with pytest.raises(module.MacOSNotarizationError, match="unambiguous"):
        module.notarize_macos_dmg(
            artifact_dir,
            mode="public",
            platform_name="macos",
            environment=environment,
        )

    environment.pop("APPLE_ID")
    environment.pop("APPLE_PASSWORD")
    (artifact_dir / "Mardas-Folio-1.31.0-macos-x86_64.dmg").write_bytes(b"extra")
    with pytest.raises(module.MacOSNotarizationError, match="exactly one"):
        module.notarize_macos_dmg(
            artifact_dir,
            mode="public",
            platform_name="macos",
            environment=environment,
        )


def test_release_workflow_notarizes_before_verification_without_merged_manifests() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    notarize_step = "- name: Notarize and staple macOS disk image"
    verify_step = "- name: Verify platform trust signature and record evidence"
    assert notarize_step in workflow
    assert "python scripts/notarize_macos_dmg.py" in workflow
    assert "!matrix.linux && env.MARDAS_RELEASE_MODE == 'public'" in workflow
    assert workflow.index(notarize_step) < workflow.index(verify_step)
    assert "build/desktop-native/desktop-native-manifest.json" not in workflow

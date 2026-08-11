from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from release_provenance import (  # noqa: E402
    ArtifactRecord,
    DistributionRecord,
    ReleaseProvenanceError,
    artifact_kind,
    build_release_manifest,
    deterministic_zip,
    generate_spdx_document,
    parse_checksums,
    runtime_dependency_closure,
    validate_release_manifest,
    validate_spdx_document,
    verify_checksums,
    verify_desktop_installer_artifact,
    verify_offline_bundle,
    verify_standalone_runtime,
    write_checksums,
    write_json,
)


def _load_script(name: str):
    path = SCRIPTS / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_dependency_closure_respects_markers_and_transitive_edges() -> None:
    records = [
        DistributionRecord(
            name="mardas-folio",
            version="1.21.0",
            summary="root",
            license_expression="MIT",
            requirements=(
                "alpha>=1",
                "legacy; python_version < '3.0'",
            ),
            project_urls=(),
        ),
        DistributionRecord(
            name="alpha",
            version="2.0",
            summary="alpha",
            license_expression="MIT",
            requirements=("beta>=1",),
            project_urls=(),
        ),
        DistributionRecord(
            name="beta",
            version="3.0",
            summary="beta",
            license_expression="Apache-2.0",
            requirements=(),
            project_urls=(),
        ),
        DistributionRecord(
            name="legacy",
            version="1.0",
            summary="legacy",
            license_expression="MIT",
            requirements=(),
            project_urls=(),
        ),
    ]

    selected, relationships = runtime_dependency_closure(records)

    assert [item.name for item in selected] == ["alpha", "beta", "mardas-folio"]
    assert relationships == [("alpha", "beta"), ("mardas-folio", "alpha")]


def test_spdx_document_is_deterministic_and_valid(tmp_path: Path) -> None:
    artifact = tmp_path / "mardas_folio-1.21.0-py3-none-any.whl"
    artifact.write_bytes(b"wheel")
    records = [
        DistributionRecord(
            name="mardas-folio",
            version="1.21.0",
            summary="Publisher",
            license_expression="MIT",
            requirements=("alpha>=1",),
            project_urls=("Repository, https://example.invalid/repo",),
        ),
        DistributionRecord(
            name="alpha",
            version="2.0",
            summary="Dependency",
            license_expression="Apache-2.0",
            requirements=(),
            project_urls=(),
        ),
    ]
    kwargs = dict(
        distributions=records,
        relationships=[("mardas-folio", "alpha")],
        artifact_paths=[artifact],
        root_name="mardas-folio",
        source_revision="abc123",
        epoch=1_735_689_600,
    )

    first = generate_spdx_document(**kwargs)
    second = generate_spdx_document(**kwargs)

    assert first == second
    assert first["creationInfo"]["created"] == "2025-01-01T00:00:00Z"
    assert len(first["packages"]) == 2
    validate_spdx_document(first, expected_version="1.21.0")


def test_deterministic_zip_has_stable_bytes_and_no_unsafe_members(tmp_path: Path) -> None:
    members = [
        ("README.md", b"hello\n", 0o644),
        ("bin/install.sh", b"#!/bin/sh\n", 0o755),
    ]
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    deterministic_zip(first, members, epoch=1_735_689_600)
    deterministic_zip(second, list(reversed(members)), epoch=1_735_689_600)

    assert first.read_bytes() == second.read_bytes()
    with pytest.raises(ReleaseProvenanceError, match="Unsafe ZIP member"):
        deterministic_zip(tmp_path / "unsafe.zip", [("../escape", b"x", 0o644)], epoch=1_735_689_600)


def test_release_manifest_and_checksums_detect_tampering(tmp_path: Path) -> None:
    wheel = tmp_path / "mardas_folio-1.21.0-py3-none-any.whl"
    sdist = tmp_path / "mardas_folio-1.21.0.tar.gz"
    sbom = tmp_path / "mardas-folio-1.21.0.spdx.json"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    spdx = generate_spdx_document(
        distributions=[
            DistributionRecord(
                name="mardas-folio",
                version="1.21.0",
                summary="Publisher",
                license_expression="MIT",
                requirements=(),
                project_urls=(),
            )
        ],
        relationships=[],
        artifact_paths=[wheel, sdist],
        root_name="mardas-folio",
        source_revision="abc",
        epoch=1_735_689_600,
    )
    write_json(sbom, spdx)
    records = [
        ArtifactRecord(wheel.name, "python-wheel", wheel.stat().st_size, hashlib.sha256(wheel.read_bytes()).hexdigest()),
        ArtifactRecord(sdist.name, "source-distribution", sdist.stat().st_size, hashlib.sha256(sdist.read_bytes()).hexdigest()),
        ArtifactRecord(sbom.name, "spdx-sbom", sbom.stat().st_size, hashlib.sha256(sbom.read_bytes()).hexdigest()),
    ]
    manifest = build_release_manifest(
        records=records,
        version="1.21.0",
        source_revision="abc",
        epoch=1_735_689_600,
    )
    manifest_path = tmp_path / "RELEASE-MANIFEST.json"
    write_json(manifest_path, manifest)
    checksum_records = records + [
        ArtifactRecord(
            manifest_path.name,
            "json-metadata",
            manifest_path.stat().st_size,
            hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        )
    ]
    checksums = tmp_path / "CHECKSUMS.sha256"
    write_checksums(checksums, checksum_records)

    validate_release_manifest(
        manifest,
        directory=tmp_path,
        expected_version="1.21.0",
        require_sbom=True,
        minimum_bundle_count=0,
    )
    verify_checksums(tmp_path, checksums)
    assert parse_checksums(checksums)[wheel.name] == hashlib.sha256(b"wheel").hexdigest()

    wheel.write_bytes(b"tampered")
    with pytest.raises(ReleaseProvenanceError, match="Checksum mismatch"):
        verify_checksums(tmp_path, checksums)


def test_offline_bundle_manifest_and_checksums_are_verified(tmp_path: Path) -> None:
    builder = _load_script("build_offline_bundle.py")
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "mardas_folio-1.21.0-py3-none-any.whl").write_bytes(b"project")
    (wheelhouse / "dependency-2.0-py3-none-any.whl").write_bytes(b"dependency")
    members = builder._bundle_members(
        wheelhouse,
        version="1.21.0",
        platform_label="linux-x64",
        python_version="3.12.0",
        epoch=1_735_689_600,
    )
    bundle = tmp_path / "mardas-folio-1.21.0-offline-linux-x64-py312.zip"
    deterministic_zip(bundle, members, epoch=1_735_689_600)

    verify_offline_bundle(bundle, expected_version="1.21.0")

    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read("BUNDLE-MANIFEST.json"))
        assert manifest["browser_included"] is False
        assert manifest["installation_mode"] == "pip-no-index-wheelhouse"



def test_standalone_runtime_manifest_and_checksums_are_verified(tmp_path: Path) -> None:
    version = "1.23.0"
    root = f"Mardas-Folio-{version}-runtime-windows-x86_64"
    files = {
        "mardas-sidecar.exe": b"sidecar",
        "_internal/runtime/chromium/chrome-headless-shell.exe": b"chromium",
    }
    inventory = [
        {
            "path": name,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        for name, data in sorted(files.items())
    ]
    manifest = {
        "schema_version": 1,
        "version": version,
        "engine_api_version": "1.0.0",
        "protocol": "mardas-sidecar",
        "protocol_version": 1,
        "browser_bundled": True,
        "files": inventory,
    }
    archive_path = tmp_path / f"{root}.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, data in files.items():
            archive.writestr(f"{root}/{name}", data)
        archive.writestr(
            f"{root}/runtime-manifest.json",
            json.dumps(manifest).encode("utf-8"),
        )

    verify_standalone_runtime(archive_path, expected_version=version)

    with zipfile.ZipFile(archive_path, "a") as archive:
        archive.writestr(f"{root}/unexpected.txt", b"tampered")
    with pytest.raises(ReleaseProvenanceError, match="archive inventory mismatch"):
        verify_standalone_runtime(archive_path, expected_version=version)


def test_desktop_installer_is_classified_and_verified(tmp_path: Path) -> None:
    version = "1.24.0"
    installer = tmp_path / f"Mardas-Folio-{version}-windows-x86_64-setup.exe"
    installer.write_bytes(b"MZ" + b"\0" * (1024 * 1024 + 32))

    assert artifact_kind(installer.name) == "desktop-installer"
    verify_desktop_installer_artifact(installer, expected_version=version)

    installer.write_bytes(b"NO" + b"\0" * (1024 * 1024 + 32))
    with pytest.raises(ReleaseProvenanceError, match="PE header"):
        verify_desktop_installer_artifact(installer, expected_version=version)


def test_release_manifest_requires_all_native_desktop_platforms(tmp_path: Path) -> None:
    version = "1.29.0"
    names = (
        f"Mardas-Folio-{version}-windows-x86_64-setup.exe",
        f"Mardas-Folio-{version}-windows-x86_64-portable.zip",
        f"Mardas-Folio-{version}-macos-arm64.dmg",
        f"Mardas-Folio-{version}-linux-x86_64.AppImage",
        f"Mardas-Folio-{version}-linux-x86_64.deb",
    )
    records = []
    for index, name in enumerate(names, 1):
        path = tmp_path / name
        path.write_bytes(bytes([index]) * 128)
        records.append(
            ArtifactRecord(
                name=name,
                kind=artifact_kind(name),
                size=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    manifest = build_release_manifest(
        records=records,
        version=version,
        source_revision="abc",
        epoch=1_735_689_600,
    )
    assert manifest["summary"]["native_desktop_artifact_count"] == 5
    assert manifest["summary"]["desktop_platforms"] == ["linux", "macos", "windows"]
    validate_release_manifest(
        manifest,
        directory=tmp_path,
        expected_version=version,
        require_sbom=False,
        minimum_bundle_count=0,
        minimum_native_desktop_count=5,
        required_desktop_platforms=("windows", "macos", "linux"),
    )

    incomplete = dict(manifest)
    incomplete["artifacts"] = [
        item for item in manifest["artifacts"] if item["kind"] != "desktop-dmg"
    ]
    with pytest.raises(ReleaseProvenanceError, match="macos"):
        validate_release_manifest(
            incomplete,
            directory=tmp_path,
            expected_version=version,
            require_sbom=False,
            minimum_bundle_count=0,
            required_desktop_platforms=("windows", "macos", "linux"),
        )



def test_release_scripts_are_executable() -> None:
    for name in (
        "release_provenance.py",
        "generate_sbom.py",
        "finalize_release_artifacts.py",
        "build_offline_bundle.py",
        "cross_platform_smoke.py",
        "build_standalone_runtime.py",
        "verify_standalone_runtime.py",
        "build_desktop_frontend.py",
        "verify_desktop_frontend.py",
        "stage_desktop_runtime.py",
        "build_desktop_app.py",
        "verify_desktop_installer.py",
        "build_native_desktop.py",
        "verify_native_desktop.py",
        "generate_update_manifest.py",
        "assemble_signed_updates.py",
        "release_preflight.py",
        "verify_platform_signing.py",
        "extract_release_notes.py",
    ):
        path = SCRIPTS / name
        assert path.is_file()
        assert os.access(path, os.X_OK)


def test_cross_platform_and_provenance_workflows_use_current_contracts() -> None:
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    codeql = (ROOT / ".github/workflows/codeql.yml").read_text(encoding="utf-8")
    dependabot = (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")

    for os_name in ("ubuntu-latest", "windows-latest", "macos-latest"):
        assert os_name in ci
        assert os_name in release
    for action in (
        "actions/checkout@v6",
        "actions/setup-python@v6",
        "actions/upload-artifact@v7",
    ):
        assert action in ci
    assert "scripts/cross_platform_smoke.py" in ci
    assert "actions/download-artifact@v8" in release
    assert "actions/attest@v4" in release
    assert "id-token: write" in release
    assert "attestations: write" in release
    assert "release-attestations-${{ needs.build-core.outputs.version }}" in release
    assert "path: build/attestations/" in release
    assert "artifact-metadata: write" in release
    assert "subject-checksums" in release
    assert "sbom-path" in release
    assert "minimum-bundle-count 3" in release
    assert "minimum-standalone-runtime-count 1" in release
    assert "build_standalone_runtime.py" in ci
    assert "verify_standalone_runtime.py" in ci
    assert "playwright install chromium --only-shell" in ci
    assert "standalone-runtime" in release
    assert "desktop-native-windows" in release
    assert "desktop-native-" in release
    assert "minimum-desktop-installer-count 1" in release
    assert "minimum-native-desktop-count 5" in release
    for platform_name in ("windows", "macos", "linux"):
        assert f"--require-desktop-platform {platform_name}" in release
    assert "build_native_desktop.py" in ci
    assert "verify_native_desktop.py" in ci
    assert "ubuntu-22.04" in ci
    assert "macos-15-intel" in ci
    assert "cargo install tauri-cli --version 2.11.4 --locked" in ci
    assert "release-preflight:" in release
    assert 'scripts/release_preflight.py --mode "$MARDAS_RELEASE_MODE"' in release
    assert "--create-updater-artifacts" in release
    assert "scripts/assemble_signed_updates.py" in release
    assert "--require-update-manifest" in release
    assert "publish-draft:" in release
    assert "gh release create" in release
    assert "--draft" in release
    assert "github/codeql-action/init@v4" in codeql
    assert "github/codeql-action/analyze@v4" in codeql
    assert "package-ecosystem: pip" in dependabot
    assert "package-ecosystem: github-actions" in dependabot


def test_finalize_cli_round_trip(tmp_path: Path) -> None:
    wheel = tmp_path / "mardas_folio-1.21.0-py3-none-any.whl"
    sdist = tmp_path / "mardas_folio-1.21.0.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    spdx = generate_spdx_document(
        distributions=[
            DistributionRecord(
                name="mardas-folio",
                version="1.21.0",
                summary="Publisher",
                license_expression="MIT",
                requirements=(),
                project_urls=(),
            )
        ],
        relationships=[],
        artifact_paths=[wheel, sdist],
        root_name="mardas-folio",
        source_revision="abc",
        epoch=1_735_689_600,
    )
    write_json(tmp_path / "mardas-folio-1.21.0.spdx.json", spdx)
    command = [
        sys.executable,
        str(SCRIPTS / "finalize_release_artifacts.py"),
        "--artifact-dir",
        str(tmp_path),
        "--version",
        "1.21.0",
        "--source-revision",
        "abc",
        "--source-date-epoch",
        "1735689600",
        "--require-sbom",
    ]

    first = subprocess.run(command, check=False, capture_output=True, text=True)
    second = subprocess.run(command + ["--verify-only"], check=False, capture_output=True, text=True)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert (tmp_path / "RELEASE-MANIFEST.json").is_file()
    assert (tmp_path / "CHECKSUMS.sha256").is_file()

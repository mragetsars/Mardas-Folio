#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from release_provenance import (
    ReleaseProvenanceError,
    build_release_manifest,
    collect_artifacts,
    parse_checksums,
    read_json,
    source_date_epoch,
    validate_release_manifest,
    validate_spdx_document,
    verify_checksums,
    verify_desktop_installer_artifact,
    verify_offline_bundle,
    verify_standalone_runtime,
    write_checksums,
    write_json,
)
from verify_native_desktop import verify_native_artifact

MANIFEST_NAME = "RELEASE-MANIFEST.json"
CHECKSUMS_NAME = "CHECKSUMS.sha256"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Finalize and verify deterministic release metadata"
    )
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-revision", default="unknown")
    parser.add_argument("--source-date-epoch")
    parser.add_argument("--require-sbom", action="store_true")
    parser.add_argument("--minimum-bundle-count", type=int, default=0)
    parser.add_argument("--minimum-standalone-runtime-count", type=int, default=0)
    parser.add_argument("--minimum-desktop-installer-count", type=int, default=0)
    parser.add_argument("--minimum-native-desktop-count", type=int, default=0)
    parser.add_argument(
        "--require-desktop-platform",
        action="append",
        default=[],
        choices=("windows", "macos", "linux"),
        help="Require at least one native desktop artifact for this platform (repeatable)",
    )
    parser.add_argument("--verify-only", action="store_true")
    return parser


def verify_release(
    directory: Path,
    *,
    version: str,
    require_sbom: bool,
    minimum_bundle_count: int,
    minimum_runtime_count: int,
    minimum_desktop_count: int,
    minimum_native_desktop_count: int,
    required_desktop_platforms: tuple[str, ...],
) -> None:
    manifest_path = directory / MANIFEST_NAME
    checksum_path = directory / CHECKSUMS_NAME
    payload = read_json(manifest_path)
    validate_release_manifest(
        payload,
        directory=directory,
        expected_version=version,
        require_sbom=require_sbom,
        minimum_bundle_count=minimum_bundle_count,
        minimum_runtime_count=minimum_runtime_count,
        minimum_desktop_count=minimum_desktop_count,
        minimum_native_desktop_count=minimum_native_desktop_count,
        required_desktop_platforms=required_desktop_platforms,
    )
    verify_checksums(directory, checksum_path)
    checksum_names = set(parse_checksums(checksum_path))
    expected_checksum_names = {item["name"] for item in payload["artifacts"]} | {MANIFEST_NAME}
    if checksum_names != expected_checksum_names:
        raise ReleaseProvenanceError(
            "Checksum inventory does not exactly match the release manifest and manifest file"
        )

    wheel_names = [
        item["name"] for item in payload["artifacts"] if item["kind"] == "python-wheel"
    ]
    sdist_names = [
        item["name"]
        for item in payload["artifacts"]
        if item["kind"] == "source-distribution"
    ]
    if len(wheel_names) != 1 or len(sdist_names) != 1:
        raise ReleaseProvenanceError(
            "Release must contain exactly one wheel and one source distribution"
        )
    normalized = version.replace("-", "_")
    if version not in wheel_names[0] and normalized not in wheel_names[0]:
        raise ReleaseProvenanceError("Wheel filename does not contain the release version")
    if version not in sdist_names[0]:
        raise ReleaseProvenanceError(
            "Source distribution filename does not contain the release version"
        )

    sbom_names = [item["name"] for item in payload["artifacts"] if item["kind"] == "spdx-sbom"]
    for name in sbom_names:
        validate_spdx_document(read_json(directory / name), expected_version=version)
    for item in payload["artifacts"]:
        if item["kind"] == "offline-install-bundle":
            verify_offline_bundle(directory / item["name"], expected_version=version)
        elif item["kind"] == "standalone-runtime":
            verify_standalone_runtime(directory / item["name"], expected_version=version)
        elif item["kind"] == "desktop-installer":
            verify_desktop_installer_artifact(
                directory / item["name"], expected_version=version
            )
            verify_native_artifact(directory / item["name"], expected_version=version)
        elif item["kind"] in {"desktop-portable", "desktop-dmg", "desktop-appimage", "desktop-deb"}:
            verify_native_artifact(directory / item["name"], expected_version=version)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    directory = args.artifact_dir.resolve()
    try:
        if not directory.is_dir():
            raise ReleaseProvenanceError(f"Artifact directory does not exist: {directory}")
        if args.minimum_bundle_count < 0:
            raise ReleaseProvenanceError("Minimum bundle count cannot be negative")
        if args.minimum_standalone_runtime_count < 0:
            raise ReleaseProvenanceError("Minimum standalone runtime count cannot be negative")
        if args.minimum_desktop_installer_count < 0:
            raise ReleaseProvenanceError("Minimum desktop installer count cannot be negative")
        if args.minimum_native_desktop_count < 0:
            raise ReleaseProvenanceError("Minimum native desktop count cannot be negative")
        manifest_path = directory / MANIFEST_NAME
        checksum_path = directory / CHECKSUMS_NAME
        if not args.verify_only:
            manifest_path.unlink(missing_ok=True)
            checksum_path.unlink(missing_ok=True)
            initial = collect_artifacts(directory, excluded_names={MANIFEST_NAME, CHECKSUMS_NAME})
            if not initial:
                raise ReleaseProvenanceError("Artifact directory is empty")
            manifest = build_release_manifest(
                records=initial,
                version=args.version,
                source_revision=args.source_revision,
                epoch=source_date_epoch(args.source_date_epoch),
            )
            write_json(manifest_path, manifest)
            complete = collect_artifacts(directory, excluded_names={CHECKSUMS_NAME})
            write_checksums(checksum_path, complete)
        verify_release(
            directory,
            version=args.version,
            require_sbom=args.require_sbom,
            minimum_bundle_count=args.minimum_bundle_count,
            minimum_runtime_count=args.minimum_standalone_runtime_count,
            minimum_desktop_count=args.minimum_desktop_installer_count,
            minimum_native_desktop_count=args.minimum_native_desktop_count,
            required_desktop_platforms=tuple(args.require_desktop_platform),
        )
    except (ReleaseProvenanceError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"Release artifact verification failed: {exc}", file=sys.stderr)
        return 2
    print(f"Release artifacts verified: {directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

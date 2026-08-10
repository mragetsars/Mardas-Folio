#!/usr/bin/env python3
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import stat
# Security: subprocess calls use explicit trusted executables and fixed argument arrays.
import subprocess  # nosec B404
import sys
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from runtime_manifest import (  # noqa: E402
    LEGACY_RUNTIME_MANIFEST_SCHEMA,
    MAX_SYMLINK_TARGET_BYTES,
    RUNTIME_FILE_TYPE,
    RUNTIME_MANIFEST_SCHEMA,
    RUNTIME_SYMLINK_TYPE,
    has_bundled_browser_file,
    safe_runtime_path,
    validate_symlink_graph,
    validate_symlink_target,
)

PROJECT_NAME = "mardas-md2pdf"
REPOSITORY_URL = "https://github.com/mragetsars/Mardas-MD2PDF"
SPDX_VERSION = "SPDX-2.3"
RELEASE_MANIFEST_SCHEMA = 1
BUNDLE_MANIFEST_SCHEMA = 1
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024 * 1024
MAX_BUNDLE_MEMBER_BYTES = 1024 * 1024 * 1024
MAX_STANDALONE_FILES = 20_000
MAX_STANDALONE_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024
MAX_RUNTIME_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_SBOM_BYTES = 16 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_LABEL_RE = re.compile(r"[^A-Za-z0-9._-]+")


class ReleaseProvenanceError(RuntimeError):
    """Raised when release provenance input or output is invalid."""


@dataclass(frozen=True)
class ArtifactRecord:
    name: str
    kind: str
    size: int
    sha256: str


@dataclass(frozen=True)
class DistributionRecord:
    name: str
    version: str
    summary: str
    license_expression: str
    requirements: tuple[str, ...]
    project_urls: tuple[str, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_date_epoch(value: str | int | None = None) -> int:
    raw = str(value if value is not None else os.environ.get("SOURCE_DATE_EPOCH", "946684800"))
    try:
        epoch = int(raw)
    except ValueError as exc:
        raise ReleaseProvenanceError(f"SOURCE_DATE_EPOCH must be an integer: {raw!r}") from exc
    if epoch < 315532800:  # ZIP timestamps cannot precede 1980-01-01.
        epoch = 315532800
    return epoch


def timestamp_from_epoch(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, payload: Mapping[str, Any] | Sequence[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def read_json(path: Path, *, max_bytes: int = MAX_SBOM_BYTES) -> Any:
    if not path.is_file():
        raise ReleaseProvenanceError(f"Required JSON file is missing: {path}")
    size = path.stat().st_size
    if size > max_bytes:
        raise ReleaseProvenanceError(f"JSON file exceeds {max_bytes} bytes: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReleaseProvenanceError(f"Invalid JSON file: {path}: {exc}") from exc


def normalized_label(value: str) -> str:
    cleaned = _SAFE_LABEL_RE.sub("-", value.strip()).strip("-._")
    if not cleaned:
        raise ReleaseProvenanceError(f"Unsafe or empty release label: {value!r}")
    return cleaned.lower()


def spdx_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9.-]+", "-", value).strip("-.")
    return f"SPDXRef-{cleaned or 'Package'}"


def _normalize_license(value: str | None) -> str:
    if not value:
        return "NOASSERTION"
    normalized = value.strip()
    aliases = {
        "MIT License": "MIT",
        "MIT": "MIT",
        "Apache Software License": "Apache-2.0",
        "Apache-2.0": "Apache-2.0",
        "BSD License": "BSD-3-Clause",
        "BSD-3-Clause": "BSD-3-Clause",
        "Python Software Foundation License": "PSF-2.0",
        "PSF-2.0": "PSF-2.0",
    }
    return aliases.get(normalized, "NOASSERTION")


def query_installed_distributions(python_executable: Path) -> list[DistributionRecord]:
    script = r'''
import json
from importlib import metadata

rows = []
for dist in metadata.distributions():
    meta = dist.metadata
    name = meta.get("Name") or getattr(dist, "name", "")
    if not name:
        continue
    rows.append({
        "name": name,
        "version": dist.version,
        "summary": meta.get("Summary") or "",
        "license_expression": meta.get("License-Expression") or meta.get("License") or "",
        "requirements": list(dist.requires or []),
        "project_urls": list(meta.get_all("Project-URL") or []),
    })
print(json.dumps(rows, ensure_ascii=False, sort_keys=True))
'''
    # Query only the explicitly selected Python interpreter with a fixed inline script.
    completed = subprocess.run(  # nosec B603
        [str(python_executable), "-c", script],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise ReleaseProvenanceError(
            "Could not inspect the installed release environment:\n" + completed.stderr.strip()
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ReleaseProvenanceError("Release environment returned invalid metadata JSON") from exc
    records: list[DistributionRecord] = []
    for item in payload:
        records.append(
            DistributionRecord(
                name=str(item.get("name", "")),
                version=str(item.get("version", "")),
                summary=str(item.get("summary", "")),
                license_expression=_normalize_license(str(item.get("license_expression", ""))),
                requirements=tuple(str(value) for value in item.get("requirements", [])),
                project_urls=tuple(str(value) for value in item.get("project_urls", [])),
            )
        )
    return records


def runtime_dependency_closure(
    records: Sequence[DistributionRecord], root_name: str = PROJECT_NAME
) -> tuple[list[DistributionRecord], list[tuple[str, str]]]:
    by_name = {canonicalize_name(item.name): item for item in records}
    root_key = canonicalize_name(root_name)
    if root_key not in by_name:
        available = ", ".join(sorted(item.name for item in records)[:20])
        raise ReleaseProvenanceError(
            f"Distribution {root_name!r} is not installed in the inspected environment. "
            f"Available examples: {available}"
        )

    environment = default_environment()
    environment["extra"] = ""
    queue = [root_key]
    visited: set[str] = set()
    relationships: set[tuple[str, str]] = set()
    while queue:
        parent_key = queue.pop(0)
        if parent_key in visited:
            continue
        visited.add(parent_key)
        parent = by_name[parent_key]
        for raw_requirement in parent.requirements:
            try:
                requirement = Requirement(raw_requirement)
            except Exception as exc:  # packaging exposes several parser exception types.
                raise ReleaseProvenanceError(
                    f"Could not parse requirement {raw_requirement!r} from {parent.name}"
                ) from exc
            if requirement.marker is not None and not requirement.marker.evaluate(environment):
                continue
            child_key = canonicalize_name(requirement.name)
            if child_key not in by_name:
                raise ReleaseProvenanceError(
                    f"Runtime dependency {requirement.name!r} required by {parent.name!r} "
                    "is missing from the inspected environment"
                )
            relationships.add((parent_key, child_key))
            if child_key not in visited:
                queue.append(child_key)

    selected = sorted((by_name[key] for key in visited), key=lambda item: canonicalize_name(item.name))
    return selected, sorted(relationships)


def _package_homepage(record: DistributionRecord) -> str:
    for project_url in record.project_urls:
        label, separator, value = project_url.partition(",")
        if separator and label.strip().lower() in {"homepage", "source", "repository"}:
            return value.strip()
    return "NOASSERTION"


def generate_spdx_document(
    *,
    distributions: Sequence[DistributionRecord],
    relationships: Sequence[tuple[str, str]],
    artifact_paths: Sequence[Path],
    root_name: str,
    source_revision: str,
    epoch: int,
) -> dict[str, Any]:
    root_key = canonicalize_name(root_name)
    records_by_key = {canonicalize_name(item.name): item for item in distributions}
    if root_key not in records_by_key:
        raise ReleaseProvenanceError(f"Root package is missing from the SPDX input: {root_name}")

    artifacts = []
    for path in sorted(artifact_paths, key=lambda item: item.name):
        resolved = path.resolve()
        if not resolved.is_file() or resolved.is_symlink():
            raise ReleaseProvenanceError(f"SPDX artifact must be a regular file: {path}")
        if resolved.stat().st_size > MAX_ARTIFACT_BYTES:
            raise ReleaseProvenanceError(f"SPDX artifact is unexpectedly large: {path}")
        artifacts.append({"name": resolved.name, "sha256": sha256_file(resolved)})

    identity = {
        "packages": [asdict(item) for item in distributions],
        "relationships": list(relationships),
        "artifacts": artifacts,
        "source_revision": source_revision,
    }
    identity_digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    root = records_by_key[root_key]
    packages: list[dict[str, Any]] = []
    for record in distributions:
        key = canonicalize_name(record.name)
        package: dict[str, Any] = {
            "name": record.name,
            "SPDXID": spdx_id(f"Package-{key}"),
            "versionInfo": record.version,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": record.license_expression,
            "copyrightText": "NOASSERTION",
            "summary": record.summary or "NOASSERTION",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": f"pkg:pypi/{key}@{record.version}",
                }
            ],
        }
        homepage = _package_homepage(record)
        if homepage != "NOASSERTION":
            package["homepage"] = homepage
        if key == root_key and artifacts:
            package["checksums"] = [
                {"algorithm": "SHA256", "checksumValue": item["sha256"]}
                for item in artifacts
            ]
            package["comment"] = "Release artifact checksums: " + ", ".join(
                f"{item['name']}={item['sha256']}" for item in artifacts
            )
        packages.append(package)

    spdx_relationships: list[dict[str, str]] = [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": spdx_id(f"Package-{root_key}"),
        }
    ]
    for parent, child in relationships:
        spdx_relationships.append(
            {
                "spdxElementId": spdx_id(f"Package-{parent}"),
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": spdx_id(f"Package-{child}"),
            }
        )

    return {
        "spdxVersion": SPDX_VERSION,
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"{root.name}-{root.version}-runtime-sbom",
        "documentNamespace": f"{REPOSITORY_URL}/sbom/{root.version}/{identity_digest}",
        "creationInfo": {
            "created": timestamp_from_epoch(epoch),
            "creators": ["Tool: Mardas-MD2PDF generate_sbom.py"],
            "comment": f"Source revision: {source_revision or 'unknown'}",
        },
        "documentDescribes": [spdx_id(f"Package-{root_key}")],
        "packages": packages,
        "relationships": spdx_relationships,
    }


def validate_spdx_document(payload: Mapping[str, Any], *, expected_version: str) -> None:
    if payload.get("spdxVersion") != SPDX_VERSION:
        raise ReleaseProvenanceError("SBOM is not SPDX 2.3 JSON")
    if payload.get("dataLicense") != "CC0-1.0" or payload.get("SPDXID") != "SPDXRef-DOCUMENT":
        raise ReleaseProvenanceError("SBOM document metadata is incomplete")
    packages = payload.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ReleaseProvenanceError("SBOM has no package inventory")
    identifiers: set[str] = set()
    root_matches = 0
    for package in packages:
        if not isinstance(package, dict):
            raise ReleaseProvenanceError("SBOM package record is not an object")
        identifier = str(package.get("SPDXID", ""))
        if not identifier.startswith("SPDXRef-") or identifier in identifiers:
            raise ReleaseProvenanceError("SBOM package identifiers are missing or duplicated")
        identifiers.add(identifier)
        if canonicalize_name(str(package.get("name", ""))) == canonicalize_name(PROJECT_NAME):
            root_matches += 1
            if str(package.get("versionInfo", "")) != expected_version:
                raise ReleaseProvenanceError("SBOM project version does not match the release")
    if root_matches != 1:
        raise ReleaseProvenanceError("SBOM must describe exactly one Mardas Folio package")

    relationships = payload.get("relationships")
    if not isinstance(relationships, list) or not any(
        isinstance(item, dict)
        and item.get("spdxElementId") == "SPDXRef-DOCUMENT"
        and item.get("relationshipType") == "DESCRIBES"
        for item in relationships
    ):
        raise ReleaseProvenanceError("SBOM is missing the document DESCRIBES relationship")


DESKTOP_ARTIFACT_KINDS = frozenset({
    "desktop-installer",
    "desktop-portable",
    "desktop-dmg",
    "desktop-appimage",
    "desktop-deb",
})

DESKTOP_UPDATE_ARTIFACT_KINDS = frozenset({
    "desktop-macos-updater",
    "desktop-update-signature",
})


def artifact_kind(name: str) -> str:
    if name.startswith("Mardas-Folio-") and name.endswith("-updater.tar.gz"):
        return "desktop-macos-updater"
    if name.startswith("Mardas-Folio-") and name.endswith(".sig"):
        return "desktop-update-signature"
    if name == "latest.json":
        return "update-manifest"
    if name.endswith(".whl"):
        return "python-wheel"
    if name.endswith(".tar.gz"):
        return "source-distribution"
    if name.endswith(".spdx.json"):
        return "spdx-sbom"
    if name.endswith(".pdf"):
        return "guide-pdf"
    if "offline-" in name and name.endswith(".zip"):
        return "offline-install-bundle"
    if name.startswith("Mardas-MD2PDF-") and "-runtime-" in name and name.endswith(".zip"):
        return "standalone-runtime"
    if name.startswith("Mardas-Folio-") and name.endswith("-setup.exe"):
        return "desktop-installer"
    if name.startswith("Mardas-Folio-") and name.endswith("-portable.zip"):
        return "desktop-portable"
    if name.startswith("Mardas-Folio-") and name.endswith(".dmg"):
        return "desktop-dmg"
    if name.startswith("Mardas-Folio-") and name.endswith(".AppImage"):
        return "desktop-appimage"
    if name.startswith("Mardas-Folio-") and name.endswith(".deb"):
        return "desktop-deb"
    if name.endswith(".sigstore.json"):
        return "sigstore-attestation"
    if name.endswith(".json"):
        return "json-metadata"
    return "release-file"


def desktop_artifact_platform(name: str, kind: str) -> str | None:
    if kind not in DESKTOP_ARTIFACT_KINDS | DESKTOP_UPDATE_ARTIFACT_KINDS:
        return None
    if "-windows-" in name:
        return "windows"
    if "-macos-" in name:
        return "macos"
    if "-linux-" in name:
        return "linux"
    return None


def collect_artifacts(directory: Path, *, excluded_names: Iterable[str] = ()) -> list[ArtifactRecord]:
    root = directory.resolve()
    excluded = set(excluded_names)
    records: list[ArtifactRecord] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        if path.name in excluded or path.name.startswith("."):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        size = path.stat().st_size
        if size > MAX_ARTIFACT_BYTES:
            raise ReleaseProvenanceError(f"Release artifact exceeds the size limit: {path.name}")
        records.append(
            ArtifactRecord(
                name=path.name,
                kind=artifact_kind(path.name),
                size=size,
                sha256=sha256_file(path),
            )
        )
    return records


def write_checksums(path: Path, records: Sequence[ArtifactRecord]) -> None:
    names = [item.name for item in records]
    if len(names) != len(set(names)):
        raise ReleaseProvenanceError("Duplicate artifact names cannot be checksummed")
    lines = [f"{item.sha256}  {item.name}" for item in sorted(records, key=lambda item: item.name)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def parse_checksums(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ReleaseProvenanceError(f"Checksum file is missing: {path}")
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64}) [ *](.+)", raw_line)
        if not match:
            raise ReleaseProvenanceError(f"Invalid checksum line {line_number}: {raw_line!r}")
        digest, name = match.groups()
        pure = PurePosixPath(name.replace("\\", "/"))
        if pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 1:
            raise ReleaseProvenanceError(f"Unsafe checksum path: {name!r}")
        if name in values:
            raise ReleaseProvenanceError(f"Duplicate checksum entry: {name}")
        values[name] = digest
    return values


def verify_checksums(directory: Path, checksum_path: Path) -> None:
    values = parse_checksums(checksum_path)
    if not values:
        raise ReleaseProvenanceError("Checksum file is empty")
    for name, expected in values.items():
        candidate = directory / name
        if candidate.is_symlink() or not candidate.is_file():
            raise ReleaseProvenanceError(f"Checksummed artifact is missing or unsafe: {name}")
        actual = sha256_file(candidate)
        if actual != expected:
            raise ReleaseProvenanceError(f"Checksum mismatch for {name}: {actual} != {expected}")


def build_release_manifest(
    *,
    records: Sequence[ArtifactRecord],
    version: str,
    source_revision: str,
    epoch: int,
) -> dict[str, Any]:
    bundle_count = sum(item.kind == "offline-install-bundle" for item in records)
    runtime_count = sum(item.kind == "standalone-runtime" for item in records)
    desktop_installer_count = sum(item.kind == "desktop-installer" for item in records)
    native_desktop_count = sum(item.kind in DESKTOP_ARTIFACT_KINDS for item in records)
    update_artifact_count = sum(item.kind in DESKTOP_UPDATE_ARTIFACT_KINDS for item in records)
    update_manifest_count = sum(item.kind == "update-manifest" for item in records)
    desktop_platforms = sorted({
        platform_name
        for item in records
        if (platform_name := desktop_artifact_platform(item.name, item.kind)) is not None
    })
    sbom_files = [item.name for item in records if item.kind == "spdx-sbom"]
    return {
        "schema_version": RELEASE_MANIFEST_SCHEMA,
        "project": PROJECT_NAME,
        "version": version,
        "source_revision": source_revision or "unknown",
        "source_date_epoch": epoch,
        "generated_at": timestamp_from_epoch(epoch),
        "repository": REPOSITORY_URL,
        "artifacts": [asdict(item) for item in sorted(records, key=lambda item: item.name)],
        "summary": {
            "artifact_count": len(records),
            "offline_bundle_count": bundle_count,
            "standalone_runtime_count": runtime_count,
            "desktop_installer_count": desktop_installer_count,
            "native_desktop_artifact_count": native_desktop_count,
            "desktop_update_artifact_count": update_artifact_count,
            "update_manifest_count": update_manifest_count,
            "desktop_platforms": desktop_platforms,
            "sbom_files": sbom_files,
        },
        "verification": {
            "checksums": "CHECKSUMS.sha256",
            "attestation_command": (
                "gh attestation verify <artifact> --repo mragetsars/Mardas-MD2PDF"
            ),
            "browser_in_offline_bundles": False,
            "browser_in_standalone_runtime": True,
        },
    }


def validate_release_manifest(
    payload: Mapping[str, Any],
    *,
    directory: Path,
    expected_version: str,
    require_sbom: bool,
    minimum_bundle_count: int,
    minimum_runtime_count: int = 0,
    minimum_desktop_count: int = 0,
    minimum_native_desktop_count: int = 0,
    required_desktop_platforms: Sequence[str] = (),
) -> None:
    if payload.get("schema_version") != RELEASE_MANIFEST_SCHEMA:
        raise ReleaseProvenanceError("Unsupported release manifest schema")
    if payload.get("project") != PROJECT_NAME or payload.get("version") != expected_version:
        raise ReleaseProvenanceError("Release manifest project or version is incorrect")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ReleaseProvenanceError("Release manifest does not contain artifacts")
    names: set[str] = set()
    sbom_count = 0
    bundle_count = 0
    runtime_count = 0
    desktop_count = 0
    native_desktop_count = 0
    desktop_platforms: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict):
            raise ReleaseProvenanceError("Release manifest artifact is not an object")
        name = str(item.get("name", ""))
        pure = PurePosixPath(name.replace("\\", "/"))
        if not name or pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 1:
            raise ReleaseProvenanceError(f"Unsafe release manifest artifact path: {name!r}")
        if name in names:
            raise ReleaseProvenanceError(f"Duplicate release manifest artifact: {name}")
        names.add(name)
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ReleaseProvenanceError(f"Release manifest artifact is missing: {name}")
        if int(item.get("size", -1)) != path.stat().st_size:
            raise ReleaseProvenanceError(f"Release manifest size mismatch: {name}")
        digest = str(item.get("sha256", ""))
        if not _SHA256_RE.fullmatch(digest) or digest != sha256_file(path):
            raise ReleaseProvenanceError(f"Release manifest checksum mismatch: {name}")
        kind = str(item.get("kind", ""))
        sbom_count += kind == "spdx-sbom"
        bundle_count += kind == "offline-install-bundle"
        runtime_count += kind == "standalone-runtime"
        desktop_count += kind == "desktop-installer"
        native_desktop_count += kind in DESKTOP_ARTIFACT_KINDS
        platform_name = desktop_artifact_platform(name, kind)
        if platform_name is not None:
            desktop_platforms.add(platform_name)
    actual_names = {
        item.name
        for item in directory.iterdir()
        if item.is_file()
        and not item.is_symlink()
        and item.name not in {"RELEASE-MANIFEST.json", "CHECKSUMS.sha256"}
        and not item.name.startswith(".")
    }
    if names != actual_names:
        missing = sorted(names - actual_names)
        extra = sorted(actual_names - names)
        raise ReleaseProvenanceError(
            f"Release manifest directory mismatch; missing={missing}, extra={extra}"
        )
    if require_sbom and sbom_count != 1:
        raise ReleaseProvenanceError("Release must contain exactly one SPDX SBOM")
    if bundle_count < minimum_bundle_count:
        raise ReleaseProvenanceError(
            f"Release contains {bundle_count} offline bundle(s); expected at least {minimum_bundle_count}"
        )
    if runtime_count < minimum_runtime_count:
        raise ReleaseProvenanceError(
            f"Release contains {runtime_count} standalone runtime(s); expected at least {minimum_runtime_count}"
        )
    if desktop_count < minimum_desktop_count:
        raise ReleaseProvenanceError(
            f"Release contains {desktop_count} desktop installer(s); expected at least {minimum_desktop_count}"
        )
    if native_desktop_count < minimum_native_desktop_count:
        raise ReleaseProvenanceError(
            f"Release contains {native_desktop_count} native desktop artifact(s); "
            f"expected at least {minimum_native_desktop_count}"
        )
    required = {str(value).strip().lower() for value in required_desktop_platforms if str(value).strip()}
    invalid_required = required - {"windows", "macos", "linux"}
    if invalid_required:
        raise ReleaseProvenanceError(
            "Unsupported required desktop platform(s): " + ", ".join(sorted(invalid_required))
        )
    missing_platforms = sorted(required - desktop_platforms)
    if missing_platforms:
        raise ReleaseProvenanceError(
            "Release is missing required native desktop platform(s): "
            + ", ".join(missing_platforms)
        )


def verify_desktop_installer_artifact(path: Path, *, expected_version: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ReleaseProvenanceError(f"Desktop installer is missing or unsafe: {path}")
    expected_prefix = f"Mardas-Folio-{expected_version}-windows-"
    if not path.name.startswith(expected_prefix) or not path.name.endswith("-setup.exe"):
        raise ReleaseProvenanceError("Desktop installer filename does not match the release version")
    size = path.stat().st_size
    if size < 1024 * 1024 or size > 2 * 1024 * 1024 * 1024:
        raise ReleaseProvenanceError("Desktop installer size is outside the allowed range")
    with path.open("rb") as handle:
        if handle.read(2) != b"MZ":
            raise ReleaseProvenanceError("Desktop installer does not contain a Windows PE header")


def safe_zip_member(name: str) -> PurePosixPath:
    pure = PurePosixPath(name.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ReleaseProvenanceError(f"Unsafe ZIP member path: {name!r}")
    return pure


def deterministic_zip(
    output_path: Path,
    members: Sequence[tuple[str, bytes, int]],
    *,
    epoch: int,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    date_time = datetime.fromtimestamp(epoch, tz=timezone.utc).timetuple()[:6]
    seen: set[str] = set()
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for raw_name, data, mode in sorted(members, key=lambda item: item[0]):
            name = safe_zip_member(raw_name).as_posix()
            if name in seen:
                raise ReleaseProvenanceError(f"Duplicate ZIP member: {name}")
            seen.add(name)
            if len(data) > MAX_BUNDLE_MEMBER_BYTES:
                raise ReleaseProvenanceError(f"ZIP member exceeds the size limit: {name}")
            info = zipfile.ZipInfo(filename=name, date_time=date_time)
            info.create_system = 3
            info.external_attr = (mode & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)


def verify_offline_bundle(path: Path, *, expected_version: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ReleaseProvenanceError(f"Offline bundle is missing or unsafe: {path}")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names: set[str] = set()
        for info in infos:
            name = safe_zip_member(info.filename).as_posix()
            if name in names:
                raise ReleaseProvenanceError(f"Duplicate offline bundle member: {name}")
            names.add(name)
            if info.file_size > MAX_BUNDLE_MEMBER_BYTES:
                raise ReleaseProvenanceError(f"Offline bundle member is too large: {name}")
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise ReleaseProvenanceError(f"Offline bundle contains a symlink: {name}")
        required = {"README.md", "install.py", "install.sh", "install.ps1", "BUNDLE-MANIFEST.json", "CHECKSUMS.sha256"}
        missing = sorted(required - names)
        if missing:
            raise ReleaseProvenanceError(
                "Offline bundle is missing required files: " + ", ".join(missing)
            )
        manifest = json.loads(archive.read("BUNDLE-MANIFEST.json").decode("utf-8"))
        if manifest.get("schema_version") != BUNDLE_MANIFEST_SCHEMA:
            raise ReleaseProvenanceError("Unsupported offline bundle manifest schema")
        if manifest.get("project") != PROJECT_NAME or manifest.get("version") != expected_version:
            raise ReleaseProvenanceError("Offline bundle project or version is incorrect")
        if manifest.get("browser_included") is not False:
            raise ReleaseProvenanceError("Offline bundle must not claim to include Chromium")
        checksum_lines = archive.read("CHECKSUMS.sha256").decode("utf-8").splitlines()
        observed: dict[str, str] = {}
        for raw_line in checksum_lines:
            if not raw_line:
                continue
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", raw_line)
            if not match:
                raise ReleaseProvenanceError("Offline bundle checksum file is invalid")
            digest, name = match.groups()
            safe_zip_member(name)
            if name == "CHECKSUMS.sha256" or name in observed:
                raise ReleaseProvenanceError("Offline bundle checksum list is recursive or duplicated")
            observed[name] = digest
        for name, expected in observed.items():
            if name not in names:
                raise ReleaseProvenanceError(f"Offline bundle checksummed member is missing: {name}")
            actual = hashlib.sha256(archive.read(name)).hexdigest()
            if actual != expected:
                raise ReleaseProvenanceError(f"Offline bundle checksum mismatch: {name}")
        wheel_names = [name for name in names if name.startswith("wheelhouse/") and name.endswith(".whl")]
        if not any(canonicalize_name(PROJECT_NAME).replace("-", "_") in name.lower() for name in wheel_names):
            raise ReleaseProvenanceError("Offline bundle does not include the project wheel")


def verify_standalone_runtime(path: Path, *, expected_version: str) -> None:
    """Verify a portable frozen sidecar archive and its internal file manifest."""

    if path.is_symlink() or not path.is_file():
        raise ReleaseProvenanceError(f"Standalone runtime is missing or unsafe: {path}")
    if expected_version not in path.name:
        raise ReleaseProvenanceError(
            "Standalone runtime filename does not contain the release version"
        )
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        content_infos = [item for item in infos if not item.is_dir()]
        # The root manifest is metadata beside, not part of, its bounded file inventory.
        if len(content_infos) > MAX_STANDALONE_FILES + 1:
            raise ReleaseProvenanceError("Standalone runtime contains too many files")
        total_uncompressed = sum(item.file_size for item in content_infos)
        if total_uncompressed > MAX_STANDALONE_UNCOMPRESSED_BYTES:
            raise ReleaseProvenanceError("Standalone runtime expands beyond the size limit")
        names: set[str] = set()
        content_names: set[str] = set()
        directory_names: set[str] = set()
        members: dict[str, zipfile.ZipInfo] = {}
        roots: set[str] = set()
        for info in infos:
            name = safe_zip_member(info.filename).as_posix()
            if name in names:
                raise ReleaseProvenanceError(f"Duplicate standalone runtime member: {name}")
            names.add(name)
            members[name] = info
            roots.add(PurePosixPath(name).parts[0])
            if info.file_size > MAX_BUNDLE_MEMBER_BYTES:
                raise ReleaseProvenanceError(f"Standalone runtime member is too large: {name}")
            entry_kind = (info.external_attr >> 16) & 0o170000
            if info.is_dir():
                if entry_kind not in {0, stat.S_IFDIR}:
                    raise ReleaseProvenanceError(
                        f"Standalone runtime directory has an invalid ZIP mode: {name}"
                    )
                directory_names.add(name)
            else:
                if entry_kind not in {0, stat.S_IFREG, stat.S_IFLNK}:
                    raise ReleaseProvenanceError(
                        f"Standalone runtime contains an unsupported ZIP entry: {name}"
                    )
                content_names.add(name)
        if len(roots) != 1:
            raise ReleaseProvenanceError(
                "Standalone runtime must contain exactly one top-level directory"
            )
        root = next(iter(roots))
        manifest_name = f"{root}/runtime-manifest.json"
        if manifest_name not in content_names:
            raise ReleaseProvenanceError("Standalone runtime manifest is missing")
        manifest_info = members[manifest_name]
        if (manifest_info.external_attr >> 16) & 0o170000 == stat.S_IFLNK:
            raise ReleaseProvenanceError("Standalone runtime manifest must be a regular file")
        if manifest_info.file_size > MAX_RUNTIME_MANIFEST_BYTES:
            raise ReleaseProvenanceError("Standalone runtime manifest is unreasonably large")
        manifest = json.loads(archive.read(manifest_name).decode("utf-8"))
        schema_version = manifest.get("schema_version")
        if schema_version not in {
            LEGACY_RUNTIME_MANIFEST_SCHEMA,
            RUNTIME_MANIFEST_SCHEMA,
        }:
            raise ReleaseProvenanceError("Unsupported standalone runtime manifest schema")
        if manifest.get("version") != expected_version:
            raise ReleaseProvenanceError("Standalone runtime version is incorrect")
        if (
            manifest.get("protocol") != "mardas-sidecar"
            or manifest.get("protocol_version") != 1
        ):
            raise ReleaseProvenanceError("Standalone runtime protocol metadata is incorrect")
        if manifest.get("browser_bundled") is not True:
            raise ReleaseProvenanceError(
                "Standalone runtime must include its pinned Chromium runtime"
            )
        file_entries = manifest.get("files")
        if (
            not isinstance(file_entries, list)
            or not file_entries
            or len(file_entries) > MAX_STANDALONE_FILES
        ):
            raise ReleaseProvenanceError("Standalone runtime file inventory is invalid")
        expected_names = {manifest_name}
        executable_found = False
        inventory_paths: set[str] = set()
        regular_inventory_paths: set[str] = set()
        symlinks: dict[str, str] = {}
        for entry in file_entries:
            if not isinstance(entry, dict):
                raise ReleaseProvenanceError("Standalone runtime file entry is not an object")
            try:
                pure = safe_runtime_path(entry.get("path"))
            except ValueError as exc:
                raise ReleaseProvenanceError(
                    "Standalone runtime inventory path is invalid"
                ) from exc
            relative = pure.as_posix()
            member_name = f"{root}/{pure.as_posix()}"
            if member_name in expected_names:
                raise ReleaseProvenanceError(
                    f"Duplicate standalone runtime inventory path: {relative}"
                )
            expected_names.add(member_name)
            if member_name not in names:
                raise ReleaseProvenanceError(
                    f"Standalone runtime inventory member is missing: {relative}"
                )
            inventory_paths.add(relative)
            info = members[member_name]
            zip_entry_kind = (info.external_attr >> 16) & 0o170000
            entry_type = entry.get("type")
            if schema_version == LEGACY_RUNTIME_MANIFEST_SCHEMA:
                if entry_type not in {None, RUNTIME_FILE_TYPE}:
                    raise ReleaseProvenanceError(
                        "Legacy standalone runtime manifests may contain only regular files"
                    )
                entry_type = RUNTIME_FILE_TYPE
            if entry_type == RUNTIME_FILE_TYPE:
                if (
                    zip_entry_kind == stat.S_IFLNK
                    or info.is_dir()
                    or (
                        schema_version == RUNTIME_MANIFEST_SCHEMA
                        and zip_entry_kind != stat.S_IFREG
                    )
                ):
                    raise ReleaseProvenanceError(
                        f"Standalone runtime file has an unsafe ZIP type: {relative}"
                    )
                expected_size = entry.get("size")
                if (
                    not isinstance(expected_size, int)
                    or isinstance(expected_size, bool)
                    or info.file_size != expected_size
                ):
                    raise ReleaseProvenanceError(f"Standalone runtime size mismatch: {relative}")
                digest = str(entry.get("sha256", ""))
                checksum = hashlib.sha256()
                with archive.open(info) as member:
                    for chunk in iter(lambda: member.read(1024 * 1024), b""):
                        checksum.update(chunk)
                if not _SHA256_RE.fullmatch(digest) or checksum.hexdigest() != digest:
                    raise ReleaseProvenanceError(
                        f"Standalone runtime checksum mismatch: {relative}"
                    )
                if relative in {"mardas-sidecar", "mardas-sidecar.exe"}:
                    executable_found = True
                regular_inventory_paths.add(relative)
            elif (
                entry_type == RUNTIME_SYMLINK_TYPE
                and schema_version == RUNTIME_MANIFEST_SCHEMA
            ):
                if (
                    zip_entry_kind != stat.S_IFLNK
                    or info.is_dir()
                    or info.create_system != 3
                ):
                    raise ReleaseProvenanceError(
                        f"Standalone runtime symlink has an unsafe ZIP type: {relative}"
                    )
                if info.file_size > MAX_SYMLINK_TARGET_BYTES:
                    raise ReleaseProvenanceError(
                        f"Standalone runtime symlink target is too large: {relative}"
                    )
                data = archive.read(member_name)
                try:
                    target = data.decode("utf-8", errors="strict")
                    validate_symlink_target(target)
                except (UnicodeDecodeError, ValueError) as exc:
                    raise ReleaseProvenanceError(
                        f"Standalone runtime symlink target is invalid: {relative}"
                    ) from exc
                if target != entry.get("target"):
                    raise ReleaseProvenanceError(
                        f"Standalone runtime symlink target mismatch: {relative}"
                    )
                symlinks[relative] = target
            else:
                raise ReleaseProvenanceError(
                    f"Standalone runtime manifest entry type is invalid: {relative}"
                )
        if not has_bundled_browser_file(regular_inventory_paths):
            raise ReleaseProvenanceError(
                "Standalone runtime claims bundled Chromium without an inventoried browser file"
            )
        if expected_names != content_names:
            extra = sorted(content_names - expected_names)
            missing = sorted(expected_names - content_names)
            raise ReleaseProvenanceError(
                f"Standalone runtime archive inventory mismatch; missing={missing}, extra={extra}"
            )
        runtime_directories = []
        for name in directory_names:
            pure = PurePosixPath(name)
            if len(pure.parts) > 1:
                runtime_directories.append(PurePosixPath(*pure.parts[1:]).as_posix())
        try:
            validate_symlink_graph(
                inventory_paths,
                symlinks,
                directories=runtime_directories,
            )
        except ValueError as exc:
            raise ReleaseProvenanceError(str(exc)) from exc
        if not executable_found:
            raise ReleaseProvenanceError("Standalone runtime sidecar executable is missing")


def encode_inline_file(path: Path) -> str:
    """Return a compact base64 string used only in tests/debug manifests."""
    return base64.b64encode(path.read_bytes()).decode("ascii")

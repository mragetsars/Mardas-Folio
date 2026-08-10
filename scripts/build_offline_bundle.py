#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
# Security: subprocess calls use explicit trusted executables and fixed argument arrays.
import subprocess  # nosec B404
import sys
import tempfile
import zipfile
from pathlib import Path

from release_provenance import (
    BUNDLE_MANIFEST_SCHEMA,
    PROJECT_NAME,
    ReleaseProvenanceError,
    deterministic_zip,
    normalized_label,
    source_date_epoch,
    timestamp_from_epoch,
    verify_offline_bundle,
)

INSTALL_PY = r'''#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import venv
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_bundle(root: Path) -> None:
    checksums = root / "CHECKSUMS.sha256"
    for raw_line in checksums.read_text(encoding="utf-8").splitlines():
        if not raw_line:
            continue
        digest, name = raw_line.split("  ", 1)
        candidate = (root / name).resolve()
        if root.resolve() not in candidate.parents:
            raise SystemExit(f"Unsafe checksum path: {name}")
        if not candidate.is_file() or sha256_file(candidate) != digest:
            raise SystemExit(f"Bundle verification failed: {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Mardas Folio from an offline wheel bundle")
    parser.add_argument("--target", type=Path, default=Path("mardas-md2pdf-venv"))
    parser.add_argument("--clear", action="store_true")
    args = parser.parse_args()
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10 or newer is required")
    root = Path(__file__).resolve().parent
    verify_bundle(root)
    target = args.target.resolve()
    builder = venv.EnvBuilder(with_pip=True, clear=args.clear)
    builder.create(target)
    if os.name == "nt":
        python_exe = target / "Scripts" / "python.exe"
        cli = target / "Scripts" / "mrs-md2pdf.exe"
    else:
        python_exe = target / "bin" / "python"
        cli = target / "bin" / "mrs-md2pdf"
    wheels = sorted((root / "wheelhouse").glob("mardas_md2pdf-*.whl"))
    if len(wheels) != 1:
        raise SystemExit("The bundle must contain exactly one Mardas Folio wheel")
    subprocess.run(
        [
            str(python_exe),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-index",
            "--find-links",
            str(root / "wheelhouse"),
            str(wheels[0]),
        ],
        check=True,
    )
    subprocess.run([str(cli), "--version"], check=True)
    print(f"Installed into: {target}")
    print("Chromium is not bundled. Use an existing Chromium executable or run:")
    print(f"  {python_exe} -m playwright install chromium")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

README_TEMPLATE = """# Mardas Folio offline Python bundle

Version: {version}
Platform label: {platform_label}
Python used to resolve wheels: {python_version}

This archive installs the Python package and its runtime dependencies without
contacting a package index. It is not a standalone executable and it does not
contain a Chromium browser binary.

## Install

Linux/macOS:

```bash
python3 install.py --target mardas-md2pdf-venv
```

Windows PowerShell:

```powershell
py install.py --target mardas-md2pdf-venv
```

The installer verifies CHECKSUMS.sha256, creates a virtual environment, and
installs exclusively from wheelhouse/ with --no-index.

## Browser requirement

PDF rendering requires a supported Chromium executable. Use a system Chromium
or install the Playwright-managed browser after the Python package is installed:

```bash
mardas-md2pdf-venv/bin/python -m playwright install chromium
```

On Windows, use `mardas-md2pdf-venv\\Scripts\\python.exe`.
The browser-install command may require network access and is intentionally not
presented as part of the offline guarantee.
"""

INSTALL_SH = """#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${PYTHON:-python3}" "$script_dir/install.py" "$@"
"""

INSTALL_PS1 = """$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = if ($env:PYTHON) { $env:PYTHON } else { 'py' }
& $Python (Join-Path $ScriptDir 'install.py') @args
exit $LASTEXITCODE
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a deterministic offline Python wheel bundle")
    wheel_group = parser.add_mutually_exclusive_group(required=True)
    wheel_group.add_argument("--wheel", type=Path, help="Project wheel")
    wheel_group.add_argument("--wheel-dir", type=Path, help="Directory containing exactly one project wheel")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--platform-label", required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--wheelhouse-dir", type=Path, help="Use an existing wheelhouse instead of pip download")
    parser.add_argument("--source-date-epoch")
    return parser


def _project_version(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as archive:
        metadata_names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ReleaseProvenanceError("Project wheel has an invalid METADATA layout")
        metadata = archive.read(metadata_names[0]).decode("utf-8", errors="strict")
    for line in metadata.splitlines():
        if line.startswith("Version: "):
            return line.removeprefix("Version: ").strip()
    raise ReleaseProvenanceError("Project wheel does not declare a version")


def _download_wheels(python_executable: Path, project_wheel: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    # The Python executable is maintainer/user-selected and all pip arguments are fixed.
    completed = subprocess.run(  # nosec B603
        [
            str(python_executable),
            "-m",
            "pip",
            "download",
            "--disable-pip-version-check",
            "--only-binary=:all:",
            "--dest",
            str(destination),
            str(project_wheel),
        ],
        check=False,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise ReleaseProvenanceError(
            "Could not resolve the offline wheelhouse:\n" + completed.stdout + completed.stderr
        )


def _bundle_members(
    wheelhouse: Path,
    *,
    version: str,
    platform_label: str,
    python_version: str,
    epoch: int,
) -> list[tuple[str, bytes, int]]:
    members: list[tuple[str, bytes, int]] = []
    wheel_records = []
    for wheel in sorted(wheelhouse.glob("*.whl"), key=lambda item: item.name.lower()):
        if wheel.is_symlink() or not wheel.is_file():
            raise ReleaseProvenanceError(f"Wheelhouse entry is unsafe: {wheel}")
        data = wheel.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        member_name = f"wheelhouse/{wheel.name}"
        members.append((member_name, data, 0o644))
        wheel_records.append({"name": wheel.name, "size": len(data), "sha256": digest})
    if not wheel_records:
        raise ReleaseProvenanceError("The offline wheelhouse is empty")

    manifest = {
        "schema_version": BUNDLE_MANIFEST_SCHEMA,
        "project": PROJECT_NAME,
        "version": version,
        "platform_label": platform_label,
        "python_version": python_version,
        "source_date_epoch": epoch,
        "generated_at": timestamp_from_epoch(epoch),
        "browser_included": False,
        "installation_mode": "pip-no-index-wheelhouse",
        "wheels": wheel_records,
    }
    static_members = [
        ("README.md", README_TEMPLATE.format(version=version, platform_label=platform_label, python_version=python_version).encode("utf-8"), 0o644),
        ("install.py", INSTALL_PY.encode("utf-8"), 0o755),
        ("install.sh", INSTALL_SH.encode("utf-8"), 0o755),
        ("install.ps1", INSTALL_PS1.encode("utf-8"), 0o644),
        ("BUNDLE-MANIFEST.json", (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"), 0o644),
    ]
    members.extend(static_members)
    checksum_lines = []
    for name, data, _mode in sorted(members, key=lambda item: item[0]):
        checksum_lines.append(f"{hashlib.sha256(data).hexdigest()}  {name}")
    members.append(("CHECKSUMS.sha256", ("\n".join(checksum_lines) + "\n").encode("utf-8"), 0o644))
    return members


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.wheel is not None:
            wheel = args.wheel.resolve()
        else:
            wheel_dir = args.wheel_dir.resolve()
            candidates = sorted(wheel_dir.glob("mardas_md2pdf-*.whl")) if wheel_dir.is_dir() else []
            if len(candidates) != 1:
                raise ReleaseProvenanceError(
                    f"Expected exactly one project wheel in {wheel_dir}; found {len(candidates)}"
                )
            wheel = candidates[0].resolve()
        if wheel.is_symlink() or not wheel.is_file() or wheel.suffix != ".whl":
            raise ReleaseProvenanceError(f"Project wheel is missing or unsafe: {wheel}")
        version = _project_version(wheel)
        platform_label = normalized_label(args.platform_label)
        epoch = source_date_epoch(args.source_date_epoch)
        with tempfile.TemporaryDirectory(prefix="mardas-offline-bundle-") as temp_name:
            temp_root = Path(temp_name)
            wheelhouse = temp_root / "wheelhouse"
            if args.wheelhouse_dir is None:
                _download_wheels(args.python, wheel, wheelhouse)
            else:
                source = args.wheelhouse_dir.resolve()
                if not source.is_dir():
                    raise ReleaseProvenanceError(f"Wheelhouse directory does not exist: {source}")
                shutil.copytree(source, wheelhouse)
                if not any(path.name == wheel.name for path in wheelhouse.glob("*.whl")):
                    shutil.copy2(wheel, wheelhouse / wheel.name)
            # Query only the explicitly selected Python interpreter.
            python_version = subprocess.check_output(  # nosec B603
                [str(args.python), "-c", "import platform; print(platform.python_version())"],
                text=True,
                encoding="utf-8",
            ).strip()
            members = _bundle_members(
                wheelhouse,
                version=version,
                platform_label=platform_label,
                python_version=python_version,
                epoch=epoch,
            )
            version_parts = python_version.split(".")
            if len(version_parts) < 2 or not all(part.isdigit() for part in version_parts[:2]):
                raise ReleaseProvenanceError(
                    f"Could not determine the Python major/minor version: {python_version!r}"
                )
            python_tag = f"py{version_parts[0]}{version_parts[1]}"
            output_name = (
                f"mardas-md2pdf-{version}-offline-{platform_label}-{python_tag}.zip"
            )
            output_path = args.output_dir.resolve() / output_name
            deterministic_zip(output_path, members, epoch=epoch)
            verify_offline_bundle(output_path, expected_version=version)
    except (ReleaseProvenanceError, OSError, subprocess.SubprocessError, zipfile.BadZipFile) as exc:
        print(f"Offline bundle build failed: {exc}", file=sys.stderr)
        return 2
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from runtime_manifest import (  # noqa: E402
    LEGACY_RUNTIME_MANIFEST_SCHEMA,
    RUNTIME_FILE_TYPE,
    RUNTIME_MANIFEST_SCHEMA,
    RUNTIME_SYMLINK_TYPE,
    has_bundled_browser_file,
    safe_runtime_path,
    validate_local_symlink,
    validate_symlink_graph,
)

MAX_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_FILES = 20_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _lstat_runtime_entry(root: Path, parts: tuple[str, ...]) -> tuple[Path, os.stat_result]:
    """Walk an inventory path without following a symlink in any component."""

    candidate = root
    for index, part in enumerate(parts):
        candidate /= part
        try:
            metadata = candidate.lstat()
        except OSError as exc:
            raise ValueError(f"Runtime entry is missing or unsafe: {'/'.join(parts)}") from exc
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"Runtime inventory traverses an unsafe parent: {candidate}")
    return candidate, metadata


def _sidecar_executable(root: Path) -> Path:
    names = ("mardas-sidecar.exe", "mardas-sidecar")
    for name in names:
        candidate = root / name
        try:
            mode = candidate.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISREG(mode):
            return candidate
    raise ValueError(f"Sidecar executable is missing from {root}")


def _read_messages(process: subprocess.Popen[str], *, expected_ids: set[str]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    assert process.stdout is not None
    while expected_ids - set(results):
        line = process.stdout.readline()
        if not line:
            break
        message = json.loads(line)
        request_id = message.get("id")
        if isinstance(request_id, str):
            results[request_id] = message
    return results


def load_and_verify_manifest(
    root: Path,
    *,
    expected_version: str | None = None,
    require_browser: bool = False,
) -> dict[str, Any]:
    root = root.expanduser()
    try:
        root_mode = root.lstat().st_mode
    except FileNotFoundError as exc:
        raise ValueError(f"Standalone runtime directory is missing: {root}") from exc
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        raise ValueError(f"Standalone runtime root must be a real directory: {root}")
    root = root.resolve(strict=True)
    manifest_path = root / "runtime-manifest.json"
    try:
        manifest_mode = manifest_path.lstat().st_mode
    except FileNotFoundError as exc:
        raise ValueError("Runtime manifest is missing or unreasonably large.") from exc
    if (
        not stat.S_ISREG(manifest_mode)
        or manifest_path.lstat().st_size > MAX_MANIFEST_BYTES
    ):
        raise ValueError("Runtime manifest is missing or unreasonably large.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema_version = manifest.get("schema_version")
    if schema_version not in {
        LEGACY_RUNTIME_MANIFEST_SCHEMA,
        RUNTIME_MANIFEST_SCHEMA,
    }:
        raise ValueError("Runtime manifest schema is unsupported.")
    if expected_version is not None and manifest.get("version") != expected_version:
        raise ValueError("Runtime manifest version does not match the desktop application.")
    if require_browser and manifest.get("browser_bundled") is not True:
        raise ValueError("Desktop runtime must include the pinned Chromium browser.")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_FILES:
        raise ValueError("Runtime manifest contains an invalid file inventory.")
    seen: set[str] = set()
    regular_files: set[str] = set()
    symlinks: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Runtime manifest file entry must be an object.")
        try:
            pure = safe_runtime_path(entry.get("path"))
        except ValueError as exc:
            raise ValueError("Runtime manifest contains an invalid path.") from exc
        relative = pure.as_posix()
        if relative in seen:
            raise ValueError("Runtime manifest contains a duplicate or invalid path.")
        seen.add(relative)
        path, metadata = _lstat_runtime_entry(root, pure.parts)
        entry_type = entry.get("type")
        if schema_version == LEGACY_RUNTIME_MANIFEST_SCHEMA:
            if entry_type not in {None, RUNTIME_FILE_TYPE}:
                raise ValueError("Legacy runtime manifests may contain only regular files.")
            entry_type = RUNTIME_FILE_TYPE
        if entry_type == RUNTIME_FILE_TYPE:
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError(f"Runtime file is missing or unsafe: {relative}")
            expected_size = entry.get("size")
            if (
                not isinstance(expected_size, int)
                or isinstance(expected_size, bool)
                or metadata.st_size != expected_size
                or _sha256(path) != entry.get("sha256")
            ):
                raise ValueError(f"Runtime file integrity mismatch: {relative}")
            regular_files.add(relative)
        elif entry_type == RUNTIME_SYMLINK_TYPE and schema_version == RUNTIME_MANIFEST_SCHEMA:
            if not stat.S_ISLNK(metadata.st_mode):
                raise ValueError(f"Runtime symlink is missing or unsafe: {relative}")
            target = validate_local_symlink(root, path)
            if target != entry.get("target"):
                raise ValueError(f"Runtime symlink target mismatch: {relative}")
            symlinks[relative] = target
        else:
            raise ValueError(f"Runtime manifest entry type is invalid: {relative}")

    if manifest.get("browser_bundled") is True and not has_bundled_browser_file(
        regular_files
    ):
        raise ValueError(
            "Runtime manifest claims bundled Chromium without an inventoried browser file."
        )

    actual: set[str] = set()
    directories: list[str] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if relative == "runtime-manifest.json":
            continue
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            directories.append(relative)
        elif stat.S_ISREG(mode) or stat.S_ISLNK(mode):
            actual.add(relative)
        else:
            raise ValueError(f"Runtime contains an unsupported filesystem entry: {relative}")
    if seen != actual:
        raise ValueError(
            f"Runtime inventory mismatch; missing={sorted(seen-actual)}, extra={sorted(actual-seen)}"
        )
    validate_symlink_graph(seen, symlinks, directories=directories)
    _sidecar_executable(root)
    return manifest


def verify(root: Path, *, render: bool) -> None:
    root = root.expanduser().resolve(strict=True)
    load_and_verify_manifest(root)
    executable = _sidecar_executable(root)
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    process = subprocess.Popen(
        [str(executable)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=environment,
    )
    assert process.stdin is not None
    with tempfile.TemporaryDirectory(prefix="mardas-runtime-smoke-") as temporary:
        temporary_root = Path(temporary)
        expected = {"health", "shutdown"}
        process.stdin.write(
            json.dumps({"jsonrpc": "2.0", "id": "health", "method": "system.health", "params": {}})
            + "\n"
        )
        if render:
            source = temporary_root / "نمونه.md"
            output = temporary_root / "خروجی.pdf"
            source.write_text("# Runtime Smoke\n\nInline math: $E=mc^2$.\n", encoding="utf-8")
            process.stdin.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "render",
                        "method": "render.document",
                        "params": {
                            "input_path": str(source),
                            "output_path": str(output),
                            "discover_config": False,
                            "options": {"cover": False, "toc": True},
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            expected.add("render")
        process.stdin.flush()
        results = _read_messages(process, expected_ids=expected - {"shutdown"})
        process.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "shutdown",
                    "method": "system.shutdown",
                    "params": {"force": False},
                }
            )
            + "\n"
        )
        process.stdin.flush()
        results.update(_read_messages(process, expected_ids={"shutdown"}))
        process.stdin.close()
        return_code = process.wait(timeout=180)
        stderr = process.stderr.read() if process.stderr else ""
        if return_code != 0:
            raise RuntimeError(f"Sidecar exited with {return_code}: {stderr}")
        if "error" in results.get("health", {}):
            raise RuntimeError(f"Runtime health failed: {results['health']}")
        if render:
            if "error" in results.get("render", {}):
                raise RuntimeError(f"Runtime render failed: {results['render']}")
            output = temporary_root / "خروجی.pdf"
            if not output.is_file() or not output.read_bytes().startswith(b"%PDF-"):
                raise RuntimeError("Runtime render did not create a valid PDF header.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify a standalone Mardas sidecar runtime.")
    parser.add_argument("runtime_dir", type=Path)
    parser.add_argument("--render", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    verify(args.runtime_dir, render=args.render)
    print("Standalone runtime verification: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

MAX_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_FILES = 20_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sidecar_executable(root: Path) -> Path:
    names = ("mardas-sidecar.exe", "mardas-sidecar")
    for name in names:
        candidate = root / name
        if candidate.is_file():
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


def verify(root: Path, *, render: bool) -> None:
    root = root.expanduser().resolve(strict=True)
    manifest_path = root / "runtime-manifest.json"
    if not manifest_path.is_file() or manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("Runtime manifest is missing or unreasonably large.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("files")
    if not isinstance(entries, list) or len(entries) > MAX_FILES:
        raise ValueError("Runtime manifest contains an invalid file inventory.")
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Runtime manifest file entry must be an object.")
        relative = entry.get("path")
        if not isinstance(relative, str) or not relative or relative in seen:
            raise ValueError("Runtime manifest contains a duplicate or invalid path.")
        seen.add(relative)
        path = (root / relative).resolve(strict=True)
        path.relative_to(root)
        if path.stat().st_size != entry.get("size") or _sha256(path) != entry.get("sha256"):
            raise ValueError(f"Runtime file integrity mismatch: {relative}")

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

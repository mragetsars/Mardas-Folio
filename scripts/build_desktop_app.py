#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from build_desktop_frontend import build_frontend  # noqa: E402
from stage_desktop_runtime import stage_runtime  # noqa: E402
from verify_desktop_frontend import verify_frontend  # noqa: E402
from verify_desktop_installer import verify_installer  # noqa: E402
from mardas_md2pdf import __version__  # noqa: E402

DESKTOP_ROOT = ROOT / "apps" / "desktop"
TAURI_ROOT = DESKTOP_ROOT / "src-tauri"
CARGO_LOCK = TAURI_ROOT / "Cargo.lock"
DEFAULT_OUTPUT = ROOT / "build" / "desktop"


def architecture_tag() -> str:
    machine = (platform.machine() or "unknown").lower().replace(" ", "-")
    return {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}.get(machine, machine)


def require_tauri_cli() -> None:
    try:
        completed = subprocess.run(
            ["cargo", "tauri", "--version"],
            cwd=TAURI_ROOT,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise SystemExit(
            "Tauri CLI is required. Install Rust, then run "
            "`cargo install tauri-cli --version 2.11.4 --locked`."
        ) from exc
    if "tauri-cli" not in completed.stdout.casefold():
        raise SystemExit(f"Unexpected Tauri CLI response: {completed.stdout.strip()}")


def require_cargo_lock() -> None:
    if CARGO_LOCK.is_symlink() or not CARGO_LOCK.is_file():
        raise SystemExit("A regular committed src-tauri/Cargo.lock is required.")


def build(args: argparse.Namespace) -> Path:
    if platform.system() != "Windows" and not args.allow_non_windows:
        raise SystemExit("The NSIS desktop installer must be built on Windows.")
    runtime = args.runtime.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve(strict=False)
    if args.clean:
        shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True, exist_ok=True)

    frontend = build_frontend(version=__version__)
    verify_frontend(frontend, expected_version=__version__)
    stage_runtime(runtime, expected_version=__version__)
    require_cargo_lock()
    require_tauri_cli()

    environment = os.environ.copy()
    environment["MARDAS_DESKTOP_VERSION"] = __version__
    subprocess.run(
        ["cargo", "tauri", "build", "--bundles", "nsis", "--", "--locked"],
        cwd=TAURI_ROOT,
        env=environment,
        check=True,
    )
    candidates = sorted(
        (TAURI_ROOT / "target" / "release" / "bundle" / "nsis").glob("*-setup.exe"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    if not candidates:
        raise SystemExit("Tauri did not create an NSIS setup executable.")
    final = output / f"Mardas-Folio-{__version__}-windows-{architecture_tag()}-setup.exe"
    temporary = final.with_suffix(final.suffix + ".tmp")
    shutil.copyfile(candidates[0], temporary)
    os.replace(temporary, final)
    payload = verify_installer(final, expected_version=__version__)
    (output / "desktop-release-manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return final


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the native Mardas Folio NSIS installer")
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--clean", action="store_true", default=True)
    parser.add_argument("--no-clean", dest="clean", action="store_false")
    parser.add_argument("--allow-non-windows", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    installer = build(build_parser().parse_args(argv))
    print(f"Mardas Folio installer: {installer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

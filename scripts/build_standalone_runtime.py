#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
DEFAULT_BUILD_ROOT = ROOT / "build" / "standalone-runtime"
MAX_RUNTIME_FILES = 20_000


def _platform_tag() -> str:
    system = platform.system().lower() or sys.platform
    machine = (platform.machine() or "unknown").lower().replace(" ", "-")
    aliases = {"amd64": "x86_64", "x64": "x86_64", "aarch64": "arm64"}
    return f"{system}-{aliases.get(machine, machine)}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _browser_root(executable: Path) -> Path:
    executable = executable.expanduser().resolve(strict=True)
    if not executable.is_file():
        raise ValueError(f"Chromium executable is not a file: {executable}")
    # Playwright browser archives keep all shared libraries/resources next to
    # the executable (or inside the .app bundle on macOS). Copy the complete
    # archive root rather than one binary.
    for parent in (executable.parent, *executable.parents):
        if parent.name.endswith(".app"):
            return parent
        if parent.name.casefold().startswith(
            ("chrome-", "chromium-", "chrome-headless-shell", "chromium")
        ):
            return parent
    return executable.parent


def _browser_type_executable() -> Path | None:
    try:
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        try:
            candidate = Path(playwright.chromium.executable_path).resolve(strict=False)
        finally:
            playwright.stop()
    except Exception:
        return None
    return candidate if candidate.is_file() else None


def _playwright_cache_roots() -> tuple[Path, ...]:
    explicit = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if explicit and explicit != "0":
        return (Path(explicit).expanduser().resolve(strict=False),)
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return (Path(local_app_data).expanduser() / "ms-playwright",)
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Caches" / "ms-playwright",)
    return (Path.home() / ".cache" / "ms-playwright",)


def _find_playwright_headless_shell() -> Path | None:
    names = (
        "chrome-headless-shell.exe",
        "chrome-headless-shell",
        "headless_shell.exe",
        "headless_shell",
    )
    for root in _playwright_cache_roots():
        if not root.is_dir():
            continue
        revision_dirs = sorted(
            (path for path in root.glob("chromium_headless_shell-*") if path.is_dir()),
            reverse=True,
        )
        for revision_dir in revision_dirs:
            for name in names:
                matches = sorted(revision_dir.rglob(name))
                if matches:
                    return matches[0].resolve(strict=False)
    return None


def _playwright_browser() -> Path | None:
    # BrowserType.executable_path resolves a full Chromium installation. An
    # `install chromium --only-shell` release runner intentionally has only the
    # separate headless-shell archive, so probe that cache explicitly as a
    # fallback.
    return _browser_type_executable() or _find_playwright_headless_shell()


def _iter_files(root: Path) -> Iterable[Path]:
    count = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or path.name == "runtime-manifest.json":
            continue
        count += 1
        if count > MAX_RUNTIME_FILES:
            raise RuntimeError(f"Runtime contains more than {MAX_RUNTIME_FILES} files.")
        yield path


def _write_manifest(runtime_dir: Path, *, browser_source: Path | None) -> Path:
    from mardas_md2pdf import __version__
    from mardas_md2pdf.application import ENGINE_API_VERSION
    from mardas_md2pdf.protocol import PROTOCOL_NAME, PROTOCOL_VERSION

    entries = []
    for path in _iter_files(runtime_dir):
        relative = path.relative_to(runtime_dir).as_posix()
        entries.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    manifest = {
        "schema_version": 1,
        "product": "Mardas MD2PDF standalone sidecar runtime",
        "version": __version__,
        "engine_api_version": ENGINE_API_VERSION,
        "protocol": PROTOCOL_NAME,
        "protocol_version": PROTOCOL_VERSION,
        "platform": _platform_tag(),
        "python": platform.python_version(),
        "browser_bundled": browser_source is not None,
        "browser_source_name": browser_source.name if browser_source else None,
        "files": entries,
    }
    path = runtime_dir / "runtime-manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _archive_runtime(runtime_dir: Path, archive_path: Path) -> None:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive_path.with_suffix(archive_path.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    with zipfile.ZipFile(
        temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for path in sorted(runtime_dir.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if path.is_file():
                archive.write(path, Path(runtime_dir.name) / path.relative_to(runtime_dir))
    os.replace(temporary, archive_path)


def build(args: argparse.Namespace) -> tuple[Path, Path | None]:
    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "PyInstaller is required. Install the desktop build dependencies with "
            "`python -m pip install -e '.[desktop]'`."
        ) from exc

    build_root = args.build_root.expanduser().resolve(strict=False)
    if args.clean:
        shutil.rmtree(build_root, ignore_errors=True)
    dist_root = build_root / "dist"
    work_root = build_root / "work"
    dist_root.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)

    browser_executable = args.chromium_path or _playwright_browser()
    browser_source: Path | None = None
    if browser_executable is not None:
        browser_source = _browser_root(browser_executable)
    elif not args.allow_missing_chromium:
        raise SystemExit(
            "Chromium was not found. Run `python -m playwright install chromium --only-shell`, "
            "or provide --chromium-path. Use --allow-missing-chromium only for protocol-only tests."
        )

    environment = os.environ.copy()
    environment["MARDAS_PROJECT_ROOT"] = str(ROOT)
    if browser_source is not None:
        environment["MARDAS_CHROMIUM_SOURCE"] = str(browser_source)
    else:
        environment.pop("MARDAS_CHROMIUM_SOURCE", None)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist_root),
        "--workpath",
        str(work_root),
        str(ROOT / "packaging" / "pyinstaller" / "mardas-sidecar.spec"),
    ]
    subprocess.run(command, cwd=ROOT, env=environment, check=True)

    from mardas_md2pdf import __version__

    produced = dist_root / "mardas-sidecar"
    if not produced.is_dir():
        raise SystemExit(f"PyInstaller did not create the expected runtime directory: {produced}")
    final_dir = build_root / f"Mardas-MD2PDF-{__version__}-runtime-{_platform_tag()}"
    shutil.rmtree(final_dir, ignore_errors=True)
    shutil.move(str(produced), final_dir)
    _write_manifest(final_dir, browser_source=browser_source)

    archive = None
    if not args.no_archive:
        archive = build_root / f"{final_dir.name}.zip"
        _archive_runtime(final_dir, archive)
    return final_dir, archive


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a self-contained PyInstaller onedir runtime for the "
            "Mardas desktop sidecar."
        )
    )
    parser.add_argument("--build-root", type=Path, default=DEFAULT_BUILD_ROOT)
    parser.add_argument("--chromium-path", type=Path)
    parser.add_argument("--allow-missing-chromium", action="store_true")
    parser.add_argument("--no-archive", action="store_true")
    parser.add_argument("--clean", action="store_true", default=True)
    parser.add_argument("--no-clean", dest="clean", action="store_false")
    return parser


def main(argv: list[str] | None = None) -> int:
    runtime_dir, archive = build(build_parser().parse_args(argv))
    print(f"Standalone runtime: {runtime_dir}")
    if archive is not None:
        print(f"Portable archive: {archive}")
        print(f"SHA-256: {_sha256(archive)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

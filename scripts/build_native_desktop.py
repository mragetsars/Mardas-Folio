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
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for path in (SCRIPTS, ROOT / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from build_desktop_frontend import build_frontend  # noqa: E402
from release_provenance import deterministic_zip, source_date_epoch  # noqa: E402
from stage_desktop_runtime import stage_runtime  # noqa: E402
from verify_desktop_frontend import verify_frontend  # noqa: E402
from verify_native_desktop import verify_native_artifact  # noqa: E402
from mardas_md2pdf import __version__  # noqa: E402

DESKTOP_ROOT = ROOT / "apps" / "desktop"
TAURI_ROOT = DESKTOP_ROOT / "src-tauri"
RESOURCE_RUNTIME = TAURI_ROOT / "resources" / "sidecar"
DEFAULT_OUTPUT = ROOT / "build" / "desktop-native"
DEFAULT_UPDATE_ENDPOINT = "https://github.com/mragetsars/Mardas-MD2PDF/releases/latest/download/latest.json"
MAX_UPDATER_PUBKEY_BYTES = 32 * 1024



def architecture_tag() -> str:
    machine = (platform.machine() or "unknown").lower().replace(" ", "-")
    return {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86-64": "x86_64",
        "aarch64": "arm64",
    }.get(machine, machine)


def platform_tag() -> str:
    system = platform.system()
    mapping = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}
    if system not in mapping:
        raise SystemExit(f"Unsupported native desktop build platform: {system}")
    return mapping[system]


def default_bundles(platform_name: str) -> tuple[str, ...]:
    if platform_name == "windows":
        return ("nsis",)
    if platform_name == "macos":
        return ("dmg",)
    if platform_name == "linux":
        return ("appimage", "deb")
    raise ValueError(f"Unsupported platform: {platform_name}")



def _validate_update_endpoint(value: str) -> str:
    candidate = value.strip()
    parsed = urlparse(candidate)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise SystemExit("Updater endpoint must be an HTTPS URL without credentials or fragments.")
    return candidate


def _read_updater_pubkey(path: Path | None, environment: dict[str, str]) -> str:
    if path is not None:
        resolved = path.expanduser().resolve(strict=True)
        if resolved.is_symlink() or not resolved.is_file():
            raise SystemExit(f"Updater public key file is missing or unsafe: {resolved}")
        if resolved.stat().st_size <= 0 or resolved.stat().st_size > MAX_UPDATER_PUBKEY_BYTES:
            raise SystemExit("Updater public key file is empty or exceeds the size limit.")
        value = resolved.read_text(encoding="utf-8").strip()
    else:
        value = environment.get("MARDAS_UPDATER_PUBKEY", "").strip()
    if not value or "\x00" in value or len(value.encode("utf-8")) > MAX_UPDATER_PUBKEY_BYTES:
        raise SystemExit(
            "Updater public key is required for signed release builds. "
            "Pass --updater-pubkey-file or set MARDAS_UPDATER_PUBKEY."
        )
    return value


def _updater_build_config(output: Path) -> Path:
    fd, raw = tempfile.mkstemp(prefix=".mardas-updater-", suffix=".json", dir=output)
    os.close(fd)
    path = Path(raw)
    path.write_text(
        json.dumps({"bundle": {"createUpdaterArtifacts": True}}, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


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
    except (FileNotFoundError, PermissionError, subprocess.CalledProcessError) as exc:
        raise SystemExit(
            "Tauri CLI is required. Install Rust, then run "
            "`cargo install tauri-cli --version 2.11.4 --locked`."
        ) from exc
    if "tauri-cli" not in completed.stdout.casefold():
        raise SystemExit(f"Unexpected Tauri CLI response: {completed.stdout.strip()}")


def _latest_candidate(bundle: str) -> Path:
    locations = {
        "nsis": TAURI_ROOT / "target" / "release" / "bundle" / "nsis",
        "dmg": TAURI_ROOT / "target" / "release" / "bundle" / "dmg",
        "appimage": TAURI_ROOT / "target" / "release" / "bundle" / "appimage",
        "deb": TAURI_ROOT / "target" / "release" / "bundle" / "deb",
    }
    patterns = {
        "nsis": "*-setup.exe",
        "dmg": "*.dmg",
        "appimage": "*.AppImage",
        "deb": "*.deb",
    }
    directory = locations[bundle]
    candidates = sorted(
        directory.glob(patterns[bundle]),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    if not candidates:
        raise SystemExit(f"Tauri did not create the expected {bundle} bundle in {directory}")
    return candidates[0]


def _normalized_name(bundle: str, *, platform_name: str, architecture: str) -> str:
    stem = f"Mardas-Studio-{__version__}-{platform_name}-{architecture}"
    suffixes = {
        "nsis": "-setup.exe",
        "dmg": ".dmg",
        "appimage": ".AppImage",
        "deb": ".deb",
    }
    return stem + suffixes[bundle]


def _copy_verified(
    candidate: Path,
    output: Path,
    *,
    bundle: str,
    platform_name: str,
    architecture: str,
) -> Path:
    final = output / _normalized_name(
        bundle, platform_name=platform_name, architecture=architecture
    )
    temporary = final.with_name(final.name + ".tmp")
    shutil.copyfile(candidate, temporary)
    os.replace(temporary, final)
    verify_native_artifact(final, expected_version=__version__)
    return final


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _portable_members(
    executable: Path,
    runtime_root: Path,
    *,
    root_name: str,
) -> list[tuple[str, bytes, int]]:
    if executable.is_symlink() or not executable.is_file():
        raise SystemExit(f"Windows desktop executable is missing or unsafe: {executable}")
    members: list[tuple[str, bytes, int]] = []
    inventory: list[dict[str, object]] = []

    def add(relative: str, data: bytes, mode: int) -> None:
        inventory.append({"path": relative, "size": len(data), "sha256": _sha256_bytes(data)})
        members.append((f"{root_name}/{relative}", data, mode))

    add("Mardas Studio.exe", executable.read_bytes(), 0o755)
    readme = (
        "Mardas Studio portable build\r\n"
        "\r\n"
        "This package includes the Mardas rendering sidecar and Chromium renderer.\r\n"
        "It uses the system Microsoft Edge WebView2 runtime for the native interface.\r\n"
        "For a prerequisite-free normal installation, use the Windows Setup executable.\r\n"
    ).encode("utf-8")
    add("README.txt", readme, 0o644)

    runtime_root = runtime_root.resolve(strict=True)
    for path in sorted(runtime_root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if path.is_symlink():
            raise SystemExit(f"Portable runtime contains a symlink: {path}")
        if not path.is_file():
            continue
        relative = "sidecar/" + path.relative_to(runtime_root).as_posix()
        add(relative, path.read_bytes(), 0o755 if os.access(path, os.X_OK) else 0o644)

    manifest = {
        "schema_version": 1,
        "product": "Mardas Studio portable",
        "version": __version__,
        "platform": "windows",
        "architecture": architecture_tag(),
        "webview2_bundled": False,
        "preferred_distribution": "setup",
        "files": inventory,
    }
    manifest_data = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    members.append((f"{root_name}/PORTABLE-MANIFEST.json", manifest_data, 0o644))
    return members


def _build_windows_portable(output: Path, *, architecture: str) -> Path:
    executable = TAURI_ROOT / "target" / "release" / "mardas-studio.exe"
    root_name = f"Mardas-Studio-{__version__}-windows-{architecture}-portable"
    final = output / f"{root_name}.zip"
    members = _portable_members(executable, RESOURCE_RUNTIME, root_name=root_name)
    deterministic_zip(final, members, epoch=source_date_epoch())
    verify_native_artifact(final, expected_version=__version__)
    return final



def _copy_signature(candidate: Path, final_payload: Path, output: Path) -> Path:
    signature = Path(str(candidate) + ".sig")
    if not signature.is_file() or signature.is_symlink():
        raise SystemExit(f"Tauri did not create updater signature: {signature}")
    final = output / f"{final_payload.name}.sig"
    temporary = final.with_name(final.name + ".tmp")
    shutil.copyfile(signature, temporary)
    os.replace(temporary, final)
    verify_native_artifact(final, expected_version=__version__)
    return final


def _latest_macos_updater() -> Path:
    directory = TAURI_ROOT / "target" / "release" / "bundle" / "macos"
    candidates = sorted(
        directory.glob("*.app.tar.gz"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    if not candidates:
        raise SystemExit(f"Tauri did not create a macOS updater bundle in {directory}")
    return candidates[0]


def _copy_updater_artifacts(
    *,
    platform_name: str,
    architecture: str,
    bundles: tuple[str, ...],
    normal_artifacts: list[Path],
    output: Path,
) -> list[Path]:
    created: list[Path] = []
    if platform_name == "windows":
        if "nsis" not in bundles:
            raise SystemExit("Signed Windows updater artifacts require the NSIS bundle.")
        candidate = _latest_candidate("nsis")
        payload = next(path for path in normal_artifacts if path.name.endswith("-setup.exe"))
        created.append(_copy_signature(candidate, payload, output))
    elif platform_name == "linux":
        if "appimage" not in bundles:
            raise SystemExit("Signed Linux updater artifacts require the AppImage bundle.")
        candidate = _latest_candidate("appimage")
        payload = next(path for path in normal_artifacts if path.name.endswith(".AppImage"))
        created.append(_copy_signature(candidate, payload, output))
    elif platform_name == "macos":
        candidate = _latest_macos_updater()
        stem = f"Mardas-Studio-{__version__}-macos-{architecture}-updater.tar.gz"
        payload = output / stem
        temporary = payload.with_name(payload.name + ".tmp")
        shutil.copyfile(candidate, temporary)
        os.replace(temporary, payload)
        verify_native_artifact(payload, expected_version=__version__)
        created.append(payload)
        created.append(_copy_signature(candidate, payload, output))
    else:
        raise SystemExit(f"Unsupported updater platform: {platform_name}")
    return created


def build(args: argparse.Namespace) -> list[Path]:
    platform_name = platform_tag()
    architecture = architecture_tag()
    bundles = tuple(args.bundle) if args.bundle else default_bundles(platform_name)
    allowed = set(default_bundles(platform_name))
    if not bundles or any(bundle not in allowed for bundle in bundles):
        raise SystemExit(
            f"Invalid bundle selection for {platform_name}: {', '.join(bundles) or '<none>'}"
        )

    runtime = args.runtime.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve(strict=False)
    if args.clean:
        shutil.rmtree(output, ignore_errors=True)
    output.mkdir(parents=True, exist_ok=True)

    frontend = build_frontend(version=__version__)
    verify_frontend(frontend, expected_version=__version__)
    stage_runtime(runtime, expected_version=__version__)
    require_tauri_cli()

    environment = os.environ.copy()
    environment["MARDAS_DESKTOP_VERSION"] = __version__
    updater_config: Path | None = None
    if args.create_updater_artifacts:
        private_key = environment.get("TAURI_SIGNING_PRIVATE_KEY", "").strip()
        if not private_key:
            raise SystemExit(
                "TAURI_SIGNING_PRIVATE_KEY is required when --create-updater-artifacts is used."
            )
        environment["MARDAS_UPDATER_PUBKEY"] = _read_updater_pubkey(
            args.updater_pubkey_file, environment
        )
        environment["MARDAS_UPDATE_ENDPOINT"] = _validate_update_endpoint(
            args.updater_endpoint or DEFAULT_UPDATE_ENDPOINT
        )
        updater_config = _updater_build_config(output)

    command = ["cargo", "tauri", "build", "--bundles", ",".join(bundles)]
    if updater_config is not None:
        command.extend(["--config", str(updater_config)])
    try:
        subprocess.run(command, cwd=TAURI_ROOT, env=environment, check=True)
    finally:
        if updater_config is not None:
            updater_config.unlink(missing_ok=True)

    artifacts = [
        _copy_verified(
            _latest_candidate(bundle),
            output,
            bundle=bundle,
            platform_name=platform_name,
            architecture=architecture,
        )
        for bundle in bundles
    ]
    if platform_name == "windows" and not args.no_portable:
        artifacts.append(_build_windows_portable(output, architecture=architecture))
    if args.create_updater_artifacts:
        artifacts.extend(
            _copy_updater_artifacts(
                platform_name=platform_name,
                architecture=architecture,
                bundles=bundles,
                normal_artifacts=artifacts,
                output=output,
            )
        )

    payloads = [verify_native_artifact(path, expected_version=__version__) for path in artifacts]
    manifest = {
        "schema_version": 1,
        "product": "Mardas Studio native desktop artifacts",
        "version": __version__,
        "platform": platform_name,
        "architecture": architecture,
        "signed_updater_artifacts": bool(args.create_updater_artifacts),
        "artifacts": payloads,
    }
    (output / "desktop-native-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return artifacts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build normalized Mardas Studio native desktop packages on the current OS"
    )
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--bundle",
        action="append",
        choices=("nsis", "dmg", "appimage", "deb"),
        help="Override the default bundle(s) for the current platform",
    )
    parser.add_argument("--no-portable", action="store_true")
    parser.add_argument(
        "--create-updater-artifacts",
        action="store_true",
        help="Create Tauri v2 signed updater artifacts; requires TAURI_SIGNING_PRIVATE_KEY",
    )
    parser.add_argument("--updater-pubkey-file", type=Path)
    parser.add_argument(
        "--updater-endpoint",
        default=None,
        help="HTTPS latest.json endpoint embedded into signed release builds",
    )
    parser.add_argument("--clean", action="store_true", default=True)
    parser.add_argument("--no-clean", dest="clean", action="store_false")
    return parser


def main(argv: list[str] | None = None) -> int:
    artifacts = build(build_parser().parse_args(argv))
    for artifact in artifacts:
        print(f"Native desktop artifact: {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

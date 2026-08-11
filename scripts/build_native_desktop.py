#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

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
from mardas_folio import __version__  # noqa: E402

DESKTOP_ROOT = ROOT / "apps" / "desktop"
TAURI_ROOT = DESKTOP_ROOT / "src-tauri"
CARGO_LOCK = TAURI_ROOT / "Cargo.lock"
RESOURCE_RUNTIME = TAURI_ROOT / "resources" / "sidecar"
DEFAULT_OUTPUT = ROOT / "build" / "desktop-native"
DEFAULT_UPDATE_ENDPOINT = "https://github.com/mragetsars/Mardas-Folio/releases/latest/download/latest.json"
MAX_UPDATER_PUBKEY_BYTES = 32 * 1024
MAX_SIGNING_VALUE_BYTES = 4096
MAX_CARGO_LOCK_BYTES = 4 * 1024 * 1024
WINDOWS_THUMBPRINT_RE = re.compile(r"^[0-9A-Fa-f]{40}$")
APPLE_IDENTITY_RE = re.compile(
    r"^Developer ID Application: [^\x00-\x1f\x7f]{1,350} \((?P<team>[A-Z0-9]{10})\)$"
)
APPLE_API_ISSUER_RE = re.compile(
    r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$"
)
APPLE_API_KEY_RE = re.compile(r"^[A-Z0-9]{10}$")
APPLE_TEAM_ID_RE = re.compile(r"^[A-Z0-9]{10}$")
APPLE_ID_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")



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


def _bounded_environment_value(environment: dict[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if (
        not value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or len(value.encode("utf-8")) > MAX_SIGNING_VALUE_BYTES
    ):
        raise SystemExit(f"{name} is required and must contain one bounded line of text.")
    return value


def _validate_timestamp_url(value: str) -> str:
    candidate = value.strip()
    try:
        parsed = urlparse(candidate)
    except ValueError as exc:
        raise SystemExit("Windows timestamp URL is invalid.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.fragment
        or any(character.isspace() for character in candidate)
    ):
        raise SystemExit(
            "Windows timestamp URL must use HTTP(S) without credentials or fragments."
        )
    return candidate


def _windows_signing_config(environment: dict[str, str]) -> dict[str, object]:
    thumbprint = _bounded_environment_value(
        environment, "MARDAS_WINDOWS_CERTIFICATE_THUMBPRINT"
    )
    if not WINDOWS_THUMBPRINT_RE.fullmatch(thumbprint):
        raise SystemExit(
            "MARDAS_WINDOWS_CERTIFICATE_THUMBPRINT must be exactly 40 hexadecimal characters."
        )
    digest = environment.get("MARDAS_WINDOWS_DIGEST_ALGORITHM", "sha256").strip().lower()
    if digest != "sha256":
        raise SystemExit("MARDAS_WINDOWS_DIGEST_ALGORITHM must be sha256.")
    timestamp_url = _validate_timestamp_url(
        _bounded_environment_value(environment, "MARDAS_WINDOWS_TIMESTAMP_URL")
    )
    return {
        "certificateThumbprint": thumbprint.upper(),
        "digestAlgorithm": digest,
        "timestampUrl": timestamp_url,
    }


def _macos_signing_config(environment: dict[str, str]) -> dict[str, object]:
    identity = _bounded_environment_value(environment, "APPLE_SIGNING_IDENTITY")
    identity_match = APPLE_IDENTITY_RE.fullmatch(identity)
    if identity_match is None:
        raise SystemExit(
            "APPLE_SIGNING_IDENTITY must name a Developer ID Application certificate "
            "and end with its 10-character team ID."
        )

    api_names = ("APPLE_API_ISSUER", "APPLE_API_KEY", "APPLE_API_KEY_PATH")
    apple_id_names = ("APPLE_ID", "APPLE_PASSWORD", "APPLE_TEAM_ID")
    api_values = tuple(environment.get(name, "").strip() for name in api_names)
    apple_id_values = tuple(environment.get(name, "").strip() for name in apple_id_names)
    api_present = any(api_values)
    apple_id_present = any(apple_id_values[:2])
    api_ready = all(api_values)
    apple_id_ready = all(apple_id_values)
    if api_present and not api_ready:
        raise SystemExit(
            "App Store Connect notarization credentials are incomplete; set issuer, key ID, "
            "and key path together."
        )
    if apple_id_present and not apple_id_ready:
        raise SystemExit(
            "Apple ID notarization credentials are incomplete; set Apple ID, app-specific "
            "password, and team ID together."
        )
    if api_ready == apple_id_ready:
        raise SystemExit(
            "Public macOS builds require exactly one complete notarization credential set: "
            "App Store Connect API or Apple ID."
        )
    if api_ready:
        issuer, key_id, raw_path = api_values
        if not APPLE_API_ISSUER_RE.fullmatch(issuer) or not APPLE_API_KEY_RE.fullmatch(key_id):
            raise SystemExit("App Store Connect issuer or key ID has an invalid format.")
        key_path = Path(raw_path).expanduser()
        if not key_path.is_absolute() or key_path.is_symlink():
            raise SystemExit("APPLE_API_KEY_PATH must be an absolute, non-symbolic path.")
        try:
            key_path = key_path.resolve(strict=True)
            key_size = key_path.stat().st_size
            key_text = key_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SystemExit("APPLE_API_KEY_PATH is missing or unreadable.") from exc
        if (
            not key_path.is_file()
            or not 64 <= key_size <= 64 * 1024
            or "\x00" in key_text
            or "-----BEGIN PRIVATE KEY-----" not in key_text
            or "-----END PRIVATE KEY-----" not in key_text
        ):
            raise SystemExit("APPLE_API_KEY_PATH does not contain a bounded PEM private key.")
        configured_team = apple_id_values[2]
        if configured_team and (
            not APPLE_TEAM_ID_RE.fullmatch(configured_team)
            or configured_team != identity_match.group("team")
        ):
            raise SystemExit(
                "APPLE_TEAM_ID does not match the Developer ID signing identity."
            )
    else:
        apple_id, password, team_id = apple_id_values
        if (
            not APPLE_ID_RE.fullmatch(apple_id)
            or not APPLE_TEAM_ID_RE.fullmatch(team_id)
            or team_id != identity_match.group("team")
            or any(
                not value
                or "\x00" in value
                or "\r" in value
                or "\n" in value
                or len(value.encode("utf-8")) > MAX_SIGNING_VALUE_BYTES
                for value in (apple_id, password, team_id)
            )
        ):
            raise SystemExit(
                "Apple ID credentials are invalid or their team ID does not match the signing "
                "identity."
            )
    return {"signingIdentity": identity}


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


def _write_temporary_build_config(
    output: Path, *, prefix: str, payload: dict[str, object]
) -> Path:
    fd, raw = tempfile.mkstemp(prefix=prefix, suffix=".json", dir=output)
    path = Path(raw)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path


def _updater_build_config(output: Path) -> Path:
    return _write_temporary_build_config(
        output,
        prefix=".mardas-updater-",
        payload={"bundle": {"createUpdaterArtifacts": True}},
    )


def _native_build_config(
    output: Path,
    *,
    create_updater_artifacts: bool,
    release_mode: str,
    platform_name: str,
    environment: dict[str, str],
) -> tuple[Path | None, dict[str, object]]:
    if release_mode not in {"draft", "public"}:
        raise SystemExit(f"Unsupported native release mode: {release_mode}")
    bundle: dict[str, object] = {}
    plugins: dict[str, object] = {}
    if create_updater_artifacts:
        bundle["createUpdaterArtifacts"] = True
        # The committed configuration carries an empty pubkey so ordinary
        # source builds stay offline, and the Rust side reads the real key from
        # a compile-time variable. `tauri-plugin-updater` validates the *config*
        # key as well, though, and an empty one fails the build with "Missing
        # comment in public key" — so a release build has to supply it here too.
        pubkey = environment.get("MARDAS_UPDATER_PUBKEY", "").strip()
        endpoint = environment.get("MARDAS_UPDATE_ENDPOINT", "").strip()
        if not pubkey or not endpoint:
            raise SystemExit(
                "Updater artifacts need MARDAS_UPDATER_PUBKEY and "
                "MARDAS_UPDATE_ENDPOINT; the bundler rejects an empty key."
            )
        plugins["updater"] = {"pubkey": pubkey, "endpoints": [endpoint]}

    signing_required = release_mode == "public" and platform_name in {"windows", "macos"}
    signing: dict[str, object] = {
        "release_mode": release_mode,
        "required": signing_required,
        "requested": signing_required,
        "verified": False,
        "status": "pending-verification" if signing_required else "not-requested",
        "method": None,
    }
    if release_mode == "public" and platform_name == "windows":
        windows = _windows_signing_config(environment)
        bundle["windows"] = windows
        signing["method"] = "certificate-thumbprint"
        signing["certificate_thumbprint"] = windows["certificateThumbprint"]
        signing["digest_algorithm"] = windows["digestAlgorithm"]
        signing["timestamp_url"] = windows["timestampUrl"]
    elif release_mode == "public" and platform_name == "macos":
        macos = _macos_signing_config(environment)
        bundle["macOS"] = macos
        signing["method"] = "developer-id"
        signing["identity"] = macos["signingIdentity"]
        signing["notarization_method"] = (
            "app-store-connect-api"
            if environment.get("APPLE_API_ISSUER", "").strip()
            else "apple-id"
        )
    elif release_mode == "public":
        signing["status"] = "not-required"

    if not bundle and not plugins:
        return None, signing
    payload: dict[str, object] = {}
    if bundle:
        payload["bundle"] = bundle
    if plugins:
        payload["plugins"] = plugins
    path = _write_temporary_build_config(
        output,
        prefix=".mardas-native-build-",
        payload=payload,
    )
    return path, signing


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


def require_cargo_lock() -> None:
    if CARGO_LOCK.is_symlink() or not CARGO_LOCK.is_file():
        raise SystemExit("A regular committed src-tauri/Cargo.lock is required.")
    try:
        size = CARGO_LOCK.stat().st_size
        content = CARGO_LOCK.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SystemExit("Could not read the committed src-tauri/Cargo.lock.") from exc
    valid_version = re.search(r"(?m)^version = [34]$", content[:256]) is not None
    if not 0 < size <= MAX_CARGO_LOCK_BYTES or not valid_version:
        raise SystemExit("The committed src-tauri/Cargo.lock is invalid.")


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
    stem = f"Mardas-Folio-{__version__}-{platform_name}-{architecture}"
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

    add("Mardas Folio.exe", executable.read_bytes(), 0o755)
    readme = (
        "Mardas Folio portable build\r\n"
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
        "product": "Mardas Folio portable",
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
    executable = TAURI_ROOT / "target" / "release" / "mardas-folio.exe"
    root_name = f"Mardas-Folio-{__version__}-windows-{architecture}-portable"
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
        stem = f"Mardas-Folio-{__version__}-macos-{architecture}-updater.tar.gz"
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


def _run_tauri_build(
    command: list[str], *, environment: dict[str, str], build_config: Path | None
) -> None:
    if command[-2:] != ["--", "--locked"]:
        raise SystemExit("Native desktop builds must use the committed Cargo.lock.")
    try:
        subprocess.run(command, cwd=TAURI_ROOT, env=environment, check=True)
    finally:
        if build_config is not None:
            build_config.unlink(missing_ok=True)


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
    require_cargo_lock()
    require_tauri_cli()

    environment = os.environ.copy()
    environment["MARDAS_DESKTOP_VERSION"] = __version__
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
    build_config, signing_contract = _native_build_config(
        output,
        create_updater_artifacts=args.create_updater_artifacts,
        release_mode=args.release_mode,
        platform_name=platform_name,
        environment=environment,
    )

    command = ["cargo", "tauri", "build", "--bundles", ",".join(bundles)]
    if build_config is not None:
        command.extend(["--config", str(build_config)])
    command.extend(["--", "--locked"])
    _run_tauri_build(command, environment=environment, build_config=build_config)

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
        "product": "Mardas Folio native desktop artifacts",
        "version": __version__,
        "platform": platform_name,
        "architecture": architecture,
        "release_mode": args.release_mode,
        "os_signing": signing_contract,
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
        description="Build normalized Mardas Folio native desktop packages on the current OS"
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
        "--release-mode",
        choices=("draft", "public"),
        default="draft",
        help="Draft builds omit OS trust signing; public builds require and verify it.",
    )
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

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from . import __version__
from .protocol import PROTOCOL_NAME, PROTOCOL_VERSION
from .runtime import resolved_chromium_path, runtime_info, runtime_root

SUPPORT_BUNDLE_SCHEMA = 1
MAX_RUNTIME_MANIFEST_BYTES = 8 * 1024 * 1024


class SupportBundleError(RuntimeError):
    """Raised when a privacy-safe support bundle cannot be created."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _runtime_manifest_summary() -> dict[str, Any] | None:
    path = runtime_root() / "runtime-manifest.json"
    if not path.is_file() or path.is_symlink():
        return None
    try:
        if path.stat().st_size > MAX_RUNTIME_MANIFEST_BYTES:
            return {"present": True, "valid": False, "reason": "manifest-too-large"}
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"present": True, "valid": False, "reason": "manifest-unreadable"}

    files = payload.get("files")
    return {
        "present": True,
        "valid": isinstance(payload, dict),
        "schema_version": payload.get("schema_version"),
        "version": payload.get("version"),
        "engine_api_version": payload.get("engine_api_version"),
        "protocol": payload.get("protocol"),
        "protocol_version": payload.get("protocol_version"),
        "platform": payload.get("platform"),
        "browser_bundled": payload.get("browser_bundled"),
        "file_count": len(files) if isinstance(files, list) else None,
        "sha256": _sha256(path),
    }


def support_payload(*, engine_api_version: str) -> dict[str, Any]:
    info = runtime_info()
    browser = resolved_chromium_path()
    return {
        "schema_version": SUPPORT_BUNDLE_SCHEMA,
        "created_at": datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
        "product": "Mardas Studio",
        "version": __version__,
        "engine_api_version": engine_api_version,
        "protocol": PROTOCOL_NAME,
        "protocol_version": PROTOCOL_VERSION,
        "runtime": {
            "frozen": info.frozen,
            "platform": info.platform,
            "architecture": info.architecture,
            "python_version": info.python_version,
            "chromium_available": browser is not None,
            "chromium_filename": browser.name if browser is not None else None,
            "runtime_manifest": _runtime_manifest_summary(),
        },
        "privacy": {
            "document_content_included": False,
            "document_paths_included": False,
            "environment_variables_included": False,
            "home_directory_included": False,
        },
    }


def _validate_output_path(path: Path) -> Path:
    candidate = path.expanduser().resolve(strict=False)
    if candidate.suffix.casefold() != ".zip":
        raise SupportBundleError("Support bundle output must use the .zip extension.")
    if candidate.exists() and candidate.is_symlink():
        raise SupportBundleError("Support bundle output cannot be a symbolic link.")
    parent = candidate.parent
    if not parent.is_dir():
        raise SupportBundleError(f"Support bundle directory does not exist: {parent}")
    return candidate


def create_support_bundle(
    output_path: Path,
    *,
    engine_api_version: str,
) -> dict[str, Any]:
    output = _validate_output_path(Path(output_path))
    payload = support_payload(engine_api_version=engine_api_version)
    readme = (
        "Mardas Studio Support Bundle\n"
        "============================\n\n"
        "This archive is designed for troubleshooting Mardas Studio itself.\n"
        "It intentionally excludes document contents, document paths, environment "
        "variables, and the user's home directory.\n\n"
        f"Mardas Studio version: {payload['version']}\n"
        f"Platform: {payload['runtime']['platform']}\n"
        f"Architecture: {payload['runtime']['architecture']}\n"
        f"Chromium available: {payload['runtime']['chromium_available']}\n"
    )

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.",
        suffix=".tmp",
        dir=output.parent,
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            archive.writestr(
                "support.json",
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            )
            archive.writestr("README.txt", readme)
        existing_mode = output.stat().st_mode & 0o777 if output.exists() else None
        if existing_mode is not None:
            os.chmod(temporary, existing_mode)
        else:
            current_umask = os.umask(0)
            os.umask(current_umask)
            os.chmod(temporary, 0o666 & ~current_umask)
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    return {
        "output_path": str(output),
        "size_bytes": output.stat().st_size,
        "sha256": _sha256(output),
        "privacy": payload["privacy"],
    }

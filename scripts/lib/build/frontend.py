"""Frontend manifest contract shared by build and verification."""

from __future__ import annotations

import hashlib
from pathlib import Path

from lib.paths import ROOT

MAX_FILES = 1_000
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024


def project_version() -> str:
    namespace: dict[str, str] = {}
    exec((ROOT / "src" / "mardas_folio" / "__init__.py").read_text(encoding="utf-8"), namespace)
    return str(namespace["__version__"])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

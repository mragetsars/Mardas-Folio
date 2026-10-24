"""Validate staged artifacts before replacing an earlier successful build."""
from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path


def publish_verified(candidate: Path, final: Path, verify: Callable[[Path], object]) -> Path:
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError(f"Build artifact is missing or unsafe: {candidate}")
    with tempfile.TemporaryDirectory(prefix=".mardas-publish-", dir=final.parent) as directory:
        staged = Path(directory) / final.name
        shutil.copyfile(candidate, staged)
        verify(staged)
        os.replace(staged, final)
    return final


def publish_directory(candidate: Path, final: Path, verify: Callable[[Path], object]) -> Path:
    if candidate.is_symlink() or not candidate.is_dir():
        raise ValueError(f"Build directory is missing or unsafe: {candidate}")
    verify(candidate)
    backup = Path(tempfile.mkdtemp(prefix=".mardas-runtime-backup-", dir=final.parent))
    backup.rmdir()
    if final.exists():
        final.replace(backup)
    try:
        candidate.replace(final)
    except Exception:
        if not final.exists() and backup.exists():
            backup.replace(final)
        raise
    shutil.rmtree(backup, ignore_errors=True)
    return final

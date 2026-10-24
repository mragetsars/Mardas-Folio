"""Ownership checks before build tools replace or recursively clean directories."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterable

MARKER = ".mardas-build-output.json"


def mark_output(path: Path, *, workspace: Path) -> None:
    # Never follow an existing marker symlink during an incremental build.
    descriptor, name = tempfile.mkstemp(prefix=".mardas-owner-", dir=path)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"schema_version": 1, "producer": "mardas-folio-build"}) + "\n")
        os.replace(temporary, path / MARKER)
    finally:
        temporary.unlink(missing_ok=True)


def validate_output(
    path: Path,
    *,
    workspace: Path,
    protected: Iterable[Path] = (),
    generated: Iterable[Path] = (),
    placeholder_files: frozenset[str] = frozenset(),
) -> Path:
    candidate = path.expanduser().absolute()
    # Inspect the spelling before resolve(), which otherwise hides a symlink
    # pointing at a source directory or somebody else's build output.
    if any(parent.is_symlink() for parent in (candidate, *candidate.parents)):
        raise ValueError(f"Build output must not contain a symlink: {candidate}")
    candidate = candidate.resolve()
    workspace = workspace.resolve()
    home = Path.home().resolve()
    if candidate in (workspace, home) or candidate in workspace.parents or candidate in home.parents:
        raise ValueError(f"Refusing unsafe build output: {candidate}")
    for source in protected:
        source = source.resolve()
        if candidate == source or candidate in source.parents or source in candidate.parents:
            raise ValueError(f"Build output overlaps an input: {candidate}")
    allowed_roots = (workspace / "build", workspace / "dist", *(p.resolve() for p in generated))
    managed = any(candidate == root or root in candidate.parents for root in allowed_roots)
    if workspace in candidate.parents and not managed:
        raise ValueError(f"Build output would replace project sources: {candidate}")
    if candidate.exists():
        if not candidate.is_dir():
            raise ValueError(f"Build output is not a directory: {candidate}")
        entries = {item.name for item in candidate.iterdir()}
        marker = candidate / MARKER
        owned = False
        if marker.is_file() and not marker.is_symlink():
            try:
                owned = json.loads(marker.read_text(encoding="utf-8")) == {
                    "schema_version": 1, "producer": "mardas-folio-build"
                }
            except (OSError, ValueError):
                pass
        placeholders = entries.issubset(placeholder_files) and all(
            (candidate / name).is_file() and not (candidate / name).is_symlink()
            for name in entries
        )
        if entries and not managed and not owned and not placeholders:
            raise ValueError(
                f"Refusing to replace an unowned, nonempty build directory: {candidate}. "
                "Choose a new or empty output directory."
            )
    return candidate


def prepare_output(
    path: Path, *, workspace: Path, clean: bool,
    protected: Iterable[Path] = (), generated: Iterable[Path] = (),
) -> Path:
    candidate = validate_output(path, workspace=workspace, protected=protected, generated=generated)
    if clean and candidate.exists():
        shutil.rmtree(candidate)
    candidate.mkdir(parents=True, exist_ok=True)
    mark_output(candidate, workspace=workspace)
    return candidate

"""Bounded local asset discovery and anchored, create-only asset imports."""

from __future__ import annotations

import hashlib
import os
import secrets
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Callable

from .engine_errors import EngineError
from .file_io import serialized_file_write
from .render_contracts import RenderCancelledError
from .workspace import WORKSPACE_IGNORED_PARTS

CancellationCallback = Callable[[], bool]

MAX_IMPORTED_ASSET_BYTES = 64 * 1024 * 1024
MAX_DOCUMENT_ASSETS = 500
MAX_DOCUMENT_ASSET_SCAN_ENTRIES = 20_000
MAX_DOCUMENT_ASSET_DEPTH = 4
_ASSET_EXTENSIONS = {
    ".avif",
    ".bib",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".json",
    ".png",
    ".svg",
    ".webp",
    ".yaml",
    ".yml",
}


def _is_reparse_point(path: Path) -> bool:
    """Detect symlinks and Windows junctions without following the final path."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


@contextmanager
def _locked_asset_directory(path: Path):
    """Keep an import anchored to the inspected directory."""
    if os.name == "nt":
        from ._windows_paths import locked_directory

        with locked_directory(path):
            yield None
        return
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def list_document_assets(
    path: str | os.PathLike[str], *, cancelled: CancellationCallback | None = None
) -> dict[str, Any]:
    document = Path(path).expanduser().resolve(strict=False)
    root = document.parent
    assets: list[dict[str, Any]] = []
    if not root.is_dir():
        return {"root": str(root), "assets": assets}
    scanned = 0
    truncated = False
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        if cancelled and cancelled():
            raise RenderCancelledError("Asset discovery was cancelled.")
        current_path = Path(current)
        try:
            relative = current_path.relative_to(root)
            parts = [
                root.joinpath(*relative.parts[:index])
                for index in range(1, len(relative.parts) + 1)
            ]
            if any(
                _is_reparse_point(part) for part in parts
            ) or not current_path.resolve().is_relative_to(root):
                directory_names[:] = []
                continue
        except (OSError, RuntimeError, ValueError):
            directory_names[:] = []
            continue
        depth = len(current_path.relative_to(root).parts)
        safe_directories: list[str] = []
        for name in sorted(directory_names, key=str.casefold):
            scanned += 1
            if scanned > MAX_DOCUMENT_ASSET_SCAN_ENTRIES:
                truncated = True
                break
            if (
                depth < MAX_DOCUMENT_ASSET_DEPTH - 1
                and not name.startswith(".")
                and name not in WORKSPACE_IGNORED_PARTS
                and not _is_reparse_point(current_path / name)
                and (current_path / name).resolve(strict=False).is_relative_to(root)
            ):
                safe_directories.append(name)
        directory_names[:] = safe_directories
        if truncated:
            break
        for name in sorted(file_names, key=str.casefold):
            if cancelled and cancelled():
                raise RenderCancelledError("Asset discovery was cancelled.")
            scanned += 1
            if scanned > MAX_DOCUMENT_ASSET_SCAN_ENTRIES:
                truncated = True
                break
            candidate = current_path / name
            if name.startswith(".") or candidate.suffix.casefold() not in _ASSET_EXTENSIONS:
                continue
            try:
                if (
                    _is_reparse_point(candidate)
                    or not candidate.is_file()
                    or not candidate.resolve(strict=False).is_relative_to(root)
                ):
                    continue
                stat_result = candidate.stat()
            except OSError:
                continue
            if len(assets) >= MAX_DOCUMENT_ASSETS:
                truncated = True
                break
            assets.append(
                {
                    "path": str(candidate),
                    "relative_path": candidate.relative_to(root).as_posix(),
                    "name": candidate.name,
                    "extension": candidate.suffix.casefold(),
                    "size_bytes": stat_result.st_size,
                }
            )
        if truncated:
            break
    assets.sort(key=lambda item: item["relative_path"].casefold())
    return {"root": str(root), "assets": assets, "truncated": truncated}


@serialized_file_write
def import_document_asset(
    document_path: str | os.PathLike[str], source_path: str | os.PathLike[str]
) -> dict[str, Any]:
    document = Path(document_path).expanduser().resolve(strict=False)
    selected_source = Path(source_path).expanduser()
    if _is_reparse_point(selected_source):
        raise EngineError(
            "Symbolic-link assets are not accepted.",
            code="MARDAS-ASSET-INVALID",
            details={"path": str(selected_source)},
        )
    try:
        source = selected_source.resolve(strict=True)
        source_stat = source.stat()
    except (OSError, RuntimeError) as exc:
        raise EngineError(
            "Selected asset could not be opened.",
            code="MARDAS-ASSET-INVALID",
            details={"path": str(selected_source)},
        ) from exc
    if not source.is_file():
        raise EngineError(
            "Selected asset is not a regular file.",
            code="MARDAS-ASSET-INVALID",
            details={"path": str(source)},
        )
    if source.suffix.casefold() not in _ASSET_EXTENSIONS:
        raise EngineError(
            "Selected asset type is not supported.",
            code="MARDAS-ASSET-TYPE",
            details={"extension": source.suffix.casefold()},
        )
    size = source_stat.st_size
    if size > MAX_IMPORTED_ASSET_BYTES:
        raise EngineError(
            "Selected asset exceeds the import size limit.",
            code="MARDAS-ASSET-TOO-LARGE",
            details={"size_bytes": size, "limit_bytes": MAX_IMPORTED_ASSET_BYTES},
        )
    try:
        with source.open("rb") as handle:
            payload = handle.read(MAX_IMPORTED_ASSET_BYTES + 1)
    except OSError as exc:
        raise EngineError(
            f"Could not read selected asset: {exc}",
            code="MARDAS-ASSET-IMPORT",
            details={"path": str(source)},
        ) from exc

    if len(payload) > MAX_IMPORTED_ASSET_BYTES:
        raise EngineError(
            "Selected asset exceeds the import size limit.",
            code="MARDAS-ASSET-TOO-LARGE",
            details={"size_bytes": len(payload), "limit_bytes": MAX_IMPORTED_ASSET_BYTES},
        )

    target_dir = document.parent / "assets"
    if _is_reparse_point(target_dir) or (target_dir.exists() and not target_dir.is_dir()):
        raise EngineError(
            "The document assets path must be a regular directory, not a file or symbolic link.",
            code="MARDAS-ASSET-INVALID",
            details={"path": str(target_dir)},
        )
    stem = source.stem or "asset"
    suffix = source.suffix.casefold()
    source_digest = hashlib.sha256(payload).digest()
    try:
        with ExitStack() as locks:
            if os.name == "nt":
                # Keep the canonical document directory stable before creating
                # or opening its assets child. Windows does not provide the
                # POSIX dir_fd/openat operations used below, so directory
                # handles deny delete/rename sharing while path-based atomic
                # creation is in progress.
                locks.enter_context(_locked_asset_directory(document.parent))
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise EngineError(
                    "The document assets directory could not be created.",
                    code="MARDAS-ASSET-IMPORT",
                    details={"path": str(target_dir)},
                ) from exc
            directory_fd = locks.enter_context(_locked_asset_directory(target_dir))
            if _is_reparse_point(target_dir) or target_dir.resolve() != document.parent / "assets":
                raise OSError("The assets directory is outside the document root")

            temporary = Path(f".mardas-import-{secrets.token_hex(16)}")
            temporary_path = target_dir / temporary.name
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_BINARY", 0)
            if directory_fd is None:
                fd = os.open(temporary_path, flags, 0o600)
            else:
                fd = os.open(str(temporary), flags, 0o600, dir_fd=directory_fd)
            handle = os.fdopen(fd, "wb")
            try:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                handle.close()
                handle = None
                counter = 1
                while True:
                    name = f"{stem}{suffix}" if counter == 1 else f"{stem}-{counter}{suffix}"
                    target = target_dir / name
                    if directory_fd is None:
                        # On Windows rename within one directory is atomic and
                        # fails if the target already exists. The locked,
                        # non-reparse directory keeps the path anchored.
                        if (
                            _is_reparse_point(target_dir)
                            or target_dir.resolve() != document.parent / "assets"
                        ):
                            raise OSError("The assets directory changed during import")
                        try:
                            os.rename(temporary_path, target)
                            break
                        except FileExistsError:
                            from ._windows_paths import matches_regular_file

                            if matches_regular_file(target, len(payload), source_digest):
                                break
                            counter += 1
                    else:
                        current = target_dir.stat(follow_symlinks=False)
                        anchored = os.fstat(directory_fd)
                        if _is_reparse_point(target_dir) or (current.st_dev, current.st_ino) != (
                            anchored.st_dev,
                            anchored.st_ino,
                        ):
                            raise OSError("The assets directory changed during import")
                        try:
                            os.link(
                                str(temporary),
                                name,
                                src_dir_fd=directory_fd,
                                dst_dir_fd=directory_fd,
                                follow_symlinks=False,
                            )
                            break
                        except FileExistsError:
                            if not _is_reparse_point(target) and target.is_file():
                                try:
                                    candidate = os.open(
                                        name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd
                                    )
                                    candidate_handle = os.fdopen(candidate, "rb")
                                    with candidate_handle:
                                        candidate_data = candidate_handle.read(len(payload) + 1)
                                    if hashlib.sha256(candidate_data).digest() == source_digest:
                                        break
                                except OSError:
                                    pass
                            counter += 1
            finally:
                if handle is not None:
                    handle.close()
                if directory_fd is None:
                    temporary_path.unlink(missing_ok=True)
                else:
                    os.unlink(str(temporary), dir_fd=directory_fd)
    except OSError as exc:
        raise EngineError(
            f"Could not import asset: {exc}",
            code="MARDAS-ASSET-IMPORT",
            details={"path": str(target_dir)},
        ) from exc
    return {
        "path": str(target),
        "relative_path": target.relative_to(document.parent).as_posix(),
        "name": target.name,
        "extension": suffix,
        "size_bytes": target.stat().st_size,
    }

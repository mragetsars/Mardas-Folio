"""Coordination for file mutations shared by document and project services."""

from __future__ import annotations

import os
import secrets
import stat
import threading
from functools import wraps
from pathlib import Path
from typing import Callable, ParamSpec, TypeVar

# Book edits can delegate to other file operations. A shared reentrant lock
# keeps their revision checks and name allocation in the same transaction,
# including when callers use multiple EngineService instances in one process.
FILE_WRITE_LOCK = threading.RLock()
_P = ParamSpec("_P")
_R = TypeVar("_R")


def serialized_file_write(function: Callable[_P, _R]) -> Callable[_P, _R]:
    @wraps(function)
    def locked(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with FILE_WRITE_LOCK:
            return function(*args, **kwargs)

    return locked


def open_atomic_output(path: Path, *, mode: int | None = None) -> tuple[int, Path]:
    """Allocate a sibling temporary file without changing the process umask."""
    path = Path(path)
    if mode is None:
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
        except FileNotFoundError:
            pass
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_BINARY", 0)
    for _attempt in range(100):
        temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
        try:
            descriptor = os.open(temporary, flags, 0o666)
        except FileExistsError:
            continue
        try:
            if mode is not None:
                if hasattr(os, "fchmod"):
                    os.fchmod(descriptor, mode)
                else:  # pragma: no cover - Windows fallback.
                    os.chmod(temporary, mode)
        except BaseException:
            os.close(descriptor)
            temporary.unlink(missing_ok=True)
            raise
        return descriptor, temporary
    raise FileExistsError(f"Could not allocate an atomic temporary file for: {path}")


def sync_directory(path: Path) -> None:
    """Best-effort durability after replacement; directories cannot be synced on all OSes."""
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def atomic_write_bytes(
    path: Path,
    payload: bytes,
    *,
    mode: int | None = None,
    before_replace: Callable[[], None] | None = None,
) -> os.stat_result:
    """Commit a complete file, preserving permissions and returning the written revision.

    The caller owns conflict policy and locking. ``before_replace`` runs after
    flushing the temporary file so it can reject a stale write before commit.
    Metadata is captured from that file, never by rereading a possibly changed
    destination. Failed writes, including cancellation, leave no temporary file.
    """
    path = Path(path).expanduser().resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = open_atomic_output(path, mode=mode)
    handle = None
    try:
        handle = os.fdopen(descriptor, "wb")
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            written_stat = os.fstat(handle.fileno())
        if before_replace is not None:
            before_replace()
        os.replace(temporary, path)
        sync_directory(path.parent)
        return written_stat
    finally:
        if handle is None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def atomic_write_text(
    path: Path,
    text: str,
    *,
    mode: int | None = None,
    before_replace: Callable[[], None] | None = None,
) -> os.stat_result:
    """Write UTF-8 without platform newline translation."""
    return atomic_write_bytes(path, text.encode("utf-8"), mode=mode, before_replace=before_replace)

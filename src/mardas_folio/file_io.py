"""Coordination for file mutations shared by document and project services."""

from __future__ import annotations

import threading
import os
import secrets
import stat
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
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
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
        except Exception:
            os.close(descriptor)
            temporary.unlink(missing_ok=True)
            raise
        return descriptor, temporary
    raise FileExistsError(f"Could not allocate an atomic temporary file for: {path}")

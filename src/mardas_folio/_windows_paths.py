"""Small Win32 helpers for no-follow asset operations.

The document engine is also used on POSIX, so importing this module does not
load Windows DLLs.  These helpers are called only by the Windows asset path.
"""

from __future__ import annotations

import ctypes
import hashlib
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_FILE_READ_ATTRIBUTES = 0x0080
_GENERIC_READ = 0x80000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_DIRECTORY = 0x10
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_FILE_ATTRIBUTE_TAG_INFO = 9
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
_READ_CHUNK_SIZE = 1024 * 1024


class _AttributeTagInfo(ctypes.Structure):
    _fields_ = [("attributes", ctypes.c_uint32), ("reparse_tag", ctypes.c_uint32)]


def _kernel32():
    if __import__("os").name != "nt":
        raise OSError("Win32 file operations are only available on Windows")
    library = ctypes.WinDLL("kernel32", use_last_error=True)
    library.CreateFileW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    ]
    library.CreateFileW.restype = ctypes.c_void_p
    library.GetFileInformationByHandleEx.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_uint32,
    ]
    library.GetFileInformationByHandleEx.restype = ctypes.c_int
    library.CloseHandle.argtypes = [ctypes.c_void_p]
    library.CloseHandle.restype = ctypes.c_int
    library.GetFileSizeEx.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int64)]
    library.GetFileSizeEx.restype = ctypes.c_int
    library.ReadFile.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    ]
    library.ReadFile.restype = ctypes.c_int
    return library


def _open(path: Path, *, access: int, share: int, flags: int):
    kernel32 = _kernel32()
    handle = kernel32.CreateFileW(str(path), access, share, None, _OPEN_EXISTING, flags, None)
    if handle in (None, _INVALID_HANDLE_VALUE):
        raise ctypes.WinError(ctypes.get_last_error())
    return kernel32, handle


def _attributes(kernel32, handle) -> int:
    info = _AttributeTagInfo()
    if not kernel32.GetFileInformationByHandleEx(
        handle,
        _FILE_ATTRIBUTE_TAG_INFO,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(info.attributes)


@contextmanager
def locked_directory(path: Path) -> Iterator[None]:
    """Open a real directory without following its final reparse point.

    Omitting FILE_SHARE_DELETE keeps the directory name stable while the
    caller creates the sibling asset and performs its final containment check.
    """

    kernel32, handle = _open(
        path,
        access=_FILE_READ_ATTRIBUTES,
        share=_FILE_SHARE_READ | _FILE_SHARE_WRITE,
        flags=_FILE_FLAG_BACKUP_SEMANTICS | _FILE_FLAG_OPEN_REPARSE_POINT,
    )
    try:
        attributes = _attributes(kernel32, handle)
        if not attributes & _FILE_ATTRIBUTE_DIRECTORY:
            raise OSError(f"Not a directory: {path}")
        if attributes & _FILE_ATTRIBUTE_REPARSE_POINT:
            raise OSError(f"Refusing to use a reparse-point directory: {path}")
        yield
    finally:
        kernel32.CloseHandle(handle)


def matches_regular_file(path: Path, expected_size: int, expected_digest: bytes) -> bool:
    """Compare an existing file without following a final symlink/junction."""

    try:
        kernel32, handle = _open(
            path,
            access=_GENERIC_READ,
            share=_FILE_SHARE_READ,
            flags=_FILE_FLAG_OPEN_REPARSE_POINT,
        )
    except OSError:
        return False

    try:
        attributes = _attributes(kernel32, handle)
        if attributes & (_FILE_ATTRIBUTE_DIRECTORY | _FILE_ATTRIBUTE_REPARSE_POINT):
            return False
        size = ctypes.c_int64()
        if not kernel32.GetFileSizeEx(handle, ctypes.byref(size)):
            return False
        if size.value != expected_size:
            return False

        digest = hashlib.sha256()
        buffer = ctypes.create_string_buffer(_READ_CHUNK_SIZE)
        remaining = expected_size
        while remaining:
            requested = min(remaining, _READ_CHUNK_SIZE)
            read = ctypes.c_uint32()
            if (
                not kernel32.ReadFile(handle, buffer, requested, ctypes.byref(read), None)
                or read.value == 0
            ):
                return False
            digest.update(buffer.raw[: read.value])
            remaining -= read.value
        return digest.digest() == expected_digest
    finally:
        kernel32.CloseHandle(handle)

"""Bounded UTF-8 document reads and conflict-aware, atomic saves.

This module owns editor file revisions and encoding preservation. It does not
know about rendering, transports, project discovery, or the desktop UI.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from .engine_errors import EngineError
from .file_io import FILE_WRITE_LOCK, atomic_write_bytes

MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MARKDOWN_DOCUMENT_EXTENSIONS = frozenset({".md", ".markdown"})
TEXT_DOCUMENT_EXTENSIONS = frozenset({".bib", ".json", ".toml", ".txt", ".yaml", ".yml"})


def _document_snapshot(path: Path) -> tuple[bytes, os.stat_result]:
    """Read bounded document bytes and metadata from the same open file."""
    with path.open("rb") as handle:
        stat_result = os.fstat(handle.fileno())
        data = handle.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise EngineError(
            "Document exceeds the editor size limit.",
            code="MARDAS-DOCUMENT-TOO-LARGE",
            details={"size_bytes": len(data), "limit_bytes": MAX_DOCUMENT_BYTES},
        )
    return data, stat_result


def _revision_for_snapshot(data: bytes, stat_result: os.stat_result) -> str:
    digest = hashlib.sha256(data).hexdigest()
    return f"{stat_result.st_mtime_ns}:{len(data)}:{digest}"


def _document_revision(path: Path) -> str:
    return _revision_for_snapshot(*_document_snapshot(path))


def _document_kind_for_path(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix in MARKDOWN_DOCUMENT_EXTENSIONS:
        return "markdown"
    if suffix == ".bib":
        return "bibliography"
    if suffix in {".json", ".toml"}:
        return suffix.removeprefix(".")
    return "text"


def _read_document_text(
    path: str | os.PathLike[str],
    *,
    allowed_extensions: frozenset[str],
    type_message: str,
    document_label: str,
) -> dict[str, Any]:
    requested = Path(path).expanduser()
    try:
        source = requested.resolve(strict=True)
    except (OSError, RuntimeError, UnicodeError) as exc:
        raise EngineError(
            "Document could not be opened.",
            code="MARDAS-DOCUMENT-READ",
            details={"path": str(requested)},
        ) from exc
    if source.suffix.casefold() not in allowed_extensions:
        raise EngineError(
            type_message,
            code="MARDAS-DOCUMENT-TYPE",
            details={"path": str(source)},
        )
    if not source.is_file():
        raise EngineError(
            "Document path must reference a regular file.",
            code="MARDAS-DOCUMENT-READ",
            details={"path": str(source)},
        )
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise EngineError(
            "Document metadata could not be read.",
            code="MARDAS-DOCUMENT-READ",
            details={"path": str(source)},
        ) from exc
    if size > MAX_DOCUMENT_BYTES:
        raise EngineError(
            f"{document_label} exceeds the editor size limit.",
            code="MARDAS-DOCUMENT-TOO-LARGE",
            details={"size_bytes": size, "limit_bytes": MAX_DOCUMENT_BYTES},
        )
    try:
        data, stat_result = _document_snapshot(source)
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise EngineError(
            f"{document_label} must be UTF-8 encoded.",
            code="MARDAS-DOCUMENT-ENCODING",
            details={"path": str(source)},
        ) from exc
    except OSError as exc:
        raise EngineError(
            "Document content could not be read.",
            code="MARDAS-DOCUMENT-READ",
            details={"path": str(source)},
        ) from exc
    revision = _revision_for_snapshot(data, stat_result)
    return {
        "path": str(source),
        "kind": _document_kind_for_path(source),
        "content": content,
        "size_bytes": len(data),
        "revision": revision,
        "read_only": not os.access(source, os.W_OK),
    }


def read_document(path: str | os.PathLike[str]) -> dict[str, Any]:
    return _read_document_text(
        path,
        allowed_extensions=MARKDOWN_DOCUMENT_EXTENSIONS,
        type_message="Only Markdown documents can be opened in the authoring workspace.",
        document_label="Markdown document",
    )


def read_text_document(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Read one supported non-Markdown UTF-8 authoring file."""

    return _read_document_text(
        path,
        allowed_extensions=TEXT_DOCUMENT_EXTENSIONS,
        type_message=(
            "Text documents must use the .txt, .toml, .json, .yaml, .yml, or .bib extension."
        ),
        document_label="Text document",
    )


def _save_document_text(
    path: str | os.PathLike[str],
    content: str,
    *,
    allowed_extensions: frozenset[str],
    extension_message: str,
    document_label: str,
    expected_revision: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    # Serialize the revision check and atomic replacement across service users.
    # External edits are checked again after writing the temporary file.
    with FILE_WRITE_LOCK:
        return _save_document_text_locked(
            path,
            content,
            allowed_extensions=allowed_extensions,
            extension_message=extension_message,
            document_label=document_label,
            expected_revision=expected_revision,
            force=force,
        )


def _save_document_text_locked(
    path: str | os.PathLike[str],
    content: str,
    *,
    allowed_extensions: frozenset[str],
    extension_message: str,
    document_label: str,
    expected_revision: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    target = Path(path).expanduser().resolve(strict=False)
    if target.suffix.casefold() not in allowed_extensions:
        raise EngineError(
            extension_message,
            code="MARDAS-DOCUMENT-TYPE",
            details={"path": str(target)},
        )
    if not isinstance(content, str):
        raise EngineError(
            "content must be a string.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": "content"},
        )
    try:
        payload = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise EngineError(
            f"{document_label} must contain valid UTF-8 text.",
            code="MARDAS-DOCUMENT-ENCODING",
            details={"path": str(target)},
        ) from exc
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise EngineError(
            f"{document_label} exceeds the editor size limit.",
            code="MARDAS-DOCUMENT-TOO-LARGE",
            details={"size_bytes": len(payload), "limit_bytes": MAX_DOCUMENT_BYTES},
        )

    def check_revision() -> None:
        if force or expected_revision is None:
            return
        current_revision = _document_revision(target) if target.is_file() else None
        if expected_revision != current_revision:
            raise EngineError(
                "The document changed on disk after it was opened.",
                code="MARDAS-DOCUMENT-CONFLICT",
                details={
                    "path": str(target),
                    "expected_revision": expected_revision,
                    "current_revision": current_revision,
                },
            )

    try:
        check_revision()
        serialized = content
        existing_data = None
        existing_stat = None
        if target.is_file():
            existing_data, existing_stat = _document_snapshot(target)
            try:
                previous = existing_data.decode("utf-8-sig")
            except UnicodeDecodeError:
                previous = None
            if previous is not None:
                normalized_previous = previous.replace("\r\n", "\n").replace("\r", "\n")
                normalized_content = content.replace("\r\n", "\n").replace("\r", "\n")
                if normalized_content == normalized_previous:
                    check_revision()
                    return {
                        "path": str(target),
                        "kind": _document_kind_for_path(target),
                        "size_bytes": len(existing_data),
                        "revision": _revision_for_snapshot(existing_data, existing_stat),
                        "read_only": not os.access(target, os.W_OK),
                    }
                crlf = "\r\n" in previous
                mixed = "\r" in previous.replace("\r\n", "") or "\n" in previous.replace("\r\n", "")
                serialized = (
                    normalized_content.replace("\n", "\r\n")
                    if crlf and not mixed
                    else normalized_content
                )
                if existing_data.startswith(b"\xef\xbb\xbf"):
                    serialized = "\ufeff" + serialized
        payload = serialized.encode("utf-8")
        if len(payload) > MAX_DOCUMENT_BYTES:
            raise EngineError(
                f"{document_label} exceeds the editor size limit.",
                code="MARDAS-DOCUMENT-TOO-LARGE",
                details={"size_bytes": len(payload), "limit_bytes": MAX_DOCUMENT_BYTES},
            )
        written_stat = atomic_write_bytes(target, payload, before_replace=check_revision)
    except OSError as exc:
        raise EngineError(
            f"Could not save {document_label.lower()}: {exc}",
            code="MARDAS-DOCUMENT-SAVE",
            details={"path": str(target)},
        ) from exc
    return {
        "path": str(target),
        "kind": _document_kind_for_path(target),
        "size_bytes": len(payload),
        "revision": _revision_for_snapshot(payload, written_stat),
        "read_only": not os.access(target, os.W_OK),
    }


def save_document(
    path: str | os.PathLike[str],
    content: str,
    *,
    expected_revision: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    return _save_document_text(
        path,
        content,
        allowed_extensions=MARKDOWN_DOCUMENT_EXTENSIONS,
        extension_message="Markdown documents must use the .md or .markdown extension.",
        document_label="Markdown document",
        expected_revision=expected_revision,
        force=force,
    )


def save_text_document(
    path: str | os.PathLike[str],
    content: str,
    *,
    expected_revision: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Atomically save a supported non-Markdown UTF-8 authoring file."""

    return _save_document_text(
        path,
        content,
        allowed_extensions=TEXT_DOCUMENT_EXTENSIONS,
        extension_message=(
            "Text documents must use the .txt, .toml, .json, .yaml, .yml, or .bib extension."
        ),
        document_label="Text document",
        expected_revision=expected_revision,
        force=force,
    )

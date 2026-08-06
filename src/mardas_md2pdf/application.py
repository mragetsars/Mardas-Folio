from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import fields
from pathlib import Path
from typing import Any, Callable, Mapping

from . import __version__
from .book import (
    BookManifest,
    book_context,
    book_pdf_options,
    convert_book,
    load_book_manifest,
    render_book,
)
from .config import LoadedProjectConfig, load_project_config
from .diagnostics import Diagnostic, has_errors
from .markdown import (
    MarkdownInputError,
    MarkdownRenderResult,
    render_markdown_file,
    render_markdown_text,
)
from .protocol import PROTOCOL_NAME, PROTOCOL_VERSION
from .renderer import PdfOptions, RenderSession, build_html, convert
from .runtime import resolved_chromium_path, runtime_info
from .workspace import (
    ProjectWorkspace,
    WorkspaceError,
    load_workspace,
    read_workspace_file,
    search_workspace,
    workspace_bibliography,
    workspace_payload,
    write_workspace_file,
)

ProgressCallback = Callable[[str, float], None]
CancellationCallback = Callable[[], bool]
ENGINE_API_VERSION = "1.2.0"
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
MAX_IMPORTED_ASSET_BYTES = 64 * 1024 * 1024
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

_OPTION_FIELDS = {
    item.name
    for item in fields(PdfOptions)
    if item.name not in {"input_path", "output_path", "quality_log", "progress", "cancelled"}
}
_PATH_OPTIONS = {
    "debug_html",
    "font_dir",
    "cover_logo",
    "brand_logo",
    "watermark_image",
    "quality_report",
}
_TUPLE_PATH_OPTIONS = {"bibliography_sources"}
_TUPLE_STRING_OPTIONS = {"required_fonts"}
_CONFIG_ALIASES = {
    "no_cover": ("cover", lambda value: not bool(value)),
    "no_cover_logo": ("cover_logo_enabled", lambda value: not bool(value)),
    "watermark": ("watermark_text", lambda value: value),
}


class EngineError(RuntimeError):
    """Stable application-layer error safe to expose through the sidecar."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "MARDAS-ENGINE-ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": self.details}


class EngineValidationError(EngineError):
    def __init__(
        self,
        message: str,
        diagnostics: tuple[Diagnostic, ...] | list[Diagnostic],
        *,
        code: str = "MARDAS-VALIDATION-FAILED",
    ) -> None:
        items = tuple(diagnostics)
        super().__init__(
            message,
            code=code,
            details={"diagnostics": [item.to_dict() for item in items]},
        )
        self.diagnostics = items


def _atomic_write_text(path: Path, text: str) -> None:
    path = Path(path).expanduser().resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = path.stat().st_mode & 0o777 if path.exists() else None
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if existing_mode is not None:
            os.chmod(temporary, existing_mode)
        else:
            current_umask = os.umask(0)
            os.umask(current_umask)
            os.chmod(temporary, 0o666 & ~current_umask)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path = Path(path).expanduser().resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = path.stat().st_mode & 0o777 if path.exists() else None
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if existing_mode is not None:
            os.chmod(temporary, existing_mode)
        else:
            current_umask = os.umask(0)
            os.umask(current_umask)
            os.chmod(temporary, 0o666 & ~current_umask)
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _document_revision(path: Path) -> str:
    stat_result = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{stat_result.st_mtime_ns}:{stat_result.st_size}:{digest}"


def read_document(path: str | os.PathLike[str]) -> dict[str, Any]:
    source = Path(path).expanduser().resolve(strict=True)
    if source.suffix.casefold() not in {".md", ".markdown"}:
        raise EngineError(
            "Only Markdown documents can be opened in the authoring workspace.",
            code="MARDAS-DOCUMENT-TYPE",
            details={"path": str(source)},
        )
    size = source.stat().st_size
    if size > MAX_DOCUMENT_BYTES:
        raise EngineError(
            "Markdown document exceeds the editor size limit.",
            code="MARDAS-DOCUMENT-TOO-LARGE",
            details={"size_bytes": size, "limit_bytes": MAX_DOCUMENT_BYTES},
        )
    try:
        content = source.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise EngineError(
            "Markdown document must be UTF-8 encoded.",
            code="MARDAS-DOCUMENT-ENCODING",
            details={"path": str(source)},
        ) from exc
    return {
        "path": str(source),
        "content": content,
        "size_bytes": size,
        "revision": _document_revision(source),
        "read_only": not os.access(source, os.W_OK),
    }


def save_document(
    path: str | os.PathLike[str],
    content: str,
    *,
    expected_revision: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    target = Path(path).expanduser().resolve(strict=False)
    if target.suffix.casefold() not in {".md", ".markdown"}:
        raise EngineError(
            "Markdown documents must use the .md or .markdown extension.",
            code="MARDAS-DOCUMENT-TYPE",
            details={"path": str(target)},
        )
    if not isinstance(content, str):
        raise EngineError(
            "content must be a string.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": "content"},
        )
    payload = content.encode("utf-8")
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise EngineError(
            "Markdown document exceeds the editor size limit.",
            code="MARDAS-DOCUMENT-TOO-LARGE",
            details={"size_bytes": len(payload), "limit_bytes": MAX_DOCUMENT_BYTES},
        )
    current_revision = _document_revision(target) if target.is_file() else None
    if not force and expected_revision is not None and expected_revision != current_revision:
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
        _atomic_write_text(target, content)
    except OSError as exc:
        raise EngineError(
            f"Could not save Markdown document: {exc}",
            code="MARDAS-DOCUMENT-SAVE",
            details={"path": str(target)},
        ) from exc
    return {
        "path": str(target),
        "size_bytes": target.stat().st_size,
        "revision": _document_revision(target),
        "read_only": not os.access(target, os.W_OK),
    }


def list_document_assets(path: str | os.PathLike[str]) -> dict[str, Any]:
    document = Path(path).expanduser().resolve(strict=False)
    root = document.parent
    assets: list[dict[str, Any]] = []
    if not root.is_dir():
        return {"root": str(root), "assets": assets}
    for candidate in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if len(assets) >= 500:
            break
        if not candidate.is_file() or candidate.is_symlink():
            continue
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            continue
        if len(relative.parts) > 4 or candidate.suffix.casefold() not in _ASSET_EXTENSIONS:
            continue
        stat_result = candidate.stat()
        assets.append(
            {
                "path": str(candidate),
                "relative_path": relative.as_posix(),
                "name": candidate.name,
                "extension": candidate.suffix.casefold(),
                "size_bytes": stat_result.st_size,
            }
        )
    return {"root": str(root), "assets": assets}


def import_document_asset(
    document_path: str | os.PathLike[str], source_path: str | os.PathLike[str]
) -> dict[str, Any]:
    document = Path(document_path).expanduser().resolve(strict=False)
    selected_source = Path(source_path).expanduser()
    if selected_source.is_symlink():
        raise EngineError(
            "Symbolic-link assets are not accepted.",
            code="MARDAS-ASSET-INVALID",
            details={"path": str(selected_source)},
        )
    source = selected_source.resolve(strict=True)
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
    size = source.stat().st_size
    if size > MAX_IMPORTED_ASSET_BYTES:
        raise EngineError(
            "Selected asset exceeds the import size limit.",
            code="MARDAS-ASSET-TOO-LARGE",
            details={"size_bytes": size, "limit_bytes": MAX_IMPORTED_ASSET_BYTES},
        )
    try:
        payload = source.read_bytes()
    except OSError as exc:
        raise EngineError(
            f"Could not read selected asset: {exc}",
            code="MARDAS-ASSET-IMPORT",
            details={"path": str(source)},
        ) from exc

    target_dir = document.parent / "assets"
    if target_dir.is_symlink():
        raise EngineError(
            "The document assets directory must not be a symbolic link.",
            code="MARDAS-ASSET-INVALID",
            details={"path": str(target_dir)},
        )
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = source.stem or "asset"
    suffix = source.suffix.casefold()
    source_digest = hashlib.sha256(payload).digest()
    target = target_dir / f"{stem}{suffix}"
    counter = 2
    while target.exists() or target.is_symlink():
        identical = False
        if target.is_file() and not target.is_symlink() and target.stat().st_size == len(payload):
            identical = hashlib.sha256(target.read_bytes()).digest() == source_digest
        if identical:
            break
        target = target_dir / f"{stem}-{counter}{suffix}"
        counter += 1
    if not target.exists():
        try:
            _atomic_write_bytes(target, payload)
        except OSError as exc:
            raise EngineError(
                f"Could not import asset: {exc}",
                code="MARDAS-ASSET-IMPORT",
                details={"path": str(source)},
            ) from exc
    return {
        "path": str(target),
        "relative_path": target.relative_to(document.parent).as_posix(),
        "name": target.name,
        "extension": suffix,
        "size_bytes": target.stat().st_size,
    }


def _path_value(value: Any, *, base_dir: Path) -> Path | None:
    if value is None or value == "":
        return None
    if not isinstance(value, (str, os.PathLike)):
        raise EngineError(
            "Path option must be a string.",
            code="MARDAS-INVALID-PARAMS",
            details={"value_type": type(value).__name__},
        )
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve(strict=False)


def _config_option_values(config: LoadedProjectConfig) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key, value in config.values.items():
        if key.startswith("book_"):
            continue
        alias = _CONFIG_ALIASES.get(key)
        if alias is not None:
            target, transform = alias
            values[target] = transform(value)
            continue
        if key in _OPTION_FIELDS:
            values[key] = value
    if values.get("brand_logo") is not None:
        values.setdefault("cover_logo", values["brand_logo"])
    return values


def _normalize_option_values(values: Mapping[str, Any], *, base_dir: Path) -> dict[str, Any]:
    unknown = sorted(set(values) - _OPTION_FIELDS)
    if unknown:
        raise EngineError(
            "Unsupported render options were supplied.",
            code="MARDAS-INVALID-PARAMS",
            details={"unknown_options": unknown},
        )
    normalized: dict[str, Any] = {}
    for key, value in values.items():
        if key in _PATH_OPTIONS:
            normalized[key] = _path_value(value, base_dir=base_dir)
        elif key == "chromium_path":
            path = _path_value(value, base_dir=base_dir)
            normalized[key] = str(path) if path is not None else None
        elif key in _TUPLE_PATH_OPTIONS:
            if value is None:
                normalized[key] = ()
            elif isinstance(value, (list, tuple)):
                normalized[key] = tuple(
                    item
                    for item in (
                        _path_value(entry, base_dir=base_dir) for entry in value
                    )
                    if item is not None
                )
            else:
                raise EngineError(
                    f"{key} must be an array of paths.",
                    code="MARDAS-INVALID-PARAMS",
                )
        elif key in _TUPLE_STRING_OPTIONS:
            if value is None:
                normalized[key] = ()
            elif isinstance(value, (list, tuple)):
                normalized[key] = tuple(str(entry).strip() for entry in value if str(entry).strip())
            else:
                raise EngineError(
                    f"{key} must be an array of strings.",
                    code="MARDAS-INVALID-PARAMS",
                )
        else:
            normalized[key] = value
    return normalized


def _load_document_config(
    input_path: Path,
    *,
    config_path: Path | None,
    discover_config: bool,
) -> LoadedProjectConfig:
    loaded = load_project_config(
        start=input_path,
        explicit_path=config_path,
        disabled=not discover_config and config_path is None,
    )
    if has_errors(loaded.diagnostics):
        raise EngineValidationError("Project configuration is invalid.", loaded.diagnostics)
    return loaded.config


def pdf_options_from_request(
    *,
    input_path: str | os.PathLike[str],
    output_path: str | os.PathLike[str] | None = None,
    config_path: str | os.PathLike[str] | None = None,
    discover_config: bool = True,
    options: Mapping[str, Any] | None = None,
    progress: ProgressCallback | None = None,
    cancelled: CancellationCallback | None = None,
) -> PdfOptions:
    """Create ``PdfOptions`` from a stable desktop/sidecar request contract."""

    source = Path(input_path).expanduser().resolve(strict=False)
    explicit_config = (
        Path(config_path).expanduser().resolve(strict=False) if config_path is not None else None
    )
    config = _load_document_config(
        source,
        config_path=explicit_config,
        discover_config=bool(discover_config),
    )
    base_dir = config.root if config.discovered else source.parent
    target = (
        _path_value(output_path, base_dir=base_dir)
        if output_path
        else source.with_suffix(".pdf")
    )
    assert target is not None

    merged = _config_option_values(config)
    merged.update(dict(options or {}))
    normalized = _normalize_option_values(merged, base_dir=base_dir)
    if not normalized.get("chromium_path"):
        chromium = resolved_chromium_path()
        if chromium is not None:
            normalized["chromium_path"] = str(chromium)
    return PdfOptions(
        input_path=source,
        output_path=target,
        progress=progress,
        cancelled=cancelled,
        **normalized,
    )


def render_document(options: PdfOptions, *, session: RenderSession | None = None) -> dict[str, Any]:
    """Render one document through the common application API used by CLI/sidecar."""

    output = convert(options, session=session)
    result: dict[str, Any] = {
        "output_path": str(output),
        "size_bytes": output.stat().st_size,
        "quality": options.quality_log.payload(),
    }
    if options.debug_html is not None and Path(options.debug_html).is_file():
        result["debug_html"] = str(options.debug_html)
    if options.quality_report is not None and Path(options.quality_report).is_file():
        result["quality_report"] = str(options.quality_report)
    return result


def _render_markdown_for_options(options: PdfOptions) -> MarkdownRenderResult:
    result = render_markdown_file(
        options.input_path,
        toc=options.toc,
        toc_depth=options.toc_depth,
        appearance_style=options.style,
        appearance_mode=options.mode,
        language=options.document_language,
        unsafe_html=options.unsafe_html,
        allow_remote_images=options.allow_remote_assets,
        references_enabled=options.references_enabled,
        numbering_scope=options.numbering_scope,
        list_of_figures=options.list_of_figures,
        list_of_tables=options.list_of_tables,
        list_of_equations=options.list_of_equations,
        list_of_listings=options.list_of_listings,
        citations_enabled=options.citations_enabled,
        bibliography_sources=(options.bibliography_sources or None),
        citation_style=options.citation_style,
        bibliography_title=options.bibliography_title,
        bibliography_include_uncited=options.bibliography_include_uncited,
    )
    return result


def _render_markdown_text_for_options(options: PdfOptions, content: str) -> MarkdownRenderResult:
    if not isinstance(content, str):
        raise EngineError(
            "content must be a string.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": "content"},
        )
    return render_markdown_text(
        content,
        source_path=options.input_path,
        toc=options.toc,
        toc_depth=options.toc_depth,
        appearance_style=options.style,
        appearance_mode=options.mode,
        language=options.document_language,
        unsafe_html=options.unsafe_html,
        allow_remote_images=options.allow_remote_assets,
        references_enabled=options.references_enabled,
        numbering_scope=options.numbering_scope,
        list_of_figures=options.list_of_figures,
        list_of_tables=options.list_of_tables,
        list_of_equations=options.list_of_equations,
        list_of_listings=options.list_of_listings,
        citations_enabled=options.citations_enabled,
        bibliography_sources=(options.bibliography_sources or None),
        citation_style=options.citation_style,
        bibliography_title=options.bibliography_title,
        bibliography_include_uncited=options.bibliography_include_uncited,
    )


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _document_summary(result: MarkdownRenderResult) -> dict[str, Any]:
    return {
        "title": result.title,
        "headings": len(result.toc_entries),
        "metadata_keys": sorted(result.metadata),
        "numbered_objects": len(result.reference_objects),
        "cited_entries": len(result.cited_keys),
        "outline": [
            {"level": level, "title": title, "id": heading_id, "number": number}
            for level, title, heading_id, number in result.toc_entries
        ],
        "metadata": _json_safe(result.metadata),
        "citation_entries": _json_safe(result.citation_entries),
        "cited_keys": list(result.cited_keys),
        "source_map": [dict(item) for item in result.source_map],
    }


def validate_document(options: PdfOptions) -> dict[str, Any]:
    try:
        result = _render_markdown_for_options(options)
    except (MarkdownInputError, OSError, UnicodeError, ValueError) as exc:
        diagnostic = Diagnostic(
            "MARDAS-E203",
            "error",
            str(exc),
            path=options.input_path,
        )
        return {"ok": False, "diagnostics": [diagnostic.to_dict()]}
    diagnostics = tuple(result.diagnostics)
    return {
        "ok": not has_errors(diagnostics),
        "diagnostics": [item.to_dict() for item in diagnostics],
        "document": _document_summary(result),
    }


def validate_document_text(options: PdfOptions, content: str) -> dict[str, Any]:
    """Validate an unsaved editor buffer against its intended source path."""

    try:
        result = _render_markdown_text_for_options(options, content)
    except (MarkdownInputError, OSError, UnicodeError, ValueError) as exc:
        diagnostic = Diagnostic(
            "MARDAS-E203",
            "error",
            str(exc),
            path=options.input_path,
        )
        return {"ok": False, "diagnostics": [diagnostic.to_dict()]}
    diagnostics = tuple(result.diagnostics)
    return {
        "ok": not has_errors(diagnostics),
        "diagnostics": [item.to_dict() for item in diagnostics],
        "document": _document_summary(result),
    }


def preview_document_text(options: PdfOptions, content: str) -> dict[str, Any]:
    """Return a safe in-memory authoring preview for a dirty editor buffer."""

    result = _render_markdown_text_for_options(options, content)
    if has_errors(result.diagnostics):
        raise EngineValidationError("Document validation failed.", result.diagnostics)
    return {
        "title": result.title,
        "body_html": result.body_html,
        "toc_html": result.toc_html,
        "reference_lists_html": result.reference_lists_html,
        "bibliography_html": result.bibliography_html,
        "pygments_css": result.pygments_css,
        "diagnostics": [item.to_dict() for item in result.diagnostics],
        "source_map": [dict(item) for item in result.source_map],
        "document": _document_summary(result),
    }


def preview_document(options: PdfOptions, *, output_path: Path) -> dict[str, Any]:
    result = _render_markdown_for_options(options)
    if has_errors(result.diagnostics):
        raise EngineValidationError("Document validation failed.", result.diagnostics)
    html_text = build_html(
        result,
        options,
        include_cover=True,
        include_content=True,
        include_watermark=True,
    )
    _atomic_write_text(output_path, html_text)
    return {
        "output_path": str(output_path),
        "size_bytes": output_path.stat().st_size,
        "title": result.title,
        "headings": len(result.toc_entries),
    }


def _load_book(config_path: Path) -> tuple[BookManifest, tuple[Diagnostic, ...]]:
    loaded = load_project_config(start=config_path, explicit_path=config_path)
    diagnostics = list(loaded.diagnostics)
    manifest: BookManifest | None = None
    if not has_errors(diagnostics):
        manifest, manifest_diagnostics = load_book_manifest(loaded.config)
        diagnostics.extend(manifest_diagnostics)
    if manifest is None or has_errors(diagnostics):
        raise EngineValidationError("Book project configuration is invalid.", diagnostics)
    return manifest, tuple(diagnostics)


def validate_book(
    config_path: Path,
    *,
    cancelled: CancellationCallback | None = None,
) -> dict[str, Any]:
    manifest, diagnostics = _load_book(config_path)
    bundle, render_diagnostics = render_book(manifest, cancelled=cancelled)
    diagnostics = diagnostics + render_diagnostics
    context = book_context(manifest, bundle)
    return {
        "ok": bundle is not None and not has_errors(diagnostics),
        "diagnostics": [item.to_dict() for item in diagnostics],
        "book": context,
    }


def render_book_project(
    config_path: Path,
    *,
    output_path: Path | None = None,
    debug_html: Path | None = None,
    progress: ProgressCallback | None = None,
    cancelled: CancellationCallback | None = None,
    session: RenderSession | None = None,
) -> dict[str, Any]:
    manifest, diagnostics = _load_book(config_path)
    output, bundle, render_diagnostics = convert_book(
        manifest,
        output_path=output_path,
        debug_html=debug_html,
        progress=progress,
        cancelled=cancelled,
        session=session,
    )
    diagnostics = diagnostics + render_diagnostics
    if output is None or has_errors(diagnostics):
        raise EngineValidationError("Book rendering failed.", diagnostics)
    result: dict[str, Any] = {
        "output_path": str(output),
        "size_bytes": output.stat().st_size,
        "diagnostics": [item.to_dict() for item in diagnostics],
        "book": book_context(manifest, bundle),
    }
    quality_path = manifest.config.values.get("quality_report")
    if quality_path is not None and Path(quality_path).is_file():
        result["quality_report"] = str(quality_path)
        try:
            result["quality"] = json.loads(Path(quality_path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
    return result


def _validate_params(params: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise EngineError(
            "Unsupported request parameters were supplied.",
            code="MARDAS-INVALID-PARAMS",
            details={"unknown_parameters": unknown},
        )


def _optional_bool(params: Mapping[str, Any], key: str, *, default: bool) -> bool:
    value = params.get(key, default)
    if not isinstance(value, bool):
        raise EngineError(
            f"{key} must be true or false.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": key},
        )
    return value


class EngineService:
    """Long-lived, thread-affine application service for desktop sidecars."""

    def __init__(self) -> None:
        self._session: RenderSession | None = None

    def _render_session(self) -> RenderSession:
        if self._session is None:
            self._session = RenderSession()
        return self._session

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    def health(self) -> dict[str, Any]:
        info = runtime_info()
        resolved_browser = resolved_chromium_path()
        runtime_payload = info.to_dict()
        runtime_payload["resolved_chromium_path"] = (
            str(resolved_browser) if resolved_browser else None
        )
        return {
            "status": "ok",
            "engine_version": __version__,
            "engine_api_version": ENGINE_API_VERSION,
            "protocol": PROTOCOL_NAME,
            "protocol_version": PROTOCOL_VERSION,
            "runtime": runtime_payload,
            "chromium_available": bool(resolved_browser),
        }

    def capabilities(self) -> dict[str, Any]:
        return {
            "engine_version": __version__,
            "engine_api_version": ENGINE_API_VERSION,
            "protocol": PROTOCOL_NAME,
            "protocol_version": PROTOCOL_VERSION,
            "methods": [
                "system.health",
                "system.capabilities",
                "system.shutdown",
                "job.cancel",
                "document.read",
                "document.save",
                "document.list_assets",
                "document.import_asset",
                "project.open",
                "project.refresh",
                "project.read",
                "project.save",
                "project.search",
                "bibliography.index",
                "render.document",
                "render.book",
                "preview.document",
                "preview.document_text",
                "validate.document",
                "validate.document_text",
                "validate.book",
            ],
            "render_options": sorted(_OPTION_FIELDS),
            "quality_profiles": ["standard", "strict-publication"],
            "error_policies": ["error", "warn", "ignore"],
            "concurrency": {"render_jobs": 1, "cancellation": True},
        }

    def dispatch(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        progress: ProgressCallback | None = None,
        cancelled: CancellationCallback | None = None,
    ) -> dict[str, Any]:
        if method == "document.read":
            _validate_params(params, {"path"})
            return read_document(_required_string(params, "path"))
        if method == "document.save":
            _validate_params(params, {"path", "content", "expected_revision", "force"})
            force = _optional_bool(params, "force", default=False)
            expected_revision = _optional_string(params, "expected_revision")
            return save_document(
                _required_string(params, "path"),
                _required_content(params),
                expected_revision=expected_revision,
                force=force,
            )
        if method == "document.list_assets":
            _validate_params(params, {"path"})
            return list_document_assets(_required_string(params, "path"))
        if method == "document.import_asset":
            _validate_params(params, {"document_path", "source_path"})
            return import_document_asset(
                _required_string(params, "document_path"),
                _required_string(params, "source_path"),
            )
        if method in {"project.open", "project.refresh"}:
            _validate_params(params, {"path"})
            workspace = _load_workspace_request(
                _required_string(params, "path"),
                cancelled=cancelled,
            )
            payload = workspace_payload(workspace)
            payload["path"] = str(workspace.root)
            return payload
        if method == "project.read":
            _validate_params(params, {"project_path", "relative_path"})
            workspace = _load_workspace_request(
                _required_string(params, "project_path"),
                cancelled=cancelled,
            )
            relative_path = _required_string(params, "relative_path")
            payload = _workspace_call(
                lambda: read_workspace_file(workspace, relative_path)
            )
            absolute_path = (workspace.root / relative_path).resolve(strict=False)
            payload["absolute_path"] = str(absolute_path)
            payload["revision"] = _document_revision(absolute_path)
            payload["read_only"] = not os.access(absolute_path, os.W_OK)
            return payload
        if method == "project.save":
            _validate_params(
                params,
                {"project_path", "relative_path", "content", "expected_sha256"},
            )
            workspace = _load_workspace_request(
                _required_string(params, "project_path"),
                cancelled=cancelled,
            )
            relative_path = _required_string(params, "relative_path")
            payload = _workspace_call(
                lambda: write_workspace_file(
                    workspace,
                    relative_path,
                    _required_content(params),
                    expected_sha256=_required_string(params, "expected_sha256"),
                )
            )
            payload["absolute_path"] = str(
                (workspace.root / relative_path).resolve(strict=False)
            )
            return payload
        if method == "project.search":
            _validate_params(
                params,
                {
                    "project_path",
                    "query",
                    "regex",
                    "case_sensitive",
                    "max_results",
                },
            )
            workspace = _load_workspace_request(
                _required_string(params, "project_path"),
                cancelled=cancelled,
            )
            return _workspace_call(
                lambda: search_workspace(
                    workspace,
                    _required_string(params, "query"),
                    regex=_optional_bool(params, "regex", default=False),
                    case_sensitive=_optional_bool(
                        params, "case_sensitive", default=False
                    ),
                    max_results=_optional_int(
                        params, "max_results", default=200, minimum=1, maximum=500
                    ),
                    cancelled=cancelled,
                )
            )
        if method == "bibliography.index":
            _validate_params(
                params,
                {"project_path", "query", "cited_keys", "max_results"},
            )
            workspace = _load_workspace_request(
                _required_string(params, "project_path"),
                cancelled=cancelled,
            )
            cited_keys = _string_list(params.get("cited_keys", ()), "cited_keys")
            return _workspace_call(
                lambda: workspace_bibliography(
                    workspace,
                    query=_optional_string(params, "query") or "",
                    cited_keys=cited_keys,
                    max_results=_optional_int(
                        params,
                        "max_results",
                        default=500,
                        minimum=1,
                        maximum=10_000,
                    ),
                )
            )
        if method == "render.document":
            _validate_params(
                params,
                {"input_path", "output_path", "config_path", "discover_config", "options"},
            )
            options = pdf_options_from_request(
                input_path=_required_string(params, "input_path"),
                output_path=_optional_string(params, "output_path"),
                config_path=_optional_string(params, "config_path"),
                discover_config=_optional_bool(params, "discover_config", default=True),
                options=_mapping(params.get("options", {}), "options"),
                progress=progress,
                cancelled=cancelled,
            )
            return render_document(options, session=self._render_session())
        if method == "validate.document":
            _validate_params(
                params,
                {"input_path", "output_path", "config_path", "discover_config", "options"},
            )
            options = pdf_options_from_request(
                input_path=_required_string(params, "input_path"),
                output_path=_optional_string(params, "output_path"),
                config_path=_optional_string(params, "config_path"),
                discover_config=_optional_bool(params, "discover_config", default=True),
                options=_mapping(params.get("options", {}), "options"),
                cancelled=cancelled,
            )
            return validate_document(options)
        if method in {"validate.document_text", "preview.document_text"}:
            _validate_params(
                params,
                {"input_path", "content", "config_path", "discover_config", "options"},
            )
            options = pdf_options_from_request(
                input_path=_required_string(params, "input_path"),
                config_path=_optional_string(params, "config_path"),
                discover_config=_optional_bool(params, "discover_config", default=True),
                options=_mapping(params.get("options", {}), "options"),
                cancelled=cancelled,
            )
            content = _required_content(params)
            if method == "validate.document_text":
                return validate_document_text(options, content)
            return preview_document_text(options, content)
        if method == "preview.document":
            _validate_params(
                params,
                {"input_path", "output_path", "config_path", "discover_config", "options"},
            )
            source = _required_string(params, "input_path")
            preview_path = _required_string(params, "output_path")
            options = pdf_options_from_request(
                input_path=source,
                output_path=str(Path(preview_path).with_suffix(".pdf")),
                config_path=_optional_string(params, "config_path"),
                discover_config=_optional_bool(params, "discover_config", default=True),
                options=_mapping(params.get("options", {}), "options"),
                cancelled=cancelled,
            )
            target = Path(preview_path).expanduser().resolve(strict=False)
            return preview_document(options, output_path=target)
        if method in {"render.book", "validate.book"}:
            allowed = {"config_path"} if method == "validate.book" else {
                "config_path", "output_path", "debug_html"
            }
            _validate_params(params, allowed)
            config_path = Path(_required_string(params, "config_path")).expanduser().resolve()
            if method == "validate.book":
                return validate_book(config_path, cancelled=cancelled)
            output_value = _optional_string(params, "output_path")
            debug_value = _optional_string(params, "debug_html")
            base_dir = config_path.parent
            return render_book_project(
                config_path,
                output_path=(
                    _path_value(output_value, base_dir=base_dir) if output_value else None
                ),
                debug_html=(
                    _path_value(debug_value, base_dir=base_dir) if debug_value else None
                ),
                progress=progress,
                cancelled=cancelled,
                session=self._render_session(),
            )
        raise EngineError(
            f"Unsupported application method: {method}",
            code="MARDAS-METHOD-NOT-FOUND",
            details={"method": method},
        )


def _workspace_error(exc: WorkspaceError) -> EngineError:
    return EngineError(
        str(exc),
        code=f"MARDAS-{exc.code.replace('_', '-').upper()}",
        details={
            "status": exc.status,
            "diagnostics": [item.to_dict() for item in exc.diagnostics],
        },
    )


def _workspace_call(callback: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return callback()
    except WorkspaceError as exc:
        raise _workspace_error(exc) from exc


def _load_workspace_request(
    path: str,
    *,
    cancelled: CancellationCallback | None = None,
) -> ProjectWorkspace:
    try:
        return load_workspace(Path(path), cancelled=cancelled)
    except WorkspaceError as exc:
        raise _workspace_error(exc) from exc


def _optional_int(
    params: Mapping[str, Any],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = params.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise EngineError(
            f"{key} must be an integer.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": key},
        )
    if value < minimum or value > maximum:
        raise EngineError(
            f"{key} must be between {minimum} and {maximum}.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": key, "minimum": minimum, "maximum": maximum},
        )
    return value


def _string_list(value: Any, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise EngineError(
            f"{key} must be an array of strings.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": key},
        )
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise EngineError(
                f"{key} must contain only non-empty strings.",
                code="MARDAS-INVALID-PARAMS",
                details={"parameter": key},
            )
        result.append(item.strip())
    return tuple(result)


def _required_string(params: Mapping[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EngineError(
            f"{key} must be a non-empty string.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": key},
        )
    return value.strip()


def _required_content(params: Mapping[str, Any]) -> str:
    value = params.get("content")
    if not isinstance(value, str):
        raise EngineError(
            "content must be a string.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": "content"},
        )
    return value


def _optional_string(params: Mapping[str, Any], key: str) -> str | None:
    value = params.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise EngineError(
            f"{key} must be a non-empty string when supplied.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": key},
        )
    return value.strip()


def _mapping(value: Any, key: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EngineError(
            f"{key} must be an object.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": key},
        )
    return value

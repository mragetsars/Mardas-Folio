from __future__ import annotations

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
from .markdown import MarkdownInputError, MarkdownRenderResult, render_markdown_file
from .protocol import PROTOCOL_NAME, PROTOCOL_VERSION
from .renderer import PdfOptions, RenderSession, build_html, convert
from .runtime import resolved_chromium_path, runtime_info

ProgressCallback = Callable[[str, float], None]
CancellationCallback = Callable[[], bool]
ENGINE_API_VERSION = "1.0.0"

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
        "document": {
            "title": result.title,
            "headings": len(result.toc_entries),
            "metadata_keys": sorted(result.metadata),
            "numbered_objects": len(result.reference_objects),
            "cited_entries": len(result.cited_keys),
        },
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
                "render.document",
                "render.book",
                "preview.document",
                "validate.document",
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


def _required_string(params: Mapping[str, Any], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EngineError(
            f"{key} must be a non-empty string.",
            code="MARDAS-INVALID-PARAMS",
            details={"parameter": key},
        )
    return value.strip()


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

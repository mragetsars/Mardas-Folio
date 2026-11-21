"""Resolve project defaults and validate per-request publication options."""

from __future__ import annotations

import os
from dataclasses import fields
from pathlib import Path
from typing import Any, Callable, Mapping

from .config import RENDER_OPTION_SPECS, ConfigValueError, LoadedProjectConfig, load_project_config
from .diagnostics import has_errors
from .engine_errors import EngineError, EngineValidationError
from .render_contracts import BODY_TYPOGRAPHY_FIELDS, PdfOptions

ProgressCallback = Callable[[str, float], None]
CancellationCallback = Callable[[], bool]

OPTION_FIELDS = {
    item.name
    for item in fields(PdfOptions)
    if item.name
    not in {
        "input_path",
        "output_path",
        "quality_log",
        "progress",
        "cancelled",
        "protected_inputs",
        "project_typography",
        "output_create_only",
    }
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

_OPTION_SPEC_FIELDS = frozenset(RENDER_OPTION_SPECS)
if _OPTION_SPEC_FIELDS != OPTION_FIELDS:
    missing = sorted(OPTION_FIELDS - _OPTION_SPEC_FIELDS)
    extra = sorted(_OPTION_SPEC_FIELDS - OPTION_FIELDS)
    raise RuntimeError(
        "Render option validation schema is out of sync with PdfOptions "
        f"(missing={missing}, extra={extra})."
    )


def path_value(value: Any, *, base_dir: Path) -> Path | None:
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
        if key in OPTION_FIELDS:
            values[key] = value
    if values.get("brand_logo") is not None:
        values.setdefault("cover_logo", values["brand_logo"])
    return values


def _validate_option_values(values: Mapping[str, Any]) -> dict[str, Any]:
    """Validate untrusted per-request overrides before path normalization."""

    unknown = sorted(set(values) - OPTION_FIELDS)
    if unknown:
        raise EngineError(
            "Unsupported render options were supplied.",
            code="MARDAS-INVALID-PARAMS",
            details={"unknown_options": unknown},
        )

    validated: dict[str, Any] = {}
    for option, value in values.items():
        spec = RENDER_OPTION_SPECS[option]
        if value is None:
            if spec.nullable:
                validated[option] = None
                continue
            raise EngineError(
                f"Render option '{option}' cannot be null.",
                code="MARDAS-INVALID-PARAMS",
                details={"option": option, "reason": "value cannot be null"},
            )
        try:
            validated[option] = spec.validator(value)
        except ConfigValueError as exc:
            raise EngineError(
                f"Invalid render option '{option}': {exc}.",
                code="MARDAS-INVALID-PARAMS",
                details={"option": option, "reason": str(exc)},
            ) from exc
    return validated


def _normalize_option_values(values: Mapping[str, Any], *, base_dir: Path) -> dict[str, Any]:
    unknown = sorted(set(values) - OPTION_FIELDS)
    if unknown:
        raise EngineError(
            "Unsupported render options were supplied.",
            code="MARDAS-INVALID-PARAMS",
            details={"unknown_options": unknown},
        )
    normalized: dict[str, Any] = {}
    for key, value in values.items():
        if key in _PATH_OPTIONS:
            normalized[key] = path_value(value, base_dir=base_dir)
        elif key == "chromium_path":
            path = path_value(value, base_dir=base_dir)
            normalized[key] = str(path) if path is not None else None
        elif key in _TUPLE_PATH_OPTIONS:
            if value is None:
                normalized[key] = ()
            elif isinstance(value, (list, tuple)):
                normalized[key] = tuple(
                    item
                    for item in (path_value(entry, base_dir=base_dir) for entry in value)
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
                normalized[key] = tuple(value)
            else:
                raise EngineError(
                    f"{key} must be an array of strings.",
                    code="MARDAS-INVALID-PARAMS",
                    details={"option": key},
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
        path_value(output_path, base_dir=base_dir) if output_path else source.with_suffix(".pdf")
    )
    assert target is not None

    merged = _config_option_values(config)
    requested = _validate_option_values(dict(options or {}))
    project_typography = frozenset(
        key for key in BODY_TYPOGRAPHY_FIELDS if key in merged and key not in requested
    )
    merged.update(requested)
    normalized = _normalize_option_values(merged, base_dir=base_dir)
    return PdfOptions(
        input_path=source,
        output_path=target,
        progress=progress,
        cancelled=cancelled,
        project_typography=project_typography,
        protected_inputs=(("project configuration", config.path),)
        if config.path is not None
        else (),
        **normalized,
    )

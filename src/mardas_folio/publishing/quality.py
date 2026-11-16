"""Publication quality policy, diagnostics, and cancellation checks."""
from __future__ import annotations
import hashlib
from pathlib import Path
from typing import Any
from ..quality import RenderQualityError, handle_quality_issue, profile_policy, validate_quality_profile
from ..render_contracts import PdfOptions, RenderCancelledError


def _check_cancel(options: "PdfOptions") -> None:
    callback = options.cancelled
    if callback is not None and callback():
        raise RenderCancelledError("PDF rendering was cancelled.")


def _resolve_quality_options(options: PdfOptions) -> None:
    profile = validate_quality_profile(options.quality_profile)
    options.quality_profile = profile
    options.math_error_policy = profile_policy(profile, options.math_error_policy)
    options.font_error_policy = profile_policy(profile, options.font_error_policy)
    options.navigation_error_policy = profile_policy(profile, options.navigation_error_policy)
    required = tuple(dict.fromkeys(name.strip() for name in options.required_fonts if name.strip()))
    if profile == "strict-publication" and not required:
        required = ("Vazirmatn",)
    options.required_fonts = required
    options.quality_log.profile = profile


def _write_quality_report(options: PdfOptions) -> None:
    if options.quality_report is not None:
        options.quality_log.write(Path(options.quality_report))


def _enforce_quality_issue(
    options: PdfOptions,
    *,
    category: str,
    policy: str,
    message: str,
    details: dict[str, Any] | None = None,
    error_type: type[RenderQualityError] = RenderQualityError,
) -> None:
    try:
        handle_quality_issue(
            options.quality_log,
            category=category,
            policy=policy,
            message=message,
            details=details,
            error_type=error_type,
        )
    finally:
        _write_quality_report(options)


def _font_directory_manifest(font_dir: Path | None) -> list[dict[str, Any]]:
    if not font_dir or not Path(font_dir).is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(Path(font_dir).iterdir(), key=lambda item: item.name.casefold()):
        if not path.is_file() or path.suffix.lower() not in {".ttf", ".otf", ".woff", ".woff2"}:
            continue
        records.append(
            {
                "name": path.name,
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return records

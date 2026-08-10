from __future__ import annotations

import argparse
import base64
import binascii
from collections import Counter
import hashlib
import ipaddress
import json
import logging
import re
import secrets
import socket
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urlsplit

from . import __version__
from .brand_assets import asset_content_type, gui_brand_asset_filename, packaged_asset_path
from .appearance import (
    code_style_for_appearance,
    validate_mode_name,
    validate_palette_name,
    validate_style_name,
)
from .markdown import MarkdownInputError, render_markdown_file
from .renderer import (
    DocumentAssetError,
    NAMED_PAGE_DIMENSIONS,
    PdfOptions,
    RenderCancelledError,
    RenderSession,
    build_html,
    convert,
    validate_branding_mode,
    validate_page_size,
)
from .render_pool import RenderQueueFullError
from .quality import validate_error_policy, validate_quality_profile
from .studio_jobs import StudioExportJob, StudioExportJobError, StudioExportManager

from .workspace import (
    ProjectWorkspace,
    WorkspaceError,
    export_workspace_book_pdf,
    load_workspace,
    read_workspace_file,
    refresh_workspace,
    render_workspace_book_html,
    render_workspace_file_html,
    workspace_diagnostics_payload,
    workspace_payload,
    write_workspace_file,
)

LOGGER = logging.getLogger(__name__)


MAX_GUI_REQUEST_BYTES = 32 * 1024 * 1024
STUDIO_REQUEST_BODY_TIMEOUT_SECONDS = 15.0
MAX_GUI_MARKDOWN_BYTES = 4 * 1024 * 1024
MAX_GUI_ASSETS = 250
MAX_GUI_ASSET_BYTES = 12 * 1024 * 1024
MAX_GUI_TOTAL_ASSET_BYTES = 32 * 1024 * 1024
MAX_GUI_FILENAME_CHARS = 120
MAX_GUI_ASSET_PATH_PART_CHARS = 180
MAX_STUDIO_CONCURRENT_EXPORTS = 2
DEFAULT_STUDIO_EXPORT_QUEUE_SIZE = 6
DEFAULT_STUDIO_RENDER_IDLE_TIMEOUT = 60.0
MAX_STUDIO_EXPORT_RESULT_BYTES = 512 * 1024 * 1024
MAX_STUDIO_PREVIEW_CLIENTS = 256
WILDCARD_BIND_HOSTS = {str(ipaddress.ip_address(0)), "::"}
# This is an HTTP header name, not a credential.
STUDIO_TOKEN_HEADER = "X-Mardas-Studio-Token"  # nosec B105
STUDIO_PREVIEW_REQUEST_HEADER = "X-Mardas-Studio-Preview-Id"
STUDIO_PREVIEW_CLIENT_HEADER = "X-Mardas-Studio-Client-Id"
STUDIO_PREVIEW_REQUEST_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")
STUDIO_PREVIEW_CLIENT_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,96}$")
STUDIO_EXPORT_JOB_RE = re.compile(r"^[A-Za-z0-9]{12,64}$")
STUDIO_EXPORT_MANAGER_INIT_LOCK = threading.Lock()

STUDIO_PREVIEW_NAMED_PAGE_SIZES = NAMED_PAGE_DIMENSIONS
STUDIO_PREVIEW_PAGE_NAME_RE = re.compile(
    r"^(?P<name>[A-Za-z][A-Za-z0-9-]*)(?:\s+(?P<orientation>portrait|landscape))?$",
    re.IGNORECASE,
)
STUDIO_PREVIEW_DIMENSIONS_RE = re.compile(
    r"^(?P<width>\d+(?:\.\d+)?(?:mm|cm|in|px|pt))\s+"
    r"(?P<height>\d+(?:\.\d+)?(?:mm|cm|in|px|pt))$",
    re.IGNORECASE,
)


class StudioRequestError(ValueError):
    """Client-facing Studio request error with a stable JSON error code."""

    def __init__(self, message: str, *, status: int = 400, code: str = "bad_request") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class IPv6ThreadingHTTPServer(ThreadingHTTPServer):
    """Threading HTTP server that binds IPv6 literals such as ``::1``."""

    address_family = socket.AF_INET6


def _create_studio_server(host: str, port: int) -> ThreadingHTTPServer:
    normalized = (host or "").strip().strip("[]")
    server_class = IPv6ThreadingHTTPServer if ":" in normalized else ThreadingHTTPServer
    return server_class((normalized, port), GuiRequestHandler)


def _studio_url(host: str, port: int) -> str:
    normalized = (host or "127.0.0.1").strip().strip("[]")
    display_host = f"[{normalized}]" if ":" in normalized else normalized
    return f"http://{display_host}:{port}/"


def _format_bytes(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.0f} MB"
    if size >= 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size} bytes"


def _error_payload(message: str, *, status: int, code: str) -> dict[str, Any]:
    return {"error": message, "status": status, "code": code}


def _decode_json_payload(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StudioRequestError(
            "Render request body must be UTF-8 encoded.", code="invalid_encoding"
        ) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StudioRequestError(
            f"Render request body must be valid JSON: {exc.msg}.", code="invalid_json"
        ) from exc
    if not isinstance(payload, dict):
        raise StudioRequestError("Render payload must be a JSON object.", code="invalid_payload")
    return payload


def _is_local_bind_host(host: str) -> bool:
    normalized = (host or "").strip().lower().strip("[]")
    return normalized in {"", "localhost", "127.0.0.1", "::1"} or normalized.startswith("127.")


def _studio_bind_warning(host: str) -> str | None:
    if _is_local_bind_host(host):
        return None
    return (
        "Studio is binding to a non-local host. Only use this on trusted networks, "
        "because anyone who can reach the server can submit Markdown and attached assets."
    )


def _header_host_name(value: str | None) -> str:
    """Extract and normalize the host name from an HTTP Host header."""
    raw = (value or "").strip()
    if not raw:
        return ""
    if raw.startswith("["):
        end = raw.find("]")
        return raw[1:end].lower() if end > 0 else raw.strip("[]").lower()
    return raw.rsplit(":", 1)[0].lower()


def _host_header_is_trusted(host_header: str | None, bind_host: str | None) -> bool:
    """Return whether a request Host header is acceptable for the Studio bind mode."""
    host = _header_host_name(host_header)
    if not host:
        return False
    if _is_local_bind_host(host):
        return True

    # The default local bind must never accept DNS-rebound or LAN Host headers.
    # If the user intentionally binds Studio to a non-local interface, the CSRF
    # token and same-origin checks below still gate render access.
    bind = (bind_host or "").strip().lower().strip("[]")
    # Wildcard binding is available only when explicitly selected by the user.
    return bool(
        bind and not _is_local_bind_host(bind) and (bind in WILDCARD_BIND_HOSTS or host == bind)
    )


def _same_origin_request(origin: str | None, host_header: str | None) -> bool:
    """Validate an Origin header against the request Host header."""
    if not origin:
        return True
    parsed = urlsplit(origin)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    return parsed.netloc.lower() == (host_header or "").strip().lower()


def _content_type_is_json(value: str | None) -> bool:
    return (value or "").split(";", 1)[0].strip().lower() == "application/json"


def _studio_content_length(headers: Any) -> int:
    """Return a validated, bounded request-body length for Studio POST requests."""
    raw_value = headers.get("Content-Length")
    if raw_value is None or not str(raw_value).strip():
        raise StudioRequestError(
            "Studio render requests require a Content-Length header.",
            status=411,
            code="length_required",
        )
    try:
        length = int(str(raw_value).strip())
    except ValueError as exc:
        raise StudioRequestError(
            "Invalid Content-Length header.", code="invalid_content_length"
        ) from exc
    if length < 0:
        raise StudioRequestError(
            "Content-Length must not be negative.", code="invalid_content_length"
        )
    if length > MAX_GUI_REQUEST_BYTES:
        raise StudioRequestError(
            "Render request is too large. "
            f"Maximum request size is {_format_bytes(MAX_GUI_REQUEST_BYTES)}.",
            status=413,
            code="request_too_large",
        )
    return length


def _read_studio_request_body(handler: Any, length: int) -> bytes:
    """Read exactly the validated Studio request body within a short I/O deadline."""
    previous_timeout = handler.connection.gettimeout()
    try:
        handler.connection.settimeout(STUDIO_REQUEST_BODY_TIMEOUT_SECONDS)
        try:
            raw = handler.rfile.read(length)
        except TimeoutError as exc:
            raise StudioRequestError(
                "Timed out while reading the Studio request body.",
                status=408,
                code="request_body_timeout",
            ) from exc
    finally:
        handler.connection.settimeout(previous_timeout)

    if len(raw) != length:
        raise StudioRequestError(
            "Studio request body ended before Content-Length bytes were received.",
            code="incomplete_request_body",
        )
    return raw


def _validate_studio_api_headers(
    headers: Any,
    *,
    bind_host: str | None,
    csrf_token: str | None,
) -> None:
    """Reject API requests that did not originate from the active Studio page."""
    host = headers.get("Host")
    if not _host_header_is_trusted(host, bind_host):
        raise StudioRequestError(
            "Studio API requests must use a trusted local Host header.",
            status=403,
            code="untrusted_host",
        )

    if not _same_origin_request(headers.get("Origin"), host):
        raise StudioRequestError(
            "Studio API requests must come from the active Studio page origin.",
            status=403,
            code="untrusted_origin",
        )

    sec_fetch_site = (headers.get("Sec-Fetch-Site") or "").strip().lower()
    if sec_fetch_site in {"cross-site", "same-site"}:
        raise StudioRequestError(
            "Cross-site Studio API requests are not accepted.",
            status=403,
            code="untrusted_fetch_site",
        )

    if csrf_token:
        submitted = headers.get(STUDIO_TOKEN_HEADER)
        if not submitted or not secrets.compare_digest(str(submitted), csrf_token):
            raise StudioRequestError(
                "Studio API token is missing or invalid.",
                status=403,
                code="invalid_studio_token",
            )


def _validate_studio_post_headers(
    headers: Any,
    *,
    bind_host: str | None,
    csrf_token: str | None,
) -> None:
    """Validate authenticated JSON POST requests to the Studio API."""
    _validate_studio_api_headers(headers, bind_host=bind_host, csrf_token=csrf_token)
    if headers.get("Transfer-Encoding"):
        raise StudioRequestError(
            "Studio render requests do not support Transfer-Encoding.",
            status=400,
            code="unsupported_transfer_encoding",
        )
    if not _content_type_is_json(headers.get("Content-Type")):
        raise StudioRequestError(
            "Studio render requests must use Content-Type: application/json.",
            status=415,
            code="unsupported_media_type",
        )


def _json_bool(value: Any, *, default: bool, code: str, label: str) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    raise StudioRequestError(f"{label} must be true or false.", code=code)


def _json_int_range(
    value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
    code: str,
    label: str,
) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise StudioRequestError(
            f"{label} must be an integer from {minimum} to {maximum}.", code=code
        )
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise StudioRequestError(
            f"{label} must be an integer from {minimum} to {maximum}.", code=code
        ) from exc
    if not minimum <= number <= maximum:
        raise StudioRequestError(f"{label} must be between {minimum} and {maximum}.", code=code)
    return number


def _json_float_range(
    value: Any,
    *,
    default: float,
    minimum: float,
    maximum: float,
    code: str,
    label: str,
) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        raise StudioRequestError(
            f"{label} must be a number from {minimum:g} to {maximum:g}.", code=code
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise StudioRequestError(
            f"{label} must be a number from {minimum:g} to {maximum:g}.", code=code
        ) from exc
    if not minimum <= number <= maximum:
        raise StudioRequestError(f"{label} must be between {minimum:g} and {maximum:g}.", code=code)
    return number


def _validated_render_options(options: dict[str, Any]) -> dict[str, Any]:
    """Normalize Studio render options and turn bad input into 400 errors."""
    try:
        page_size = validate_page_size(str(options.get("pageSize") or "A4"))
    except ValueError as exc:
        raise StudioRequestError(f"pageSize {exc}", code="invalid_page_size") from exc

    direction = str(options.get("direction") or "").strip().lower()
    if direction not in {"", "auto", "rtl", "ltr"}:
        raise StudioRequestError("direction must be auto, rtl, or ltr.", code="invalid_direction")

    try:
        style = validate_style_name(options.get("style") or "modern")
    except ValueError as exc:
        raise StudioRequestError(str(exc), code="invalid_style") from exc
    try:
        palette = validate_palette_name(options.get("palette") or "blue")
    except ValueError as exc:
        raise StudioRequestError(str(exc), code="invalid_palette") from exc
    try:
        mode = validate_mode_name(options.get("mode") or "light")
    except ValueError as exc:
        raise StudioRequestError(str(exc), code="invalid_mode") from exc
    try:
        branding = validate_branding_mode(options.get("branding") or "off")
    except ValueError as exc:
        raise StudioRequestError(str(exc), code="invalid_branding") from exc

    try:
        quality_profile = validate_quality_profile(options.get("qualityProfile"))
    except ValueError as exc:
        raise StudioRequestError(f"qualityProfile {exc}", code="invalid_quality_profile") from exc

    quality_policies: dict[str, str | None] = {}
    for key, option_name, code in (
        ("math_error_policy", "mathErrorPolicy", "invalid_math_error_policy"),
        ("font_error_policy", "fontErrorPolicy", "invalid_font_error_policy"),
        (
            "navigation_error_policy",
            "navigationErrorPolicy",
            "invalid_navigation_error_policy",
        ),
    ):
        raw = options.get(option_name)
        if raw is None or not str(raw).strip():
            quality_policies[key] = None
            continue
        try:
            quality_policies[key] = validate_error_policy(str(raw))
        except ValueError as exc:
            raise StudioRequestError(f"{option_name} {exc}", code=code) from exc

    raw_required_fonts = options.get("requiredFonts") or []
    if isinstance(raw_required_fonts, str):
        raw_required_fonts = [part.strip() for part in raw_required_fonts.split(",")]
    if not isinstance(raw_required_fonts, list):
        raise StudioRequestError(
            "requiredFonts must be a comma-separated string or a JSON array.",
            code="invalid_required_fonts",
        )
    required_fonts: list[str] = []
    for value in raw_required_fonts:
        font = str(value).strip()
        if not font:
            continue
        if len(font) > 120:
            raise StudioRequestError(
                "Each required font name must be 120 characters or fewer.",
                code="invalid_required_fonts",
            )
        if font not in required_fonts:
            required_fonts.append(font)
    if len(required_fonts) > 16:
        raise StudioRequestError(
            "At most 16 required fonts may be checked.", code="invalid_required_fonts"
        )

    return {
        "style": style,
        "palette": palette,
        "mode": mode,
        "branding": branding,
        "toc": _json_bool(options.get("toc"), default=True, code="invalid_toc", label="toc"),
        "toc_depth": _json_int_range(
            options.get("tocDepth"),
            default=6,
            minimum=1,
            maximum=6,
            code="invalid_toc_depth",
            label="tocDepth",
        ),
        "toc_page_break": _json_bool(
            options.get("tocPageBreak"),
            default=True,
            code="invalid_toc_page_break",
            label="tocPageBreak",
        ),
        "h1_page_break": _json_bool(
            options.get("h1PageBreak"),
            default=True,
            code="invalid_h1_page_break",
            label="h1PageBreak",
        ),
        "page_size": page_size,
        "direction": direction or None,
        "cover": not _json_bool(
            options.get("noCover"), default=False, code="invalid_no_cover", label="noCover"
        ),
        "watermark_opacity": _json_float_range(
            options.get("watermarkOpacity"),
            default=0.065,
            minimum=0,
            maximum=1,
            code="invalid_watermark_opacity",
            label="watermarkOpacity",
        ),
        "no_header_footer": _json_bool(
            options.get("noHeaderFooter"),
            default=False,
            code="invalid_no_header_footer",
            label="noHeaderFooter",
        ),
        "no_mathjax": _json_bool(
            options.get("noMathjax"), default=False, code="invalid_no_mathjax", label="noMathjax"
        ),
        "quality_profile": quality_profile,
        **quality_policies,
        "required_fonts": tuple(required_fonts),
    }


def _asset_text(name: str) -> str:
    return (resources.files("mardas_md2pdf") / "assets" / name).read_text(encoding="utf-8")


def _shorten_filename(value: str, *, max_chars: int) -> str:
    """Trim long user-provided names while preserving extensions and uniqueness."""
    if len(value) <= max_chars:
        return value

    # SHA-1 is used only for a deterministic filename suffix, not security.
    digest = hashlib.sha1(
        value.encode("utf-8", "surrogatepass"), usedforsecurity=False
    ).hexdigest()[:10]
    stem = value
    suffix = ""
    if "." in value:
        candidate_stem, candidate_suffix = value.rsplit(".", 1)
        if candidate_stem and 1 <= len(candidate_suffix) <= 16:
            stem = candidate_stem
            suffix = f".{candidate_suffix}"

    marker = f"-{digest}"
    available = max(1, max_chars - len(marker) - len(suffix))
    return f"{stem[:available].rstrip('-_. ')}{marker}{suffix}"


def _safe_filename(value: str | None, default: str = "mardas-document") -> str:
    if not value:
        return default
    keep = []
    for char in value.strip():
        if char.isalnum() or char in {"-", "_", "."}:
            keep.append(char)
        elif char.isspace():
            keep.append("-")
    name = "".join(keep).strip("-_.")
    return _shorten_filename(name, max_chars=MAX_GUI_FILENAME_CHARS) if name else default


def _safe_ascii_filename(value: str, default: str = "mardas-document.pdf") -> str:
    keep = []
    for char in value.strip():
        if char.isascii() and (char.isalnum() or char in {"-", "_", "."}):
            keep.append(char)
        elif char.isspace():
            keep.append("-")
    name = "".join(keep).strip("-_.") or default
    if name.lower() == "pdf" and str(value).lower().endswith(".pdf"):
        name = default
    return _shorten_filename(name, max_chars=MAX_GUI_FILENAME_CHARS)


def _attachment_disposition(filename: str) -> str:
    fallback = _safe_ascii_filename(filename)
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


def _safe_asset_path_part(value: str) -> str:
    """Preserve browser-provided asset names while removing path-control bytes."""
    cleaned = "".join(
        char for char in value if char not in {"/", "\\"} and ord(char) >= 32 and ord(char) != 127
    )
    cleaned = cleaned.strip()
    if cleaned in {"", ".", ".."}:
        return ""
    return _shorten_filename(cleaned, max_chars=MAX_GUI_ASSET_PATH_PART_CHARS)


def _safe_asset_relative_path(value: str | None, fallback: str = "asset") -> Path:
    raw = str(value or fallback).replace("\\", "/").strip()
    parts = [_safe_asset_path_part(part) for part in raw.split("/")]
    safe_parts = [part for part in parts if part]
    return Path(*safe_parts) if safe_parts else Path(_safe_filename(fallback))


def _asset_path_key(path: Path) -> tuple[str, ...]:
    """Return a platform-neutral key that catches Windows case collisions."""
    return tuple(part.casefold() for part in path.parts)


def _asset_paths_conflict(left: Path, right: Path) -> bool:
    left_parts = _asset_path_key(left)
    right_parts = _asset_path_key(right)
    common = min(len(left_parts), len(right_parts))
    return left_parts[:common] == right_parts[:common]


def _gui_asset_target_groups(asset_paths: list[Path]) -> list[tuple[Path, ...]]:
    """Return primary asset paths plus only unambiguous basename fallbacks."""
    basename_counts = Counter(path.name.casefold() for path in asset_paths if len(path.parts) > 1)
    primary_keys = {_asset_path_key(path) for path in asset_paths}
    groups: list[tuple[Path, ...]] = []
    for rel_path in asset_paths:
        targets = [rel_path]
        basename = Path(rel_path.name)
        if (
            len(rel_path.parts) > 1
            and basename_counts[rel_path.name.casefold()] == 1
            and _asset_path_key(basename) not in primary_keys
        ):
            targets.append(basename)
        groups.append(tuple(targets))
    return groups


def _validate_gui_asset_targets(
    asset_paths: list[Path], *, reserved_paths: tuple[Path, ...]
) -> list[tuple[Path, ...]]:
    target_groups = _gui_asset_target_groups(asset_paths)
    targets = [target for group in target_groups for target in group]
    normalized_reserved = tuple(Path(path) for path in reserved_paths)

    for target in targets:
        if any(_asset_paths_conflict(target, reserved) for reserved in normalized_reserved):
            raise StudioRequestError(
                f'Attached asset path "{target.as_posix()}" conflicts with a Studio working file.',
                code="reserved_asset_path",
            )

    for index, target in enumerate(targets):
        for other in targets[index + 1 :]:
            if _asset_paths_conflict(target, other):
                raise StudioRequestError(
                    "Attached asset paths conflict after normalization or basename fallback.",
                    code="conflicting_asset_path",
                )
    return target_groups


def _write_gui_assets(tmp: Path, assets: Any, *, reserved_paths: tuple[Path, ...] = ()) -> None:
    if not isinstance(assets, list):
        return
    total_bytes = 0
    prepared: list[tuple[Path, bytes]] = []
    for index, asset in enumerate(assets[:MAX_GUI_ASSETS]):
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("path") or asset.get("name") or f"asset-{index}")
        data_url = str(asset.get("data") or "")
        if "," not in data_url:
            continue
        header, payload = data_url.split(",", 1)
        if "base64" not in header.lower():
            continue
        try:
            data = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            continue
        if len(data) > MAX_GUI_ASSET_BYTES:
            continue
        if total_bytes + len(data) > MAX_GUI_TOTAL_ASSET_BYTES:
            continue
        rel_path = _safe_asset_relative_path(name, fallback=f"asset-{index}")
        prepared.append((rel_path, data))
        total_bytes += len(data)

    target_groups = _validate_gui_asset_targets(
        [rel_path for rel_path, _data in prepared], reserved_paths=reserved_paths
    )
    for (rel_path, data), relative_targets in zip(prepared, target_groups, strict=True):
        for relative_target in relative_targets:
            target = tmp / relative_target
            try:
                target.relative_to(tmp)
            except ValueError:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)


def _validate_studio_payload(
    payload: dict[str, Any], *, allow_empty_markdown: bool = False
) -> tuple[str, dict[str, Any], list[Any], dict[str, Any], str]:
    markdown = str(payload.get("markdown") or "")
    options = payload.get("options") or {}
    assets = payload.get("assets") or []
    if not isinstance(options, dict):
        raise StudioRequestError("Render options must be a JSON object.", code="invalid_options")
    if not allow_empty_markdown and not markdown.strip():
        raise StudioRequestError("Markdown content is empty.", code="empty_markdown")
    if len(markdown.encode("utf-8")) > MAX_GUI_MARKDOWN_BYTES:
        raise StudioRequestError(
            "Markdown content is too large. "
            f"Maximum Markdown size is {_format_bytes(MAX_GUI_MARKDOWN_BYTES)}.",
            status=413,
            code="markdown_too_large",
        )
    render_options = _validated_render_options(options)
    filename = _safe_filename(
        str(options.get("filename") or options.get("title") or "mardas-document")
    )
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"
    return markdown, options, assets if isinstance(assets, list) else [], render_options, filename


def _studio_pdf_options(
    *,
    tmp: Path,
    md_path: Path,
    output_path: Path,
    options: dict[str, Any],
    render_options: dict[str, Any],
) -> PdfOptions:
    brand_logo_path = None
    brand_logo_value = str(options.get("brandLogo") or "").strip()
    if brand_logo_value:
        brand_logo_path = tmp / _safe_asset_relative_path(brand_logo_value, fallback="brand-logo")
        if not brand_logo_path.is_file():
            raise StudioRequestError(
                "brandLogo must match an attached asset path.",
                code="invalid_brand_logo",
            )

    return PdfOptions(
        input_path=md_path,
        output_path=output_path,
        title=(str(options.get("title") or "").strip() or None),
        author=(str(options.get("author") or "").strip() or None),
        description=(str(options.get("description") or "").strip() or None),
        toc=render_options["toc"],
        toc_depth=render_options["toc_depth"],
        toc_page_break=render_options["toc_page_break"],
        h1_page_break=render_options["h1_page_break"],
        page_size=render_options["page_size"],
        document_direction=render_options["direction"],
        style=render_options["style"],
        palette=render_options["palette"],
        mode=render_options["mode"],
        cover=render_options["cover"],
        branding=render_options["branding"],
        brand_name=(str(options.get("brandName") or "").strip() or None),
        brand_logo=brand_logo_path,
        brand_footer=(str(options.get("brandFooter") or "").strip() or None),
        watermark_text=(str(options.get("watermark") or "").strip() or None),
        watermark_opacity=render_options["watermark_opacity"],
        no_header_footer=render_options["no_header_footer"],
        no_mathjax=render_options["no_mathjax"],
        quality_profile=render_options["quality_profile"],
        math_error_policy=render_options["math_error_policy"],
        font_error_policy=render_options["font_error_policy"],
        navigation_error_policy=render_options["navigation_error_policy"],
        required_fonts=render_options["required_fonts"],
        quality_report=tmp / "quality-report.json",
    )


def _studio_preview_page_dimensions(page_size: str | None) -> tuple[str, str]:
    """Return CSS width and height for Studio's screen-side PDF preview sheet."""
    try:
        page_size = validate_page_size(page_size)
    except ValueError:
        page_size = "A4"

    dimension_match = STUDIO_PREVIEW_DIMENSIONS_RE.fullmatch(page_size)
    if dimension_match:
        return dimension_match.group("width"), dimension_match.group("height")

    name_match = STUDIO_PREVIEW_PAGE_NAME_RE.fullmatch(page_size)
    if not name_match:
        return STUDIO_PREVIEW_NAMED_PAGE_SIZES["a4"]

    width, height = STUDIO_PREVIEW_NAMED_PAGE_SIZES.get(
        name_match.group("name").lower(), STUDIO_PREVIEW_NAMED_PAGE_SIZES["a4"]
    )
    if (name_match.group("orientation") or "").lower() == "landscape":
        width, height = height, width
    return width, height


def _studio_pdf_like_preview_css(page_size: str | None) -> str:
    """Inject screen-only CSS that makes renderer HTML read like a PDF-like sheet preview."""
    page_width, page_height = _studio_preview_page_dimensions(page_size)
    return f"""
  <style id="mardas-studio-preview-css">
    @media screen {{
      :root {{
        --md2pdf-preview-page-width: {page_width};
        --md2pdf-preview-page-height: {page_height};
        --md2pdf-preview-page-gap: 30px;
        --md2pdf-preview-scale: 1;
        --md2pdf-preview-shell-bg: #d8dde6;
        --md2pdf-preview-shell-bg-dark: #050505;
        --md2pdf-preview-label-bg: #eef3fb;
      }}
      html {{
        min-height: 100%;
        background: var(--md2pdf-preview-shell-bg) !important;
        overflow-x: hidden;
        color-scheme: light;
        scrollbar-width: thin;
        scrollbar-color: #aab3c1 transparent;
      }}
      html.md2pdf-preview-dark,
      html:has(body.md2pdf-mode-dark) {{
        color-scheme: dark;
        scrollbar-color: #4a4a4a transparent;
      }}
      * {{
        scrollbar-width: thin;
        scrollbar-color: #aab3c1 transparent;
      }}
      html.md2pdf-preview-dark *,
      html:has(body.md2pdf-mode-dark) * {{
        scrollbar-color: #4a4a4a transparent;
      }}
      *::-webkit-scrollbar {{
        width: 10px;
        height: 10px;
      }}
      *::-webkit-scrollbar-track {{
        background: transparent;
      }}
      *::-webkit-scrollbar-thumb {{
        background: #aab3c1;
        border: 3px solid transparent;
        border-radius: 999px;
        background-clip: padding-box;
      }}
      html.md2pdf-preview-dark *::-webkit-scrollbar-thumb,
      html:has(body.md2pdf-mode-dark) *::-webkit-scrollbar-thumb {{
        background: #4a4a4a;
        background-clip: padding-box;
      }}
      *::-webkit-scrollbar-thumb:hover {{
        background: #7f8da3;
        background-clip: padding-box;
      }}
      html.md2pdf-preview-dark *::-webkit-scrollbar-thumb:hover,
      html:has(body.md2pdf-mode-dark) *::-webkit-scrollbar-thumb:hover {{
        background: #666666;
        background-clip: padding-box;
      }}
      body {{
        min-height: 100%;
        min-width: 0;
        margin: 0 !important;
        padding: var(--md2pdf-preview-page-gap) 0 !important;
        background: var(--md2pdf-preview-shell-bg) !important;
        display: flex;
        flex-direction: column;
        align-items: center;
        overflow-x: hidden;
      }}
      body.md2pdf-mode-dark {{
        background: var(--md2pdf-preview-shell-bg-dark) !important;
        --md2pdf-preview-label-bg: #111111;
      }}
      .md2pdf-document {{
        width: var(--md2pdf-preview-page-width);
        min-height: var(--md2pdf-preview-page-height);
        margin: 0 auto var(--md2pdf-preview-page-gap) !important;
        padding: var(--page-margin-top) var(--page-margin-x) var(--page-margin-bottom) !important;
        box-shadow: 0 24px 74px rgba(15, 23, 42, .28), 0 0 0 1px rgba(15, 23, 42, .14);
        overflow: visible;
        flex: 0 0 auto;
        position: relative;
        isolation: isolate;
        zoom: var(--md2pdf-preview-scale);
      }}
      @supports not (zoom: 1) {{
        .md2pdf-document {{
          transform: scale(var(--md2pdf-preview-scale));
          transform-origin: top center;
        }}
      }}
      body:not(.md2pdf-mode-dark) .md2pdf-document {{
        background: #ffffff !important;
      }}
      body.md2pdf-mode-dark .md2pdf-document {{
        box-shadow: 0 24px 74px rgba(0, 0, 0, .72), 0 0 0 1px rgba(255, 255, 255, .12);
      }}
      .md2pdf-article {{
        max-width: none !important;
        margin: 0 !important;
        position: relative;
        z-index: 1;
      }}
      .md2pdf-page-break {{
        display: block !important;
        height: auto !important;
        min-height: 0 !important;
        margin: 18mm 0 !important;
        border: 0 !important;
        border-top: 1px dashed color-mix(in srgb, var(--accent, #2563eb) 48%, var(--line, #dbe3ef));
        overflow: visible !important;
        break-after: auto !important;
        page-break-after: auto !important;
        position: relative;
      }}
      .md2pdf-page-break::after {{
        content: "Explicit page break";
        position: absolute;
        left: 50%;
        top: -.85em;
        transform: translateX(-50%);
        padding: .1em .55em;
        border-radius: 999px;
        background: var(--md2pdf-preview-label-bg);
        color: var(--muted, #64748b);
        font: 700 9px/1.4 var(--font-en, Arial, sans-serif);
        letter-spacing: .08em;
        text-transform: uppercase;
        white-space: nowrap;
      }}
    }}
  </style>
  <script id="mardas-studio-preview-scale-script">
    (() => {{
      let refreshHandle = 0;
      const syncPreviewShellTheme = () => {{
        document.documentElement.classList.toggle(
          'md2pdf-preview-dark',
          Boolean(document.body && document.body.classList.contains('md2pdf-mode-dark'))
        );
      }};
      const updatePreviewScale = () => {{
        const root = document.documentElement;
        syncPreviewShellTheme();
        const page = document.querySelector('.md2pdf-document');
        if (!page) return;
        root.style.setProperty('--md2pdf-preview-scale', '1');
        const pageWidth = page.getBoundingClientRect().width;
        const viewportWidth = document.documentElement.clientWidth || window.innerWidth || pageWidth;
        const scale = Math.min(1, Math.max(0.28, (viewportWidth - 32) / Math.max(pageWidth, 1)));
        root.style.setProperty('--md2pdf-preview-scale', scale.toFixed(4));
      }};
      const refreshPreviewPageChrome = () => {{ updatePreviewScale(); }};
      const queueRefresh = () => {{
        if (refreshHandle) cancelAnimationFrame(refreshHandle);
        refreshHandle = requestAnimationFrame(refreshPreviewPageChrome);
      }};
      window.addEventListener('resize', queueRefresh);
      if (document.fonts && document.fonts.ready) document.fonts.ready.then(queueRefresh).catch(() => {{}});
      if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', queueRefresh, {{ once: true }});
      }} else {{
        queueRefresh();
      }}
      setTimeout(queueRefresh, 200);
    }})();
  </script>"""


def _inject_studio_preview_css(html_text: str, *, page_size: str | None) -> str:
    preview_css = _studio_pdf_like_preview_css(page_size)
    return html_text.replace("</head>", f"{preview_css}\n</head>", 1)


def _render_studio_html_payload(payload: dict[str, Any]) -> str:
    markdown, options, assets, render_options, _filename = _validate_studio_payload(
        payload, allow_empty_markdown=True
    )
    with tempfile.TemporaryDirectory(prefix="mardas-md2pdf-gui-html-") as tmpdir:
        tmp = Path(tmpdir)
        md_path = tmp / "document.md"
        html_path = tmp / "document.html"
        md_path.write_text(markdown, encoding="utf-8")
        _write_gui_assets(
            tmp,
            assets,
            reserved_paths=(Path("document.md"), Path("document.html"), Path("document.pdf")),
        )
        pdf_options = _studio_pdf_options(
            tmp=tmp,
            md_path=md_path,
            output_path=html_path.with_suffix(".pdf"),
            options=options,
            render_options=render_options,
        )
        result = render_markdown_file(
            md_path,
            toc=render_options["toc"],
            toc_depth=render_options["toc_depth"],
            code_style=code_style_for_appearance(render_options["style"], render_options["mode"]),
            unsafe_html=False,
            allow_remote_images=False,
        )
        html_text = build_html(
            result,
            pdf_options,
            include_cover=render_options["cover"],
            include_content=True,
            include_watermark=True,
        )
        html_text = _inject_studio_preview_css(html_text, page_size=render_options["page_size"])
        html_path.write_text(html_text, encoding="utf-8")
        return html_text


def _render_studio_document_export(
    directory: Path,
    *,
    markdown: str,
    options: dict[str, Any],
    assets: list[Any],
    render_options: dict[str, Any],
    filename: str,
    session: RenderSession,
    progress: Callable[[str, float], None],
    cancelled: Callable[[], bool],
) -> Path:
    md_path = directory / "document.md"
    pdf_path = directory / filename
    md_path.write_text(markdown, encoding="utf-8")
    _write_gui_assets(
        directory,
        assets,
        reserved_paths=(Path("document.md"), Path(filename)),
    )
    pdf_options = _studio_pdf_options(
        tmp=directory,
        md_path=md_path,
        output_path=pdf_path,
        options=options,
        render_options=render_options,
    )
    pdf_options.progress = progress
    pdf_options.cancelled = cancelled
    convert(pdf_options, session=session)
    if pdf_path.stat().st_size > MAX_STUDIO_EXPORT_RESULT_BYTES:
        pdf_path.unlink(missing_ok=True)
        raise StudioRequestError(
            "Rendered PDF exceeds the Studio result-size limit.",
            status=413,
            code="export_result_too_large",
        )
    return pdf_path


def _studio_job_error(exc: BaseException | None) -> tuple[str, str, int]:
    if isinstance(exc, StudioRequestError):
        return str(exc), exc.code, exc.status
    if isinstance(exc, WorkspaceError):
        return str(exc), exc.code, exc.status
    if isinstance(exc, MarkdownInputError):
        return str(exc), "invalid_markdown", 400
    if isinstance(exc, DocumentAssetError):
        return str(exc), "unsafe_document_asset", 400
    if isinstance(exc, RenderCancelledError):
        return "PDF rendering was cancelled.", "render_cancelled", 409
    if isinstance(exc, StudioExportJobError):
        return str(exc), "invalid_export_result", 500
    return (
        "Studio rendering failed. Check the local Studio logs for details.",
        "render_failed",
        500,
    )


def _studio_export_quality_payload(job: StudioExportJob) -> dict[str, Any] | None:
    report = job.directory / "quality-report.json"
    try:
        if not report.is_file() or report.stat().st_size > 512 * 1024:
            return None
        payload = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return {
        "schema_version": payload.get("schema_version"),
        "profile": payload.get("profile"),
        "ok": bool(payload.get("ok")),
        "summary": payload.get("summary") if isinstance(payload.get("summary"), dict) else {},
        "events": payload.get("events") if isinstance(payload.get("events"), list) else [],
    }


def _studio_export_job_payload(job: StudioExportJob) -> dict[str, Any]:
    snapshot = job.future.snapshot()
    payload = snapshot.to_dict()
    payload["job_id"] = job.job_id
    payload["filename"] = job.filename
    quality = _studio_export_quality_payload(job)
    if quality is not None:
        payload["quality"] = quality
    if snapshot.status == "succeeded":
        payload["result_url"] = f"/api/export-jobs/{job.job_id}/result"
    elif snapshot.status == "failed":
        message, code, status = _studio_job_error(job.future.exception())
        payload.update({"error": message, "code": code, "error_status": status})
    elif snapshot.status == "cancelled":
        payload.update(
            {
                "error": "PDF rendering was cancelled.",
                "code": "render_cancelled",
                "error_status": 409,
            }
        )
    return payload


def _studio_export_job_route(request_path: str) -> tuple[str, str] | None:
    prefix = "/api/export-jobs/"
    if not request_path.startswith(prefix):
        return None
    parts = request_path[len(prefix) :].split("/")
    if not parts or not STUDIO_EXPORT_JOB_RE.fullmatch(parts[0]):
        return None
    action = parts[1] if len(parts) == 2 else "status" if len(parts) == 1 else ""
    if action not in {"status", "result", "cancel"}:
        return None
    return parts[0], action


class GuiRequestHandler(BaseHTTPRequestHandler):
    server_version = f"MardasMD2PDFGUI/{__version__}"

    def _studio_csrf_token(self) -> str:
        return str(getattr(self.server, "studio_csrf_token", ""))

    def _studio_bind_host(self) -> str:
        return str(getattr(self.server, "studio_bind_host", self.server.server_address[0]))

    def _studio_project_workspace(self) -> ProjectWorkspace | None:
        workspace = getattr(self.server, "studio_project_workspace", None)
        return workspace if isinstance(workspace, ProjectWorkspace) else None

    def _set_studio_project_workspace(self, workspace: ProjectWorkspace) -> None:
        self.server.studio_project_workspace = workspace  # type: ignore[attr-defined]

    def _studio_export_manager(self) -> StudioExportManager:
        manager = getattr(self.server, "studio_export_manager", None)
        if isinstance(manager, StudioExportManager):
            return manager
        with STUDIO_EXPORT_MANAGER_INIT_LOCK:
            manager = getattr(self.server, "studio_export_manager", None)
            if isinstance(manager, StudioExportManager):
                return manager
            manager = StudioExportManager(
                workers=MAX_STUDIO_CONCURRENT_EXPORTS,
                queue_size=DEFAULT_STUDIO_EXPORT_QUEUE_SIZE,
                idle_timeout=DEFAULT_STUDIO_RENDER_IDLE_TIMEOUT,
            )
            self.server.studio_export_manager = manager  # type: ignore[attr-defined]
            original_close = self.server.server_close

            def close_with_exports() -> None:
                manager.close()
                original_close()

            self.server.server_close = close_with_exports  # type: ignore[method-assign]
            return manager

    def _submit_export_job(self, payload: dict[str, Any]) -> StudioExportJob:
        kind = str(payload.get("kind") or "document").strip().lower()
        manager = self._studio_export_manager()
        if kind == "book":
            workspace = self._require_studio_project_workspace()
            filename = (
                workspace.manifest.output_path.name
                if workspace.manifest is not None
                else "book.pdf"
            )

            def render_book_job(
                directory: Path,
                session: RenderSession,
                progress: Callable[[str, float], None],
                cancelled: Callable[[], bool],
            ) -> Path:
                output = directory / filename
                built, _filename, refreshed = export_workspace_book_pdf(
                    workspace,
                    output,
                    session=session,
                    progress=progress,
                    cancelled=cancelled,
                )
                self._set_studio_project_workspace(refreshed)
                if built.stat().st_size > MAX_STUDIO_EXPORT_RESULT_BYTES:
                    built.unlink(missing_ok=True)
                    raise StudioRequestError(
                        "Rendered PDF exceeds the Studio result-size limit.",
                        status=413,
                        code="export_result_too_large",
                    )
                return built

            return manager.submit(
                label="Book PDF export",
                filename=filename,
                work=render_book_job,
            )

        if kind != "document":
            raise StudioRequestError(
                "Export job kind must be document or book.",
                code="invalid_export_job_kind",
            )
        markdown, options, assets, render_options, filename = _validate_studio_payload(payload)

        def render_document_job(
            directory: Path,
            session: RenderSession,
            progress: Callable[[str, float], None],
            cancelled: Callable[[], bool],
        ) -> Path:
            return _render_studio_document_export(
                directory,
                markdown=markdown,
                options=options,
                assets=assets,
                render_options=render_options,
                filename=filename,
                session=session,
                progress=progress,
                cancelled=cancelled,
            )

        return manager.submit(
            label="Document PDF export",
            filename=filename,
            work=render_document_job,
        )

    def _require_studio_project_workspace(self) -> ProjectWorkspace:
        workspace = self._studio_project_workspace()
        if workspace is None:
            raise WorkspaceError(
                "Studio was not started in project mode.",
                code="project_mode_disabled",
                status=404,
            )
        return workspace

    def _studio_preview_render_lock(self) -> threading.Lock:
        lock = getattr(self.server, "studio_preview_render_lock", None)
        if lock is None:
            lock = threading.Lock()
            self.server.studio_preview_render_lock = lock  # type: ignore[attr-defined]
        return lock

    def _studio_preview_state_lock(self) -> threading.Lock:
        lock = getattr(self.server, "studio_preview_state_lock", None)
        if lock is None:
            lock = threading.Lock()
            self.server.studio_preview_state_lock = lock  # type: ignore[attr-defined]
        return lock

    def _register_preview_request(self) -> tuple[str, str] | None:
        preview_id = (self.headers.get(STUDIO_PREVIEW_REQUEST_HEADER) or "").strip()
        if not preview_id:
            return None
        if not STUDIO_PREVIEW_REQUEST_RE.fullmatch(preview_id):
            raise StudioRequestError(
                "Studio preview request id is invalid.",
                status=400,
                code="invalid_preview_request_id",
            )
        client_id = (self.headers.get(STUDIO_PREVIEW_CLIENT_HEADER) or "legacy").strip()
        if not STUDIO_PREVIEW_CLIENT_RE.fullmatch(client_id):
            raise StudioRequestError(
                "Studio preview client id is invalid.",
                status=400,
                code="invalid_preview_client_id",
            )
        with self._studio_preview_state_lock():
            states = getattr(self.server, "studio_latest_preview_ids", None)
            if not isinstance(states, dict):
                states = {}
                self.server.studio_latest_preview_ids = states  # type: ignore[attr-defined]
            if client_id not in states and len(states) >= MAX_STUDIO_PREVIEW_CLIENTS:
                states.pop(next(iter(states)))
            states[client_id] = preview_id
        return client_id, preview_id

    def _preview_request_is_current(self, preview_request: tuple[str, str] | None) -> bool:
        if not preview_request:
            return True
        client_id, preview_id = preview_request
        with self._studio_preview_state_lock():
            states = getattr(self.server, "studio_latest_preview_ids", {})
            return isinstance(states, dict) and states.get(client_id) == preview_id

    def _send_stale_preview(self) -> None:
        self._send_error(
            "A newer Studio PDF-like preview request superseded this one.",
            status=409,
            code="stale_preview",
        )

    def _send_text(
        self, content: str, *, status: int = 200, content_type: str = "text/html; charset=utf-8"
    ) -> None:
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_error(self, message: str, *, status: int, code: str) -> None:
        self._send_json(_error_payload(message, status=status, code=code), status=status)

    def _request_path(self) -> str:
        return urlsplit(self.path).path or "/"

    def _request_query(self) -> dict[str, list[str]]:
        return parse_qs(urlsplit(self.path).query, keep_blank_values=True)

    def _send_workspace_error(self, exc: WorkspaceError) -> None:
        payload = _error_payload(str(exc), status=exc.status, code=exc.code)
        workspace = self._studio_project_workspace()
        if workspace is not None and exc.diagnostics:
            payload["diagnostics"] = workspace_diagnostics_payload(workspace, exc.diagnostics)
        self._send_json(payload, status=exc.status)

    def _send_export_artifact(self, artifact: Any) -> bool:
        try:
            size = artifact.path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", artifact.content_type)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Disposition", _attachment_disposition(artifact.filename)
            )
            self.send_header("Content-Length", str(size))
            self.end_headers()
            with artifact.path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    self.wfile.write(chunk)
            return True
        except (BrokenPipeError, ConnectionResetError):
            LOGGER.info("Studio export download disconnected before completion")
            return False

    def _handle_export_job_get(self, request_path: str) -> bool:
        route = _studio_export_job_route(request_path)
        if route is None:
            return False
        job_id, action = route
        if action == "cancel":
            return False
        _validate_studio_api_headers(
            self.headers,
            bind_host=self._studio_bind_host(),
            csrf_token=self._studio_csrf_token(),
        )
        manager = self._studio_export_manager()
        job = manager.get(job_id)
        if job is None:
            self._send_error(
                "Export job was not found or has expired.",
                status=404,
                code="export_job_not_found",
            )
            return True
        if action == "status":
            self._send_json(_studio_export_job_payload(job))
            return True

        snapshot = job.future.snapshot()
        if snapshot.status != "succeeded":
            self._send_error(
                "Export result is not ready.",
                status=409,
                code="export_result_not_ready",
            )
            return True
        artifact = job.future.result(timeout=0)
        if self._send_export_artifact(artifact):
            manager.mark_downloaded(job_id)
        return True

    def _handle_export_job_post(self, request_path: str) -> bool:
        route = _studio_export_job_route(request_path)
        create = request_path == "/api/export-jobs"
        if not create and (route is None or route[1] != "cancel"):
            return False
        _validate_studio_post_headers(
            self.headers,
            bind_host=self._studio_bind_host(),
            csrf_token=self._studio_csrf_token(),
        )
        length = _studio_content_length(self.headers)
        raw = _read_studio_request_body(self, length)
        payload = _decode_json_payload(raw)
        if create:
            job = self._submit_export_job(payload)
            response = _studio_export_job_payload(job)
            response["status_url"] = f"/api/export-jobs/{job.job_id}"
            response["cancel_url"] = f"/api/export-jobs/{job.job_id}/cancel"
            self._send_json(response, status=202)
            return True

        if route is None:
            return False
        job_id, _action = route
        cancelled = self._studio_export_manager().cancel(job_id)
        if cancelled is None:
            self._send_error(
                "Export job was not found or has expired.",
                status=404,
                code="export_job_not_found",
            )
        elif not cancelled:
            self._send_error(
                "Export job has already finished.",
                status=409,
                code="export_job_finished",
            )
        else:
            job = self._studio_export_manager().get(job_id)
            self._send_json(
                _studio_export_job_payload(job) if job is not None else {"job_id": job_id},
                status=202,
            )
        return True

    def _handle_project_get(self, request_path: str) -> bool:
        if request_path not in {"/api/project", "/api/project/file"}:
            return False
        _validate_studio_api_headers(
            self.headers,
            bind_host=self._studio_bind_host(),
            csrf_token=self._studio_csrf_token(),
        )
        workspace = self._studio_project_workspace()
        if request_path == "/api/project":
            if workspace is None:
                self._send_json({"enabled": False})
                return True
            refreshed = refresh_workspace(workspace)
            self._set_studio_project_workspace(refreshed)
            self._send_json(workspace_payload(refreshed))
            return True

        workspace = self._require_studio_project_workspace()
        values = self._request_query().get("path", [])
        relative_path = values[0] if values else ""
        self._send_json(read_workspace_file(workspace, relative_path))
        return True

    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        request_path = self._request_path()
        try:
            if self._handle_export_job_get(request_path):
                return
            if self._handle_project_get(request_path):
                return
        except RenderQueueFullError:
            self._send_error(
                "Studio export queue is full. Try again after an active job finishes.",
                status=429,
                code="export_queue_full",
            )
            return
        except RenderCancelledError:
            self._send_error(
                "PDF rendering was cancelled.",
                status=409,
                code="render_cancelled",
            )
            return
        except StudioRequestError as exc:
            self._send_error(str(exc), status=exc.status, code=exc.code)
            return
        except WorkspaceError as exc:
            self._send_workspace_error(exc)
            return
        except Exception:  # pragma: no cover - defensive project API boundary
            LOGGER.exception("Studio project GET failed for %s", request_path)
            self._send_error(
                "Studio project request failed. Check the local Studio logs for details.",
                status=500,
                code="project_request_failed",
            )
            return

        if request_path in {"/", "/index.html"}:
            html = (
                _asset_text("gui.html")
                .replace("__MARDAS_VERSION__", __version__)
                .replace("__MARDAS_STUDIO_TOKEN__", self._studio_csrf_token())
            )
            self._send_text(html)
            return
        filename = gui_brand_asset_filename(request_path)
        if filename is not None:
            data = packaged_asset_path(filename).read_bytes()
            content_type = asset_content_type(filename)
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if request_path == "/api/version":
            self._send_json({"version": __version__})
            return
        self._send_text("Not found", status=404, content_type="text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802 - stdlib API
        request_path = self._request_path()
        if request_path == "/api/export-jobs" or (
            (route := _studio_export_job_route(request_path)) is not None
            and route[1] == "cancel"
        ):
            try:
                if self._handle_export_job_post(request_path):
                    return
            except RenderQueueFullError:
                self._send_error(
                    "Studio export queue is full. Try again after an active job finishes.",
                    status=429,
                    code="export_queue_full",
                )
            except StudioRequestError as exc:
                self._send_error(str(exc), status=exc.status, code=exc.code)
            except WorkspaceError as exc:
                self._send_workspace_error(exc)
            except Exception:
                LOGGER.exception("Studio export job request failed for %s", request_path)
                self._send_error(
                    "Studio export job request failed. Check the local Studio logs for details.",
                    status=500,
                    code="export_job_failed",
                )
            return
        allowed = {
            "/api/render",
            "/api/render-html",
            "/api/project/save",
            "/api/project/validate",
            "/api/project/render-book",
            "/api/project/render-book-html",
            "/api/project/render-file-html",
        }
        if request_path not in allowed:
            self._send_error("Unknown endpoint", status=404, code="not_found")
            return
        try:
            _validate_studio_post_headers(
                self.headers,
                bind_host=self._studio_bind_host(),
                csrf_token=self._studio_csrf_token(),
            )
            length = _studio_content_length(self.headers)
            preview_request = (
                self._register_preview_request()
                if request_path
                in {
                    "/api/render-html",
                    "/api/project/render-book-html",
                    "/api/project/render-file-html",
                }
                else None
            )
            raw = _read_studio_request_body(self, length)
            payload = _decode_json_payload(raw)

            if request_path == "/api/project/save":
                workspace = self._require_studio_project_workspace()
                relative_path = payload.get("path")
                content = payload.get("content")
                expected = payload.get("expected_sha256")
                if not isinstance(relative_path, str):
                    raise WorkspaceError(
                        "Project save requires a relative file path.",
                        code="invalid_project_path",
                    )
                if not isinstance(content, str):
                    raise WorkspaceError(
                        "Project save requires text content.",
                        code="invalid_project_content",
                    )
                if not isinstance(expected, str):
                    raise WorkspaceError(
                        "Project save requires the previously opened file hash.",
                        code="missing_project_file_hash",
                    )
                file_payload = write_workspace_file(
                    workspace, relative_path, content, expected_sha256=expected
                )
                refreshed = refresh_workspace(workspace)
                self._set_studio_project_workspace(refreshed)
                self._send_json({"file": file_payload, "project": workspace_payload(refreshed)})
                return

            if request_path == "/api/project/validate":
                workspace = self._require_studio_project_workspace()
                refreshed = refresh_workspace(workspace)
                self._set_studio_project_workspace(refreshed)
                self._send_json(workspace_payload(refreshed))
                return

            if request_path == "/api/project/render-file-html":
                workspace = self._require_studio_project_workspace()
                relative_path = payload.get("path")
                content = payload.get("content")
                if not isinstance(relative_path, str) or not isinstance(content, str):
                    raise WorkspaceError(
                        "Project preview requires a file path and text content.",
                        code="invalid_project_preview",
                    )
                if not self._preview_request_is_current(preview_request):
                    self._send_stale_preview()
                    return
                with self._studio_preview_render_lock():
                    if not self._preview_request_is_current(preview_request):
                        self._send_stale_preview()
                        return
                    html_text, refreshed = render_workspace_file_html(
                        workspace, relative_path, content
                    )
                    html_text = _inject_studio_preview_css(
                        html_text,
                        page_size=str(refreshed.config.values.get("page_size", "A4")),
                    )
                    self._set_studio_project_workspace(refreshed)
                    if not self._preview_request_is_current(preview_request):
                        self._send_stale_preview()
                        return
                self._send_text(html_text, content_type="text/html; charset=utf-8")
                return

            if request_path == "/api/project/render-book-html":
                workspace = self._require_studio_project_workspace()
                if not self._preview_request_is_current(preview_request):
                    self._send_stale_preview()
                    return
                with self._studio_preview_render_lock():
                    if not self._preview_request_is_current(preview_request):
                        self._send_stale_preview()
                        return
                    html_text, refreshed = render_workspace_book_html(workspace)
                    html_text = _inject_studio_preview_css(
                        html_text,
                        page_size=str(refreshed.config.values.get("page_size", "A4")),
                    )
                    self._set_studio_project_workspace(refreshed)
                    if not self._preview_request_is_current(preview_request):
                        self._send_stale_preview()
                        return
                self._send_text(html_text, content_type="text/html; charset=utf-8")
                return

            if request_path == "/api/render-html":
                if not self._preview_request_is_current(preview_request):
                    self._send_stale_preview()
                    return
                if preview_request:
                    with self._studio_preview_render_lock():
                        if not self._preview_request_is_current(preview_request):
                            self._send_stale_preview()
                            return
                        html_text = _render_studio_html_payload(payload)
                        if not self._preview_request_is_current(preview_request):
                            self._send_stale_preview()
                            return
                else:
                    html_text = _render_studio_html_payload(payload)
                self._send_text(html_text, content_type="text/html; charset=utf-8")
                return

            job_payload = dict(payload)
            job_payload["kind"] = (
                "book" if request_path == "/api/project/render-book" else "document"
            )
            job = self._submit_export_job(job_payload)
            artifact = job.future.result(timeout=900)
            if self._send_export_artifact(artifact):
                self._studio_export_manager().mark_downloaded(job.job_id)
        except RenderQueueFullError:
            self._send_error(
                "Studio export queue is full. Try again after an active job finishes.",
                status=429,
                code="export_queue_full",
            )
        except RenderCancelledError:
            self._send_error(
                "PDF rendering was cancelled.",
                status=409,
                code="render_cancelled",
            )
        except StudioRequestError as exc:
            self._send_error(str(exc), status=exc.status, code=exc.code)
        except WorkspaceError as exc:
            self._send_workspace_error(exc)
        except MarkdownInputError as exc:
            self._send_error(str(exc), status=400, code="invalid_markdown")
        except DocumentAssetError as exc:
            self._send_error(str(exc), status=400, code="unsafe_document_asset")
        except Exception:  # pragma: no cover - defensive boundary; exercised via HTTP tests
            LOGGER.exception("Studio render failed for %s", request_path)
            self._send_error(
                "Studio rendering failed. Check the local Studio logs for details.",
                status=500,
                code="render_failed",
            )

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[Mardas GUI] {self.address_string()} - {fmt % args}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mrs-md2pdf-gui",
        description="Open the local Mardas Folio GUI for editing Markdown and exporting PDFs.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind; default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind; default: 8765")
    parser.add_argument(
        "--no-open", action="store_true", help="Do not open the browser automatically"
    )
    parser.add_argument(
        "--project",
        type=Path,
        help="Open a local mardas.toml project workspace with safe file editing and Book Mode tools.",
    )
    parser.add_argument(
        "--render-workers",
        type=int,
        choices=range(1, 9),
        default=MAX_STUDIO_CONCURRENT_EXPORTS,
        metavar="N",
        help="Persistent Chromium export workers; default: 2 (allowed: 1-8).",
    )
    parser.add_argument(
        "--export-queue-size",
        type=int,
        choices=range(1, 65),
        default=DEFAULT_STUDIO_EXPORT_QUEUE_SIZE,
        metavar="N",
        help="Maximum queued Studio exports; default: 6 (allowed: 1-64).",
    )
    parser.add_argument(
        "--render-idle-timeout",
        type=float,
        default=DEFAULT_STUDIO_RENDER_IDLE_TIMEOUT,
        metavar="SECONDS",
        help="Close idle Chromium workers after this many seconds; default: 60.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.render_idle_timeout < 1:
        parser.error("--render-idle-timeout must be at least one second")
    project_workspace: ProjectWorkspace | None = None
    if args.project is not None:
        try:
            project_workspace = load_workspace(args.project)
        except WorkspaceError as exc:
            parser.error(str(exc))

    server = _create_studio_server(args.host, args.port)
    server.studio_bind_host = args.host  # type: ignore[attr-defined]
    server.studio_csrf_token = secrets.token_urlsafe(32)  # type: ignore[attr-defined]
    server.studio_preview_state_lock = threading.Lock()  # type: ignore[attr-defined]
    server.studio_preview_render_lock = threading.Lock()  # type: ignore[attr-defined]
    server.studio_latest_preview_ids = {}  # type: ignore[attr-defined]
    export_manager = StudioExportManager(
        workers=args.render_workers,
        queue_size=args.export_queue_size,
        idle_timeout=args.render_idle_timeout,
    )
    server.studio_export_manager = export_manager  # type: ignore[attr-defined]
    server.studio_project_workspace = project_workspace  # type: ignore[attr-defined]
    url = _studio_url(args.host, server.server_port)
    print(f"Mardas Folio is running at {url}")
    if project_workspace is not None:
        print(f"Project workspace: {project_workspace.root}")
    warning = _studio_bind_warning(args.host)
    if warning:
        print(f"WARNING: {warning}")
    print("Press Ctrl+C to stop.")
    if not args.no_open:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Mardas Folio...")
    finally:
        export_manager.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

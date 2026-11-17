"""Application orchestration and the stable desktop/sidecar API facade."""

from __future__ import annotations

import json
import os
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Mapping
from urllib.parse import unquote, urlsplit

from . import __version__
from .book import (
    BookManifest,
    book_context,
    convert_book,
    load_book_manifest,
    render_book,
)
from .config import (
    load_project_config,
)
from .diagnostics import Diagnostic, has_errors
from .document_assets import (
    import_document_asset as import_document_asset,
)
from .document_assets import (
    list_document_assets as list_document_assets,
)
from .document_store import (
    MARKDOWN_DOCUMENT_EXTENSIONS as _MARKDOWN_DOCUMENT_EXTENSIONS,
)
from .document_store import (
    MAX_DOCUMENT_BYTES as MAX_DOCUMENT_BYTES,
)
from .document_store import (
    read_document as read_document,
)
from .document_store import (
    read_text_document as read_text_document,
)
from .document_store import (
    save_document as save_document,
)
from .document_store import (
    save_text_document as save_text_document,
)
from .engine_errors import (
    EngineError as EngineError,
)
from .engine_errors import (
    EngineValidationError as EngineValidationError,
)
from .file_io import atomic_write_text as _atomic_write_text
from .markdown import (
    MarkdownInputError,
    MarkdownRenderResult,
    render_markdown_file,
    render_markdown_text,
)
from .protocol import PROTOCOL_NAME, PROTOCOL_VERSION
from .render_requests import (
    OPTION_FIELDS as _OPTION_FIELDS,
)
from .render_requests import (
    path_value as _path_value,
)
from .render_requests import (
    pdf_options_from_request as pdf_options_from_request,
)
from .renderer import (
    OutputExistsError,
    OutputPathError,
    OutputSidecarUnsupportedError,
    PdfOptions,
    RenderSession,
    build_html,
    convert,
    preview_appearance_payload,
    preview_page_payload,
)
from .request_validation import (
    mapping as _mapping,
)
from .request_validation import (
    optional_bool as _optional_bool,
)
from .request_validation import (
    optional_int as _optional_int,
)
from .request_validation import (
    optional_string as _optional_string,
)
from .request_validation import (
    required_content as _required_content,
)
from .request_validation import (
    required_string as _required_string,
)
from .request_validation import (
    string_list as _string_list,
)
from .request_validation import (
    validate_params as _validate_params,
)
from .runtime import runtime_info
from .support import SupportBundleError, create_support_bundle
from .workspace import (
    ProjectWorkspace,
    WorkspaceError,
    add_workspace_book_chapter,
    create_book_workspace,
    duplicate_workspace_book_chapter,
    export_workspace_book_pdf,
    load_workspace,
    read_workspace_file,
    remove_workspace_book_chapter,
    render_workspace_book_html,
    reorder_workspace_book_chapters,
    search_workspace,
    validate_workspace_book_payload,
    workspace_bibliography,
    workspace_payload,
    write_workspace_file,
)

ProgressCallback = Callable[[str, float], None]
CancellationCallback = Callable[[], bool]
# 1.6.0 adds `page.background` to the `preview.document_page` result: the colour
# the printed sheet itself is, which a client drawing paper cannot derive. It is
# additive, so an older client keeps working against a newer engine.
ENGINE_API_VERSION = "1.6.0"


def _paths_refer_to_same_file(left: Path, right: Path) -> bool:
    """Detect textual aliases, symlinks, hardlinks, and case-folded path aliases."""

    left = Path(left).expanduser()
    right = Path(right).expanduser()
    try:
        if left.exists() and right.exists() and os.path.samefile(left, right):
            return True
    except OSError:
        pass
    return os.path.normcase(str(left.resolve(strict=False))) == os.path.normcase(
        str(right.resolve(strict=False))
    )


def resolve_markdown_link(
    document_path: str | os.PathLike[str],
    href: str,
    *,
    project_path: str | os.PathLike[str] | None = None,
) -> dict[str, str | None]:
    """Resolve a relative Markdown link without opening arbitrary local paths."""

    parsed = urlsplit(href.strip())
    if parsed.scheme or parsed.netloc or parsed.query:
        raise EngineError(
            "Only relative Markdown file links are supported here.",
            code="MARDAS-LINK-UNSUPPORTED",
        )
    try:
        relative = unquote(parsed.path, errors="strict")
        fragment = unquote(parsed.fragment, errors="strict")
    except (UnicodeDecodeError, ValueError) as exc:
        raise EngineError(
            "The linked Markdown path is not valid URL encoding.",
            code="MARDAS-LINK-INVALID",
        ) from exc
    if (
        not relative
        or "\x00" in relative
        or "\\" in relative
        or relative.startswith("/")
        or PureWindowsPath(relative).is_absolute()
        or PureWindowsPath(relative).drive
    ):
        raise EngineError(
            "The linked path must be a relative Markdown file.",
            code="MARDAS-LINK-UNSUPPORTED",
        )
    if Path(relative).suffix.casefold() not in _MARKDOWN_DOCUMENT_EXTENSIONS:
        raise EngineError(
            "Only Markdown file links are supported in the document preview.",
            code="MARDAS-LINK-UNSUPPORTED",
        )

    try:
        source = Path(document_path).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise EngineError(
            "The current document is no longer available.",
            code="MARDAS-LINK-CONTEXT",
        ) from exc
    if not source.is_file() or source.suffix.casefold() not in _MARKDOWN_DOCUMENT_EXTENSIONS:
        raise EngineError(
            "Links can only be opened from a saved Markdown document.",
            code="MARDAS-LINK-CONTEXT",
        )

    workspace = _load_workspace_request(str(project_path)) if project_path else None
    root = workspace.root if workspace is not None else source.parent
    if not source.is_relative_to(root):
        raise EngineError(
            "The current document is outside the linked project.",
            code="MARDAS-LINK-CONTEXT",
        )
    try:
        target = (source.parent / relative).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise EngineError(
            "The linked Markdown file could not be found.",
            code="MARDAS-LINK-NOT-FOUND",
            details={"href": href},
        ) from exc
    if not target.is_relative_to(root):
        raise EngineError(
            "The linked Markdown file is outside the current document folder or project.",
            code="MARDAS-LINK-OUTSIDE-ROOT",
        )
    if not target.is_file() or target.suffix.casefold() not in _MARKDOWN_DOCUMENT_EXTENSIONS:
        raise EngineError(
            "Only existing Markdown files can be opened from the preview.",
            code="MARDAS-LINK-UNSUPPORTED",
        )

    relative_path: str | None = None
    if workspace is not None:
        relative_path = target.relative_to(root).as_posix()
        payload = _workspace_call(lambda: read_workspace_file(workspace, relative_path))
        if payload.get("kind") != "markdown":
            raise EngineError(
                "The linked file is not part of the project's Markdown documents.",
                code="MARDAS-LINK-UNSUPPORTED",
            )
        target = root / relative_path
    return {"path": str(target), "relative_path": relative_path, "fragment": fragment}


def render_document(options: PdfOptions, *, session: RenderSession | None = None) -> dict[str, Any]:
    """Render one document through the common application API used by CLI/sidecar."""

    try:
        output = convert(options, session=session)
    except OutputExistsError as exc:
        raise EngineError(str(exc), code="MARDAS-OUTPUT-EXISTS") from exc
    except OutputSidecarUnsupportedError as exc:
        raise EngineError(str(exc), code="MARDAS-OUTPUT-SIDECAR-UNSUPPORTED") from exc
    except OutputPathError as exc:
        raise EngineError(str(exc), code="MARDAS-OUTPUT-PATH-COLLISION") from exc
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
    encoded = json.dumps(value, ensure_ascii=True, default=str)
    return json.loads(encoded, parse_constant=lambda _value: None)


def _document_summary(result: MarkdownRenderResult) -> dict[str, Any]:
    return {
        "title": result.title,
        "headings": len(result.toc_entries),
        "metadata_keys": sorted(str(key) for key in result.metadata),
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
        "appearance": preview_appearance_payload(result.metadata, options),
    }


def preview_page_document_text(options: PdfOptions, content: str) -> dict[str, Any]:
    """Return the published page itself, laid out as the exporter will print it.

    ``preview.document_text`` answers "what does the body look like"; this
    answers "what will the PDF look like", which is a different question and the
    only one the export screen is actually asking. Cover, contents, watermark
    and running footer come back with the page geometry so the caller can draw
    real sheets instead of a scrolling article.
    """

    result = _render_markdown_text_for_options(options, content)
    if has_errors(result.diagnostics):
        raise EngineValidationError("Document validation failed.", result.diagnostics)
    payload = preview_page_payload(result, options)
    payload["diagnostics"] = [item.to_dict() for item in result.diagnostics]
    payload["document"] = _document_summary(result)
    return payload


def preview_document(options: PdfOptions, *, output_path: Path) -> dict[str, Any]:
    target = Path(output_path).expanduser().resolve(strict=False)
    if _paths_refer_to_same_file(options.input_path, target):
        raise EngineError(
            "Preview HTML and input Markdown paths must reference different files.",
            code="MARDAS-PREVIEW-PATH-COLLISION",
            details={"input_path": str(options.input_path), "output_path": str(target)},
        )
    if target.suffix.casefold() not in {".htm", ".html"}:
        raise EngineError(
            "Preview output must use the .html or .htm extension.",
            code="MARDAS-PREVIEW-OUTPUT-TYPE",
            details={"output_path": str(target)},
        )
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
    _atomic_write_text(target, html_text)
    return {
        "output_path": str(target),
        "size_bytes": target.stat().st_size,
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
        info = runtime_info(resolve_browser=True)
        runtime_payload = info.to_dict()
        runtime_payload["resolved_chromium_path"] = (
            str(info.chromium_path) if info.chromium_path else None
        )
        return {
            "status": "ok",
            "engine_version": __version__,
            "engine_api_version": ENGINE_API_VERSION,
            "protocol": PROTOCOL_NAME,
            "protocol_version": PROTOCOL_VERSION,
            "runtime": runtime_payload,
            "chromium_available": bool(info.chromium_path),
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
                "system.support_bundle",
                "job.cancel",
                "document.read",
                "document.read_text",
                "document.save",
                "document.save_text",
                "document.list_assets",
                "document.import_asset",
                "document.resolve_markdown_link",
                "project.open",
                "project.refresh",
                "project.read",
                "project.save",
                "project.search",
                "bibliography.index",
                "book.create",
                "book.add_chapter",
                "book.duplicate_chapter",
                "book.reorder_chapters",
                "book.remove_chapter",
                "book.validate",
                "book.preview",
                "book.export",
                "publication.inspect_output",
                "render.document",
                "render.book",
                "preview.document",
                "preview.document_text",
                "preview.document_page",
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
        """Route each request to its use-case family; transport controls live in the sidecar."""
        handlers = {
            "system": self._dispatch_system,
            "document": self._dispatch_documents,
            "project": self._dispatch_projects,
            "bibliography": self._dispatch_projects,
            "book": self._dispatch_books,
            "publication": self._dispatch_publication,
            "render": self._dispatch_publication,
            "preview": self._dispatch_publication,
            "validate": self._dispatch_publication,
        }
        handler = handlers.get(method.partition(".")[0])
        if handler is None:
            raise _unsupported_method(method)
        return handler(method, params, progress=progress, cancelled=cancelled)

    def _dispatch_system(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        progress: ProgressCallback | None = None,
        cancelled: CancellationCallback | None = None,
    ) -> dict[str, Any]:
        if method == "system.support_bundle":
            _validate_params(params, {"output_path"})
            try:
                return create_support_bundle(
                    Path(_required_string(params, "output_path")),
                    engine_api_version=ENGINE_API_VERSION,
                )
            except SupportBundleError as exc:
                raise EngineError(
                    str(exc),
                    code="MARDAS-SUPPORT-BUNDLE-ERROR",
                ) from exc
        raise _unsupported_method(method)

    def _dispatch_documents(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        progress: ProgressCallback | None = None,
        cancelled: CancellationCallback | None = None,
    ) -> dict[str, Any]:
        if method in {"document.read", "document.read_text"}:
            _validate_params(params, {"path"})
            read = read_document if method == "document.read" else read_text_document
            return read(_required_string(params, "path"))
        if method in {"document.save", "document.save_text"}:
            _validate_params(params, {"path", "content", "expected_revision", "force"})
            force = _optional_bool(params, "force", default=False)
            expected_revision = _optional_string(params, "expected_revision")
            save = save_document if method == "document.save" else save_text_document
            return save(
                _required_string(params, "path"),
                _required_content(params),
                expected_revision=expected_revision,
                force=force,
            )
        if method == "document.list_assets":
            _validate_params(params, {"path"})
            return list_document_assets(_required_string(params, "path"), cancelled=cancelled)
        if method == "document.import_asset":
            _validate_params(params, {"document_path", "source_path"})
            return import_document_asset(
                _required_string(params, "document_path"),
                _required_string(params, "source_path"),
            )
        if method == "document.resolve_markdown_link":
            _validate_params(params, {"document_path", "href", "project_path"})
            return resolve_markdown_link(
                _required_string(params, "document_path"),
                _required_string(params, "href"),
                project_path=_optional_string(params, "project_path"),
            )
        raise _unsupported_method(method)

    def _dispatch_projects(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        progress: ProgressCallback | None = None,
        cancelled: CancellationCallback | None = None,
    ) -> dict[str, Any]:
        if method in {"project.open", "project.refresh"}:
            _validate_params(params, {"path"})
            workspace = _load_workspace_request(
                _required_string(params, "path"),
                cancelled=cancelled,
                validate_content=True,
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
            payload = _workspace_call(lambda: read_workspace_file(workspace, relative_path))
            absolute_path = (workspace.root / str(payload["path"])).resolve(strict=False)
            payload["absolute_path"] = str(absolute_path)
            payload["revision"] = f"{payload['mtime_ns']}:{payload['size']}:{payload['sha256']}"
            payload["read_only"] = not os.access(absolute_path, os.W_OK)
            return payload
        if method == "project.save":
            _validate_params(
                params,
                {"project_path", "relative_path", "content", "expected_sha256"},
            )
            content = _required_content(params)
            # Reject malformed request text before a cancellable project scan.
            # Shutdown may cancel discovery, but must not hide invalid content.
            try:
                content.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise _workspace_error(
                    WorkspaceError(
                        "Project file content must be valid UTF-8 text.",
                        code="invalid_project_content",
                    )
                ) from exc
            workspace = _load_workspace_request(
                _required_string(params, "project_path"),
                cancelled=cancelled,
            )
            relative_path = _required_string(params, "relative_path")
            payload = _workspace_call(
                lambda: write_workspace_file(
                    workspace,
                    relative_path,
                    content,
                    expected_sha256=_required_string(params, "expected_sha256"),
                )
            )
            absolute_path = (workspace.root / str(payload["path"])).resolve(strict=False)
            payload["absolute_path"] = str(absolute_path)
            payload["revision"] = f"{payload['mtime_ns']}:{payload['size']}:{payload['sha256']}"
            payload["read_only"] = not os.access(absolute_path, os.W_OK)
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
                    case_sensitive=_optional_bool(params, "case_sensitive", default=False),
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
        raise _unsupported_method(method)

    def _dispatch_books(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        progress: ProgressCallback | None = None,
        cancelled: CancellationCallback | None = None,
    ) -> dict[str, Any]:
        if method == "book.create":
            _validate_params(
                params,
                {"parent_path", "folder_name", "title", "language", "direction"},
            )
            try:
                workspace = create_book_workspace(
                    Path(_required_string(params, "parent_path")),
                    folder_name=_required_string(params, "folder_name"),
                    title=_required_string(params, "title"),
                    language=_optional_string(params, "language") or "fa-IR",
                    direction=_optional_string(params, "direction") or "auto",
                )
            except WorkspaceError as exc:
                raise _workspace_error(exc) from exc
            payload = workspace_payload(workspace)
            payload["path"] = str(workspace.root)
            return payload
        if method == "book.add_chapter":
            _validate_params(
                params,
                {
                    "project_path",
                    "title",
                    "expected_config_sha256",
                    "position",
                    "content",
                },
            )
            workspace = _load_workspace_request(
                _required_string(params, "project_path"),
                cancelled=cancelled,
            )
            position_value = params.get("position")
            position = (
                _optional_int(
                    params,
                    "position",
                    default=0,
                    minimum=0,
                    maximum=500,
                )
                if position_value is not None
                else None
            )
            try:
                refreshed, chapter = add_workspace_book_chapter(
                    workspace,
                    title=_required_string(params, "title"),
                    expected_config_sha256=_required_string(params, "expected_config_sha256"),
                    position=position,
                    content=(
                        _required_content(params) if params.get("content") is not None else None
                    ),
                )
            except WorkspaceError as exc:
                raise _workspace_error(exc) from exc
            payload = workspace_payload(refreshed)
            payload["path"] = str(refreshed.root)
            payload["created_chapter"] = chapter
            return payload
        if method == "book.duplicate_chapter":
            _validate_params(
                params,
                {
                    "project_path",
                    "relative_path",
                    "title",
                    "expected_config_sha256",
                },
            )
            workspace = _load_workspace_request(
                _required_string(params, "project_path"),
                cancelled=cancelled,
            )
            try:
                refreshed, chapter = duplicate_workspace_book_chapter(
                    workspace,
                    relative_path=_required_string(params, "relative_path"),
                    title=_optional_string(params, "title"),
                    expected_config_sha256=_required_string(params, "expected_config_sha256"),
                )
            except WorkspaceError as exc:
                raise _workspace_error(exc) from exc
            payload = workspace_payload(refreshed)
            payload["path"] = str(refreshed.root)
            payload["created_chapter"] = chapter
            return payload
        if method == "book.reorder_chapters":
            _validate_params(
                params,
                {"project_path", "ordered_paths", "expected_config_sha256"},
            )
            workspace = _load_workspace_request(
                _required_string(params, "project_path"),
                cancelled=cancelled,
            )
            try:
                refreshed = reorder_workspace_book_chapters(
                    workspace,
                    ordered_paths=_string_list(params.get("ordered_paths", ()), "ordered_paths"),
                    expected_config_sha256=_required_string(params, "expected_config_sha256"),
                )
            except WorkspaceError as exc:
                raise _workspace_error(exc) from exc
            payload = workspace_payload(refreshed)
            payload["path"] = str(refreshed.root)
            return payload
        if method == "book.remove_chapter":
            _validate_params(
                params,
                {
                    "project_path",
                    "relative_path",
                    "expected_config_sha256",
                },
            )
            workspace = _load_workspace_request(
                _required_string(params, "project_path"),
                cancelled=cancelled,
            )
            try:
                refreshed = remove_workspace_book_chapter(
                    workspace,
                    relative_path=_required_string(params, "relative_path"),
                    expected_config_sha256=_required_string(params, "expected_config_sha256"),
                )
            except WorkspaceError as exc:
                raise _workspace_error(exc) from exc
            payload = workspace_payload(refreshed)
            payload["path"] = str(refreshed.root)
            return payload
        if method == "book.validate":
            _validate_params(params, {"project_path"})
            workspace = _load_workspace_request(
                _required_string(params, "project_path"),
                cancelled=cancelled,
            )
            try:
                payload, refreshed = validate_workspace_book_payload(
                    workspace,
                    progress=progress,
                    cancelled=cancelled,
                )
            except WorkspaceError as exc:
                raise _workspace_error(exc) from exc
            payload["project"] = workspace_payload(refreshed)
            payload["project"]["path"] = str(refreshed.root)
            return payload
        if method == "book.preview":
            _validate_params(params, {"project_path"})
            workspace = _load_workspace_request(
                _required_string(params, "project_path"),
                cancelled=cancelled,
            )
            try:
                html, refreshed = render_workspace_book_html(
                    workspace,
                    progress=progress,
                    cancelled=cancelled,
                )
            except WorkspaceError as exc:
                raise _workspace_error(exc) from exc
            project = workspace_payload(refreshed)
            project["path"] = str(refreshed.root)
            return {"html": html, "project": project}
        if method == "book.export":
            _validate_params(params, {"project_path", "output_path", "create_only"})
            workspace = _load_workspace_request(
                _required_string(params, "project_path"),
                cancelled=cancelled,
            )
            output_path = Path(_required_string(params, "output_path")).expanduser()
            try:
                built, suggested_name, refreshed = export_workspace_book_pdf(
                    workspace,
                    output_path,
                    session=self._render_session(),
                    progress=progress,
                    cancelled=cancelled,
                    create_only=_optional_bool(params, "create_only", default=False),
                )
            except WorkspaceError as exc:
                raise _workspace_error(exc) from exc
            except OutputExistsError as exc:
                raise EngineError(str(exc), code="MARDAS-OUTPUT-EXISTS") from exc
            except OutputSidecarUnsupportedError as exc:
                raise EngineError(str(exc), code="MARDAS-OUTPUT-SIDECAR-UNSUPPORTED") from exc
            except OutputPathError as exc:
                raise EngineError(str(exc), code="MARDAS-OUTPUT-PATH-COLLISION") from exc
            project = workspace_payload(refreshed)
            project["path"] = str(refreshed.root)
            return {
                "output_path": str(built),
                "size_bytes": built.stat().st_size,
                "suggested_name": suggested_name,
                "project": project,
            }
        raise _unsupported_method(method)

    def _dispatch_publication(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        progress: ProgressCallback | None = None,
        cancelled: CancellationCallback | None = None,
    ) -> dict[str, Any]:
        if method == "publication.inspect_output":
            _validate_params(params, {"output_path"})
            candidate = Path(_required_string(params, "output_path")).expanduser()
            if candidate.suffix.casefold() != ".pdf":
                raise EngineError(
                    "Output must use the .pdf extension.", code="MARDAS-INVALID-PARAMS"
                )
            return {"exists": os.path.lexists(candidate)}
        if method == "render.document":
            _validate_params(
                params,
                {
                    "input_path",
                    "output_path",
                    "config_path",
                    "discover_config",
                    "options",
                    "create_only",
                },
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
            options.output_create_only = _optional_bool(params, "create_only", default=False)
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
        if method in {
            "validate.document_text",
            "preview.document_text",
            "preview.document_page",
        }:
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
            if method == "preview.document_page":
                return preview_page_document_text(options, content)
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
            allowed = (
                {"config_path"}
                if method == "validate.book"
                else {"config_path", "output_path", "debug_html"}
            )
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
                debug_html=(_path_value(debug_value, base_dir=base_dir) if debug_value else None),
                progress=progress,
                cancelled=cancelled,
                session=self._render_session(),
            )
        raise _unsupported_method(method)


def _unsupported_method(method: str) -> EngineError:
    return EngineError(
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
    validate_content: bool = False,
) -> ProjectWorkspace:
    try:
        return load_workspace(Path(path), cancelled=cancelled, validate_content=validate_content)
    except WorkspaceError as exc:
        raise _workspace_error(exc) from exc

from __future__ import annotations

import argparse
import os
import platform
import shutil
import sys
import tempfile
from importlib import resources
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Any, Callable

from bs4 import BeautifulSoup

from . import __version__
from .appearance import appearance_from_metadata, resolve_appearance
from .book import (
    BookManifest,
    BookRenderBundle,
    book_context,
    convert_book,
    load_book_manifest,
    render_book,
)
from .config import (
    CONFIG_FILENAME,
    CONFIG_SCHEMA_VERSION,
    LoadedProjectConfig,
    default_config_text,
    load_project_config,
)
from .diagnostics import Diagnostic, format_diagnostic, has_errors, write_diagnostics
from .markdown import MarkdownInputError, render_markdown_file
from .runtime import playwright_chromium_path

PROJECT_COMMANDS = (
    "init",
    "validate",
    "doctor",
    "explain-config",
    "build-book",
    "validate-book",
    "explain-book",
    "audit-accessibility",
    "audit-book-accessibility",
    "audit-pdf",
)


def _add_config_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--config",
        type=Path,
        help=f"Use an explicit {CONFIG_FILENAME} project configuration file.",
    )
    group.add_argument(
        "--no-config",
        action="store_true",
        help=f"Disable automatic {CONFIG_FILENAME} discovery for this command.",
    )


def _init_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mrs-md2pdf init", description=f"Create a versioned {CONFIG_FILENAME} project file."
    )
    parser.add_argument("directory", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument(
        "--force", action="store_true", help="Replace an existing configuration file atomically"
    )
    parser.add_argument(
        "--book",
        action="store_true",
        help="Create a starter multi-file book project with two ordered chapters",
    )
    return parser


def _init_main(argv: list[str]) -> int:
    parser = _init_parser()
    args = parser.parse_args(argv)
    directory = args.directory.expanduser().resolve()
    if directory.exists() and not directory.is_dir():
        parser.error(f"Project path is not a directory: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / CONFIG_FILENAME
    if target.exists() and not args.force:
        parser.error(f"Configuration already exists: {target}; use --force to replace it")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{CONFIG_FILENAME}.", dir=directory)
    temporary = Path(temporary_name)
    try:
        config_text = default_config_text()
        if args.book:
            config_text = config_text.replace(
                '# [book]\n# chapters = [\n#   "chapters/01-introduction.md",\n#   "chapters/02-content.md",\n# ]\n# output = "dist/book.pdf"\n# chapter_page_break = true',
                '[book]\nchapters = [\n  "chapters/01-introduction.md",\n  "chapters/02-content.md",\n]\noutput = "dist/book.pdf"\nchapter_page_break = true',
            )
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(config_text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        if args.book:
            chapters_dir = directory / "chapters"
            chapters_dir.mkdir(parents=True, exist_ok=True)
            samples = {
                chapters_dir
                / "01-introduction.md": "# Introduction\n\nStart writing your book here.\n",
                chapters_dir
                / "02-content.md": "# Main Content\n\nContinue with the next chapter.\n",
            }
            for chapter_path, content in samples.items():
                if chapter_path.exists():
                    continue
                chapter_path.write_text(content, encoding="utf-8", newline="\n")
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    print(f"Created project configuration: {target}")
    if args.book:
        print(f"Created starter book chapters: {directory / 'chapters'}")
    return 0


def _analysis_parser(command: str) -> argparse.ArgumentParser:
    descriptions = {
        "validate": "Validate project configuration and Markdown without launching Chromium.",
        "doctor": "Check the local rendering environment and project configuration.",
        "explain-config": "Show effective project settings and their sources.",
    }
    parser = argparse.ArgumentParser(
        prog=f"mrs-md2pdf {command}", description=descriptions[command]
    )
    parser.add_argument(
        "input",
        nargs="?" if command == "doctor" else None,
        type=Path,
        default=Path.cwd() if command == "doctor" else None,
    )
    _add_config_arguments(parser)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser


def _input_diagnostics(path: Path, *, required_file: bool) -> list[Diagnostic]:
    if not path.exists():
        return [Diagnostic("MARDAS-E201", "error", "Input path does not exist.", path=path)]
    if required_file and not path.is_file():
        return [
            Diagnostic("MARDAS-E202", "error", "Input must be a regular Markdown file.", path=path)
        ]
    return []


def _project_config_diagnostics(config: LoadedProjectConfig) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    path_checks = [
        ("brand_logo", "MARDAS-E113", "Configured branding logo is not a regular file."),
        ("watermark_image", "MARDAS-E114", "Configured watermark image is not a regular file."),
    ]
    for key, code, message in path_checks:
        value = config.values.get(key)
        if value is not None and not Path(value).is_file():
            diagnostics.append(Diagnostic(code, "error", message, path=Path(value)))
    for source in config.values.get("bibliography_sources", ()):
        path = Path(source)
        if not path.is_file():
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E701",
                    "error",
                    "Configured bibliography source does not exist or is not a regular file.",
                    path=path,
                )
            )

    font_dir = config.values.get("font_dir")
    if font_dir is not None and not Path(font_dir).is_dir():
        diagnostics.append(
            Diagnostic(
                "MARDAS-E115",
                "error",
                "Configured font directory does not exist or is not a directory.",
                path=Path(font_dir),
            )
        )
    if config.values.get("unsafe_html") is True:
        diagnostics.append(
            Diagnostic(
                "MARDAS-W301",
                "warning",
                "Project configuration enables unsanitized raw HTML.",
                path=config.path,
                hint="Keep security.unsafe_html=false for untrusted Markdown.",
            )
        )
    if config.values.get("allow_remote_assets") is True:
        diagnostics.append(
            Diagnostic(
                "MARDAS-W302",
                "warning",
                "Project configuration permits remote network assets.",
                path=config.path,
                hint="Remote assets can disclose network metadata and make builds non-reproducible.",
            )
        )
    return diagnostics


def _load_analysis_config(
    args: argparse.Namespace, path: Path
) -> tuple[LoadedProjectConfig, list[Diagnostic]]:
    result = load_project_config(start=path, explicit_path=args.config, disabled=args.no_config)
    diagnostics = list(result.diagnostics)
    if not has_errors(diagnostics):
        diagnostics.extend(_project_config_diagnostics(result.config))
    return result.config, diagnostics


def _validate_document(
    path: Path,
    config: LoadedProjectConfig,
    *,
    document_root: Path | None = None,
    defer_reference_resolution: bool = False,
    defer_citation_resolution: bool = False,
) -> tuple[list[Diagnostic], dict[str, Any]]:
    diagnostics: list[Diagnostic] = []
    values = config.values
    try:
        result = render_markdown_file(
            path,
            toc=bool(values.get("toc", False)),
            toc_depth=int(values.get("toc_depth", 6)),
            language=values.get("document_language"),
            unsafe_html=bool(values.get("unsafe_html", False)),
            allow_remote_images=bool(values.get("allow_remote_assets", False)),
            document_root=document_root,
            references_enabled=values.get("references_enabled"),
            numbering_scope=values.get("numbering_scope"),
            list_of_figures=values.get("list_of_figures"),
            list_of_tables=values.get("list_of_tables"),
            list_of_equations=values.get("list_of_equations"),
            list_of_listings=values.get("list_of_listings"),
            defer_reference_resolution=defer_reference_resolution,
            citations_enabled=values.get("citations_enabled"),
            bibliography_sources=values.get("bibliography_sources"),
            citation_style=values.get("citation_style"),
            bibliography_title=values.get("bibliography_title"),
            bibliography_include_uncited=values.get("bibliography_include_uncited"),
            defer_citation_resolution=defer_citation_resolution,
        )
    except (MarkdownInputError, OSError, UnicodeError, ValueError) as exc:
        diagnostics.append(
            Diagnostic(
                "MARDAS-E203",
                "error",
                str(exc),
                path=path,
                hint="Fix the Markdown/front matter error and run validation again.",
            )
        )
        return diagnostics, {}

    if not values.get("title") and not result.metadata.get("title") and result.title == "Document":
        diagnostics.append(
            Diagnostic(
                "MARDAS-W201",
                "warning",
                "Document has no explicit title or level-one heading.",
                path=path,
                hint="Add `title` to front matter or add a `# Heading`.",
            )
        )
    if not defer_reference_resolution:
        diagnostics.extend(result.diagnostics)
    soup = BeautifulSoup(result.body_html, "html.parser")
    for placeholder in soup.select(".md2pdf-image-placeholder[data-md2pdf-blocked-src]"):
        source = str(placeholder.get("data-md2pdf-blocked-src") or "").strip()
        reason = str(placeholder.get("data-md2pdf-blocked-reason") or "").strip()
        code = "MARDAS-W203" if reason == "local" else "MARDAS-W204"
        message = (
            f"Local image could not be embedded: {source}"
            if reason == "local"
            else f"Remote image is blocked by project policy: {source}"
        )
        diagnostics.append(
            Diagnostic(
                code,
                "warning",
                message,
                path=path,
                hint=(
                    "Keep the image inside the document directory and verify its path."
                    if reason == "local"
                    else "Use a local image or explicitly enable security.allow_remote_assets for trusted projects."
                ),
            )
        )

    previous_level: int | None = None
    for level, title, _heading_id, _number in result.toc_entries:
        if previous_level is not None and level > previous_level + 1:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-W202",
                    "warning",
                    f"Heading hierarchy jumps from level {previous_level} to level {level}: {title}",
                    path=path,
                    hint="Use consecutive heading levels for a clearer document outline.",
                )
            )
        previous_level = level
    return diagnostics, {
        "title": values.get("title") or result.metadata.get("title") or result.title,
        "headings": len(result.toc_entries),
        "metadata_keys": sorted(result.metadata),
        "numbered_objects": len(result.reference_objects),
        "cited_entries": len(result.cited_keys),
        "bibliography_entries": len(result.citation_entries),
    }


def _validate_main(argv: list[str]) -> int:
    parser = _analysis_parser("validate")
    args = parser.parse_args(argv)
    input_path = args.input.expanduser().resolve()
    diagnostics = _input_diagnostics(input_path, required_file=True)
    config, config_diagnostics = _load_analysis_config(args, input_path)
    diagnostics.extend(config_diagnostics)
    document_context: dict[str, Any] = {}
    if not has_errors(diagnostics):
        document_diagnostics, document_context = _validate_document(input_path, config)
        diagnostics.extend(document_diagnostics)
    context = {
        "command": "validate",
        "input": str(input_path),
        "config": str(config.path) if config.path else None,
        "schema_version": CONFIG_SCHEMA_VERSION,
        "document": document_context,
    }
    write_diagnostics(diagnostics, output_format=args.format, stream=sys.stdout, context=context)
    return 1 if has_errors(diagnostics) else 0


def _doctor_main(argv: list[str]) -> int:
    parser = _analysis_parser("doctor")
    args = parser.parse_args(argv)
    target = args.input.expanduser().resolve()
    diagnostics = _input_diagnostics(target, required_file=False)
    config, config_diagnostics = _load_analysis_config(args, target)
    diagnostics.extend(config_diagnostics)
    if config.values.get("book_chapters") and not has_errors(diagnostics):
        _manifest, book_diagnostics = load_book_manifest(config)
        diagnostics.extend(book_diagnostics)

    if sys.version_info < (3, 10):
        diagnostics.append(
            Diagnostic(
                "MARDAS-E403",
                "error",
                "Python 3.10 or newer is required.",
                hint="Install a supported Python runtime before rendering documents.",
            )
        )

    chromium = shutil.which("chromium") or shutil.which("google-chrome") or shutil.which("chrome")
    if not chromium:
        managed_browser = playwright_chromium_path()
        if managed_browser is not None:
            chromium = str(managed_browser)
    configured_chromium = config.values.get("chromium_path")
    if configured_chromium:
        configured_path = Path(configured_chromium)
        if configured_path.is_file():
            chromium = str(configured_path)
        else:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E401",
                    "error",
                    "Configured Chromium executable does not exist.",
                    path=configured_path,
                )
            )
    if not chromium:
        diagnostics.append(
            Diagnostic(
                "MARDAS-W401",
                "warning",
                "No system Chromium/Chrome executable was found on PATH.",
                hint="Run `playwright install chromium` or configure browser.chromium_path.",
            )
        )

    mathjax_path = resources.files("mardas_md2pdf") / "assets" / "mathjax" / "tex-svg-full.js"
    if not mathjax_path.is_file():
        diagnostics.append(
            Diagnostic(
                "MARDAS-E402",
                "error",
                "Vendored MathJax asset is missing from the installed package.",
            )
        )

    if target.is_file() and not has_errors(diagnostics):
        document_diagnostics, _ = _validate_document(target, config)
        diagnostics.extend(document_diagnostics)

    dependency_versions: dict[str, str] = {}
    for distribution in ("playwright", "pypdf", "markdown-it-py", "beautifulsoup4", "PyYAML"):
        try:
            dependency_versions[distribution] = package_version(distribution)
        except PackageNotFoundError:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E404",
                    "error",
                    f"Required dependency is not installed: {distribution}",
                )
            )

    context = {
        "command": "doctor",
        "version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "input": str(target),
        "config": str(config.path) if config.path else None,
        "chromium": chromium,
        "mathjax": str(mathjax_path),
        "dependencies": dependency_versions,
    }
    write_diagnostics(diagnostics, output_format=args.format, stream=sys.stdout, context=context)
    return 1 if has_errors(diagnostics) else 0


def _metadata_value(metadata: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = metadata.get(key)
        if value not in (None, ""):
            return value
    return None


def _display_config_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _display_config_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_display_config_value(item) for item in value]
    return value


def _effective_config(input_path: Path, config: LoadedProjectConfig) -> dict[str, dict[str, Any]]:
    result = render_markdown_file(
        input_path,
        toc=bool(config.values.get("toc", False)),
        toc_depth=int(config.values.get("toc_depth", 6)),
        unsafe_html=bool(config.values.get("unsafe_html", False)),
        allow_remote_images=bool(config.values.get("allow_remote_assets", False)),
    )
    metadata = result.metadata
    metadata_appearance = appearance_from_metadata(metadata)
    raw_appearance = (
        metadata.get("appearance") if isinstance(metadata.get("appearance"), dict) else {}
    )
    appearance = resolve_appearance(
        style=config.values.get("style") or metadata_appearance.style,
        palette=config.values.get("palette") or metadata_appearance.palette,
        mode=config.values.get("mode") or metadata_appearance.mode,
    )
    metadata_branding = (
        metadata.get("branding") if isinstance(metadata.get("branding"), dict) else {}
    )
    metadata_direction = _metadata_value(
        metadata, "dir", "direction", "text_direction", "document_direction"
    )
    raw_references = metadata.get("references")
    metadata_references = raw_references if isinstance(raw_references, dict) else {}
    raw_citations = metadata.get("citations")
    metadata_citations = raw_citations if isinstance(raw_citations, dict) else {}

    defaults: dict[str, Any] = {
        "toc": False,
        "toc_depth": 6,
        "toc_page_break": False,
        "h1_page_break": False,
        "page_size": "A4",
        "margin_top": "18mm",
        "margin_bottom": "20mm",
        "margin_x": "16mm",
        "cover": True,
        "header_footer": True,
        "mathjax": True,
        "unsafe_html": False,
        "allow_remote_assets": False,
        "timeout_ms": 120_000,
        "chromium_sandbox": "auto",
        "show_logo": True,
        "watermark": None,
        "watermark_opacity": 0.065,
        "watermark_width": "105mm",
        "font_dir": None,
        "chromium_path": None,
        "references_enabled": False,
        "numbering_scope": "global",
        "list_of_figures": False,
        "list_of_tables": False,
        "list_of_equations": False,
        "list_of_listings": False,
        "citations_enabled": False,
        "bibliography_sources": [],
        "citation_style": "author-date",
        "bibliography_title": None,
        "bibliography_include_uncited": False,
    }
    effective: dict[str, dict[str, Any]] = {}

    def add(name: str, value: Any, source: str) -> None:
        effective[name] = {
            "value": _display_config_value(value),
            "source": source,
        }

    citation_metadata_keys = {
        "citations_enabled": "enabled",
        "citation_style": "style",
        "bibliography_title": "bibliography_title",
        "bibliography_include_uncited": "include_uncited",
    }
    for key, default in defaults.items():
        internal_key = {
            "cover": "no_cover",
            "header_footer": "no_header_footer",
            "mathjax": "no_mathjax",
        }.get(key, key)
        if internal_key in config.values:
            raw = config.values[internal_key]
            value = not raw if internal_key.startswith("no_") else raw
            add(key, value, str(config.path))
            continue
        if key == "bibliography_sources":
            raw_sources = metadata.get("bibliography") or metadata_citations.get("sources")
            if raw_sources not in (None, "", []):
                add(key, raw_sources, "front matter")
            else:
                add(key, default, "built-in default")
            continue
        if key in citation_metadata_keys:
            metadata_key = citation_metadata_keys[key]
            if metadata_key in metadata_citations:
                add(key, metadata_citations[metadata_key], "front matter")
            elif key == "citations_enabled" and isinstance(raw_citations, bool):
                add(key, raw_citations, "front matter")
            else:
                add(key, default, "built-in default")
            continue
        metadata_key = "enabled" if key == "references_enabled" else key
        if metadata_key in metadata_references:
            add(key, metadata_references[metadata_key], "front matter")
        elif key == "references_enabled" and isinstance(raw_references, bool):
            add(key, raw_references, "front matter")
        elif key == "numbering_scope" and "numbering" in metadata_references:
            add(key, metadata_references["numbering"], "front matter")
        else:
            add(key, default, "built-in default")

    metadata_fields = {
        "title": _metadata_value(metadata, "title"),
        "author": _metadata_value(metadata, "authors", "author"),
        "description": _metadata_value(metadata, "description", "summary", "subject"),
        "direction": metadata_direction or "auto",
    }
    config_destinations = {
        "title": "title",
        "author": "author",
        "description": "description",
        "direction": "document_direction",
    }
    for name, metadata_value in metadata_fields.items():
        dest = config_destinations[name]
        if dest in config.values:
            add(name, config.values[dest], str(config.path))
        elif metadata_value not in (None, ""):
            add(name, metadata_value, "front matter")
        else:
            add(name, None if name != "direction" else "auto", "built-in default")

    for name, value in (
        ("style", appearance.style),
        ("palette", appearance.palette),
        ("mode", appearance.mode),
    ):
        metadata_explicit = name in raw_appearance or name in metadata
        source = (
            str(config.path)
            if name in config.values
            else "front matter"
            if metadata_explicit
            else "built-in default"
        )
        add(name, value, source)

    branding_value = config.values.get("branding")
    if branding_value is not None:
        add("branding", branding_value, str(config.path))
    elif metadata_branding.get("mode") or metadata.get("branding"):
        add("branding", metadata_branding.get("mode") or metadata.get("branding"), "front matter")
    else:
        add("branding", "off", "built-in default")

    for dest, value in sorted(config.values.items()):
        public_name = {
            "document_direction": "direction",
            "no_cover": "cover",
            "no_header_footer": "header_footer",
            "no_mathjax": "mathjax",
            "no_cover_logo": "show_logo",
        }.get(dest, dest)
        if public_name in effective:
            continue
        add(public_name, not value if dest.startswith("no_") else value, str(config.path))
    return dict(sorted(effective.items()))


def _explain_config_main(argv: list[str]) -> int:
    parser = _analysis_parser("explain-config")
    args = parser.parse_args(argv)
    input_path = args.input.expanduser().resolve()
    diagnostics = _input_diagnostics(input_path, required_file=True)
    config, config_diagnostics = _load_analysis_config(args, input_path)
    diagnostics.extend(config_diagnostics)
    effective: dict[str, dict[str, Any]] = {}
    if not has_errors(diagnostics):
        try:
            effective = _effective_config(input_path, config)
        except (MarkdownInputError, OSError, UnicodeError, ValueError) as exc:
            diagnostics.append(Diagnostic("MARDAS-E203", "error", str(exc), path=input_path))

    if args.format == "json":
        write_diagnostics(
            diagnostics,
            output_format="json",
            stream=sys.stdout,
            context={
                "command": "explain-config",
                "input": str(input_path),
                "config": str(config.path) if config.path else None,
                "schema_version": CONFIG_SCHEMA_VERSION,
                "effective": effective,
            },
        )
    else:
        print(f"Input: {input_path}")
        print(f"Config: {config.path or 'none discovered'}")
        print(f"Schema version: {CONFIG_SCHEMA_VERSION}")
        if diagnostics:
            print()
            for item in diagnostics:
                print(format_diagnostic(item))
        if effective:
            print("\nEffective settings:")
            for name, item in effective.items():
                print(f"  {name:<24} {item['value']!s:<20} [{item['source']}]")
    return 1 if has_errors(diagnostics) else 0


def _audit_parser(command: str) -> argparse.ArgumentParser:
    descriptions = {
        "audit-accessibility": "Audit Markdown accessibility without launching Chromium.",
        "audit-book-accessibility": "Audit all ordered Book Mode chapters for accessibility.",
        "audit-pdf": "Inspect PDF accessibility and archival-readiness signals.",
    }
    parser = argparse.ArgumentParser(
        prog=f"mrs-md2pdf {command}", description=descriptions[command]
    )
    parser.add_argument("input", type=Path)
    if command != "audit-pdf":
        _add_config_arguments(parser)
    else:
        parser.add_argument(
            "--profile",
            choices=["accessibility", "archival", "all"],
            default="all",
            help="Limit the PDF audit to accessibility, archival, or all readiness checks.",
        )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--fail-on",
        choices=["error", "warning", "never"],
        default="error",
        help="Choose which diagnostic severity makes the command return a non-zero status.",
    )
    return parser


def _audit_exit_status(diagnostics: list[Diagnostic], fail_on: str) -> int:
    if fail_on == "never":
        return 0
    if fail_on == "warning":
        return 1 if any(item.severity in {"error", "warning"} for item in diagnostics) else 0
    return 1 if has_errors(diagnostics) else 0


def _render_for_accessibility(
    path: Path,
    config: LoadedProjectConfig,
    *,
    document_root: Path | None = None,
    defer_reference_resolution: bool = False,
    defer_citation_resolution: bool = False,
):
    values = config.values
    return render_markdown_file(
        path,
        toc=bool(values.get("toc", False)),
        toc_depth=int(values.get("toc_depth", 6)),
        appearance_style=values.get("style"),
        appearance_mode=values.get("mode"),
        language=values.get("document_language"),
        unsafe_html=bool(values.get("unsafe_html", False)),
        allow_remote_images=bool(values.get("allow_remote_assets", False)),
        document_root=document_root,
        references_enabled=values.get("references_enabled"),
        numbering_scope=values.get("numbering_scope"),
        list_of_figures=values.get("list_of_figures"),
        list_of_tables=values.get("list_of_tables"),
        list_of_equations=values.get("list_of_equations"),
        list_of_listings=values.get("list_of_listings"),
        defer_reference_resolution=defer_reference_resolution,
        citations_enabled=values.get("citations_enabled"),
        bibliography_sources=values.get("bibliography_sources"),
        citation_style=values.get("citation_style"),
        bibliography_title=values.get("bibliography_title"),
        bibliography_include_uncited=values.get("bibliography_include_uncited"),
        defer_citation_resolution=defer_citation_resolution,
    )


def _audit_accessibility_main(argv: list[str]) -> int:
    from .accessibility import audit_markdown_result, diagnostic_counts

    parser = _audit_parser("audit-accessibility")
    args = parser.parse_args(argv)
    path = args.input.expanduser().resolve()
    diagnostics = _input_diagnostics(path, required_file=True)
    config = LoadedProjectConfig(None, path.parent, {})
    if not diagnostics:
        config, config_diagnostics = _load_analysis_config(args, path)
        diagnostics.extend(config_diagnostics)

    metrics: dict[str, object] = {}
    if not has_errors(diagnostics):
        try:
            result = _render_for_accessibility(path, config, document_root=config.root)
            diagnostics.extend(result.diagnostics)
            appearance = resolve_appearance(
                style=config.values.get("style") or appearance_from_metadata(result.metadata).style,
                palette=config.values.get("palette") or appearance_from_metadata(result.metadata).palette,
                mode=config.values.get("mode") or appearance_from_metadata(result.metadata).mode,
            )
            audit = audit_markdown_result(
                path=path,
                markdown=path.read_text(encoding="utf-8-sig"),
                result=result,
                appearance=appearance,
                configured_language=config.values.get("document_language"),
            )
            diagnostics.extend(audit.diagnostics)
            metrics = audit.metrics
        except (MarkdownInputError, OSError, UnicodeError, ValueError) as exc:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-A900",
                    "error",
                    f"Accessibility audit could not analyze the document: {exc}",
                    path=path,
                )
            )

    context = {
        "command": "audit-accessibility",
        "input": str(path),
        "summary": diagnostic_counts(diagnostics),
        "metrics": metrics,
        "compliance_claims": {
            "wcag": False,
            "pdfua": False,
            "note": "Source-level readiness checks only; manual and independent validation remain required.",
        },
    }
    write_diagnostics(diagnostics, output_format=args.format, stream=sys.stdout, context=context)
    return _audit_exit_status(diagnostics, args.fail_on)


def _audit_book_accessibility_main(argv: list[str]) -> int:
    from .accessibility import audit_markdown_result, diagnostic_counts

    parser = _audit_parser("audit-book-accessibility")
    args = parser.parse_args(argv)
    target = args.input.expanduser().resolve()
    explicit = args.config
    if target.is_file() and target.name == CONFIG_FILENAME and explicit is None:
        explicit = target
    start = target.parent if target.is_file() else target
    diagnostics = _input_diagnostics(target, required_file=False)
    result = load_project_config(start=start, explicit_path=explicit, disabled=args.no_config)
    config = result.config
    diagnostics.extend(result.diagnostics)
    diagnostics.extend(_project_config_diagnostics(config) if not has_errors(diagnostics) else [])
    manifest = None
    file_metrics: list[dict[str, object]] = []
    if not has_errors(diagnostics):
        manifest, manifest_diagnostics = load_book_manifest(config)
        diagnostics.extend(manifest_diagnostics)

    if manifest is not None and not has_errors(diagnostics):
        _validated_manifest, _bundle, book_diagnostics = _book_validation(config)
        diagnostics.extend(book_diagnostics)

    if manifest is not None and not has_errors(diagnostics):
        for chapter in manifest.chapters:
            try:
                rendered = _render_for_accessibility(
                    chapter.path,
                    config,
                    document_root=manifest.root,
                    defer_reference_resolution=bool(config.values.get("references_enabled", False)),
                    defer_citation_resolution=bool(config.values.get("citations_enabled", False)),
                )
                diagnostics.extend(rendered.diagnostics)
                metadata_appearance = appearance_from_metadata(rendered.metadata)
                appearance = resolve_appearance(
                    style=config.values.get("style") or metadata_appearance.style,
                    palette=config.values.get("palette") or metadata_appearance.palette,
                    mode=config.values.get("mode") or metadata_appearance.mode,
                )
                audit = audit_markdown_result(
                    path=chapter.path,
                    markdown=chapter.path.read_text(encoding="utf-8-sig"),
                    result=rendered,
                    appearance=appearance,
                    configured_language=config.values.get("document_language"),
                )
                diagnostics.extend(audit.diagnostics)
                try:
                    relative = chapter.path.relative_to(manifest.root).as_posix()
                except ValueError:
                    relative = chapter.path.name
                file_metrics.append({"path": relative, **audit.metrics})
            except (MarkdownInputError, OSError, UnicodeError, ValueError) as exc:
                diagnostics.append(
                    Diagnostic(
                        "MARDAS-A900",
                        "error",
                        f"Accessibility audit could not analyze the chapter: {exc}",
                        path=chapter.path,
                    )
                )

    context: dict[str, object] = {
        "command": "audit-book-accessibility",
        "input": str(target),
        "summary": diagnostic_counts(diagnostics),
        "files": file_metrics,
        "compliance_claims": {
            "wcag": False,
            "pdfua": False,
            "note": "Source-level readiness checks only; manual and independent validation remain required.",
        },
    }
    if manifest is not None:
        context.update(book_context(manifest, None))
    write_diagnostics(diagnostics, output_format=args.format, stream=sys.stdout, context=context)
    return _audit_exit_status(diagnostics, args.fail_on)


def _audit_pdf_main(argv: list[str]) -> int:
    from .pdf_audit import audit_pdf, diagnostic_counts

    parser = _audit_parser("audit-pdf")
    args = parser.parse_args(argv)
    path = args.input.expanduser().resolve()
    if not path.is_file():
        diagnostics = [
            Diagnostic("MARDAS-P800", "error", "PDF input is not a regular file.", path=path)
        ]
        metrics: dict[str, object] = {"path": str(path), "profile": args.profile}
    else:
        result = audit_pdf(path, profile=args.profile)
        diagnostics = list(result.diagnostics)
        metrics = result.metrics
    context = {
        "command": "audit-pdf",
        "summary": diagnostic_counts(diagnostics),
        "metrics": metrics,
    }
    write_diagnostics(diagnostics, output_format=args.format, stream=sys.stdout, context=context)
    return _audit_exit_status(diagnostics, args.fail_on)


def _book_parser(command: str) -> argparse.ArgumentParser:
    descriptions = {
        "build-book": "Build one deterministic PDF from the ordered chapters in mardas.toml.",
        "validate-book": "Validate the complete multi-file book without launching Chromium.",
        "explain-book": "Show the resolved chapter order, titles, output, and heading counts.",
    }
    parser = argparse.ArgumentParser(
        prog=f"mrs-md2pdf {command}", description=descriptions[command]
    )
    parser.add_argument(
        "project",
        nargs="?",
        type=Path,
        default=Path.cwd(),
        help="Project directory, mardas.toml path, or a chapter inside the project",
    )
    _add_config_arguments(parser)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    if command == "build-book":
        parser.add_argument("-o", "--output", type=Path, help="Override book.output for this build")
        parser.add_argument("--debug-html", type=Path, help="Write the combined HTML atomically")
        parser.add_argument(
            "--progress",
            choices=["auto", "on", "off"],
            default="auto",
            help="Show stage progress on stderr",
        )
    return parser


def _book_target_and_config(
    args: argparse.Namespace,
) -> tuple[Path, LoadedProjectConfig, list[Diagnostic]]:
    target = args.project.expanduser().resolve()
    explicit = args.config
    if target.is_file() and target.name == CONFIG_FILENAME and explicit is None:
        explicit = target
    start = target.parent if target.is_file() and target.name == CONFIG_FILENAME else target
    diagnostics = _input_diagnostics(target, required_file=False)
    if target.name == CONFIG_FILENAME and not target.is_file():
        diagnostics = [
            Diagnostic(
                "MARDAS-E101",
                "error",
                "Project configuration file was not found or is not a regular file.",
                path=target,
            )
        ]
    result = load_project_config(start=start, explicit_path=explicit, disabled=args.no_config)
    diagnostics.extend(result.diagnostics)
    if not has_errors(diagnostics):
        diagnostics.extend(_project_config_diagnostics(result.config))
    return target, result.config, diagnostics


def _book_validation(
    config: LoadedProjectConfig,
    *,
    progress: Callable[[str, float], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[BookManifest | None, BookRenderBundle | None, list[Diagnostic]]:
    manifest, manifest_diagnostics = load_book_manifest(config)
    diagnostics = list(manifest_diagnostics)
    if manifest is None or has_errors(diagnostics):
        return manifest, None, diagnostics

    chapter_count = max(1, len(manifest.chapters))
    for chapter in manifest.chapters:
        if cancelled and cancelled():
            from .renderer import RenderCancelledError

            raise RenderCancelledError("PDF rendering was cancelled.")
        if progress:
            progress(
                f"Validating chapter {chapter.index} of {chapter_count}",
                0.02 + 0.28 * ((chapter.index - 1) / chapter_count),
            )
        chapter_diagnostics, _context = _validate_document(
            chapter.path,
            config,
            document_root=manifest.root,
            defer_reference_resolution=bool(config.values.get("references_enabled", False)),
            defer_citation_resolution=bool(config.values.get("citations_enabled", False)),
        )
        diagnostics.extend(chapter_diagnostics)
    bundle, render_diagnostics = render_book(
        manifest,
        progress=(
            (lambda stage, value: progress(stage, 0.3 + value * 0.7)) if progress else None
        ),
        cancelled=cancelled,
    )
    diagnostics.extend(render_diagnostics)

    if bundle is not None:
        titles: dict[str, Path] = {}
        for summary in bundle.chapters:
            key = summary.title.strip().casefold()
            previous = titles.get(key)
            if key and previous is not None:
                diagnostics.append(
                    Diagnostic(
                        "MARDAS-W503",
                        "warning",
                        f"Book contains duplicate chapter title: {summary.title}",
                        path=summary.path,
                        hint=f"The same title was first used by {previous}.",
                    )
                )
            elif key:
                titles[key] = summary.path
    return manifest, bundle, diagnostics


def project_config_diagnostics(config: LoadedProjectConfig) -> list[Diagnostic]:
    """Return project-level diagnostics for Studio and CLI integrations."""
    return _project_config_diagnostics(config)


def validate_book_project(
    config: LoadedProjectConfig,
    *,
    progress: Callable[[str, float], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[BookManifest | None, BookRenderBundle | None, list[Diagnostic]]:
    """Validate and render a Book Mode project without formatting CLI output."""
    return _book_validation(config, progress=progress, cancelled=cancelled)


def _book_progress(mode: str, *, json_output: bool) -> Callable[[str, float], None] | None:
    enabled = mode == "on" or (mode == "auto" and sys.stderr.isatty())
    if json_output or not enabled:
        return None

    def report(stage: str, value: float) -> None:
        percent = max(0, min(100, round(value * 100)))
        print(f"[{percent:3d}%] {stage}", file=sys.stderr)

    return report


def _validate_book_main(argv: list[str]) -> int:
    parser = _book_parser("validate-book")
    args = parser.parse_args(argv)
    _target, config, diagnostics = _book_target_and_config(args)
    manifest = None
    bundle = None
    if not has_errors(diagnostics):
        manifest, bundle, book_diagnostics = _book_validation(config)
        diagnostics.extend(book_diagnostics)
    context: dict[str, object] = {
        "command": "validate-book",
        "schema_version": CONFIG_SCHEMA_VERSION,
    }
    if manifest is not None:
        context.update(book_context(manifest, bundle))
    write_diagnostics(diagnostics, output_format=args.format, stream=sys.stdout, context=context)
    return 1 if has_errors(diagnostics) else 0


def _explain_book_main(argv: list[str]) -> int:
    parser = _book_parser("explain-book")
    args = parser.parse_args(argv)
    _target, config, diagnostics = _book_target_and_config(args)
    manifest = None
    bundle = None
    if not has_errors(diagnostics):
        manifest, bundle, book_diagnostics = _book_validation(config)
        diagnostics.extend(book_diagnostics)
    context: dict[str, object] = {
        "command": "explain-book",
        "schema_version": CONFIG_SCHEMA_VERSION,
    }
    if manifest is not None:
        context.update(book_context(manifest, bundle))
    write_diagnostics(diagnostics, output_format=args.format, stream=sys.stdout, context=context)
    return 1 if has_errors(diagnostics) else 0


def _build_book_main(argv: list[str]) -> int:
    parser = _book_parser("build-book")
    args = parser.parse_args(argv)
    _target, config, diagnostics = _book_target_and_config(args)
    manifest = None
    bundle = None
    if not has_errors(diagnostics):
        manifest, bundle, book_diagnostics = _book_validation(config)
        diagnostics.extend(book_diagnostics)
    if manifest is None or has_errors(diagnostics):
        context: dict[str, object] = {"command": "build-book"}
        if manifest is not None:
            context.update(book_context(manifest, bundle))
        write_diagnostics(
            diagnostics, output_format=args.format, stream=sys.stdout, context=context
        )
        return 1

    output_override = args.output.expanduser().resolve() if args.output else None
    debug_html = args.debug_html.expanduser().resolve() if args.debug_html else None
    try:
        output, built_bundle, build_diagnostics = convert_book(
            manifest,
            output_path=output_override,
            debug_html=debug_html,
            progress=_book_progress(args.progress, json_output=args.format == "json"),
            bundle=bundle,
        )
    except Exception as exc:
        if os.environ.get("MARDAS_DEBUG") == "1":
            raise
        output = None
        built_bundle = bundle
        build_diagnostics = (
            Diagnostic(
                "MARDAS-E511",
                "error",
                f"Book rendering failed: {exc}",
                path=manifest.output_path,
                hint="Run `mrs-md2pdf doctor` and retry with MARDAS_DEBUG=1 only for local debugging.",
            ),
        )
    diagnostics.extend(build_diagnostics)
    context = {"command": "build-book", **book_context(manifest, built_bundle or bundle)}
    if output is not None:
        context["output"] = str(output)
    write_diagnostics(diagnostics, output_format=args.format, stream=sys.stdout, context=context)
    return 1 if output is None or has_errors(diagnostics) else 0


def run_project_command(command: str, argv: list[str]) -> int:
    handlers: dict[str, Callable[[list[str]], int]] = {
        "init": _init_main,
        "validate": _validate_main,
        "doctor": _doctor_main,
        "explain-config": _explain_config_main,
        "build-book": _build_book_main,
        "validate-book": _validate_book_main,
        "explain-book": _explain_book_main,
        "audit-accessibility": _audit_accessibility_main,
        "audit-book-accessibility": _audit_book_accessibility_main,
        "audit-pdf": _audit_pdf_main,
    }
    try:
        handler = handlers[command]
    except KeyError as exc:  # pragma: no cover - protected by CLI dispatch
        raise ValueError(f"Unknown project command: {command}") from exc
    return handler(argv)

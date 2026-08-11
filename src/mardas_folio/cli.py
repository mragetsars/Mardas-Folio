from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .appearance import (
    MODE_DESCRIPTIONS,
    MODES,
    PALETTE_DESCRIPTIONS,
    PALETTES_ORDER,
    STYLE_DESCRIPTIONS,
    STYLES,
)
from .config import (
    CONFIG_FILENAME,
    LoadedProjectConfig,
    apply_config_values,
    load_project_config,
)
from .diagnostics import format_diagnostic, has_errors
from .project_commands import PROJECT_COMMANDS, run_project_command
from .quality import ERROR_POLICIES, QUALITY_PROFILES
from .renderer import (
    BRANDING_MODES,
    PdfOptions,
    convert,
    validate_branding_mode,
    validate_page_size,
)


class _CliProgressBar:
    def __init__(self, *, stream=None, width: int = 28) -> None:
        self.stream = stream or sys.stderr
        self.width = width
        self._last_line = ""

    def __call__(self, message: str, fraction: float) -> None:
        fraction = max(0.0, min(1.0, float(fraction)))
        filled = round(self.width * fraction)
        bar = "█" * filled + "░" * (self.width - filled)
        line = f"\r[{bar}] {fraction:>6.0%}  {message}"
        padding = " " * max(0, len(self._last_line) - len(line))
        self.stream.write(line + padding)
        if fraction >= 1.0:
            self.stream.write("\n")
        self.stream.flush()
        self._last_line = line


def _progress_callback(mode: str):
    if mode == "off":
        return None
    if mode == "auto" and not sys.stderr.isatty():
        return None
    return _CliProgressBar()


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="folio",
        description=(
            "Convert Markdown to polished PDF with Persian RTL/LTR typography, "
            "professional covers, hierarchical TOC, code highlighting, Mermaid flowcharts, tables, watermarking, and MathJax."
        ),
        epilog=(
            "Project workflows: `folio init`, `validate`, `doctor`, `explain-config`, "
            "`validate-book`, `explain-book`, `build-book`, `audit-accessibility`, "
            "`audit-book-accessibility`, and `audit-pdf`. Legacy conversion syntax remains "
            "`folio input.md [options]`."
        ),
    )
    parser.add_argument("input", nargs="?", type=Path, help="Input Markdown file")
    parser.add_argument("-o", "--output", type=Path, help="Output PDF path")
    _add_config_arguments(parser)
    parser.add_argument("--title", help="Override document title")
    parser.add_argument("--author", help="Override author metadata")
    parser.add_argument("--description", help="Override summary/description metadata")
    parser.add_argument(
        "--lang",
        dest="document_language",
        help="Declare the document language with a BCP 47 tag such as fa-IR or en-US.",
    )
    parser.add_argument(
        "--toc",
        dest="toc",
        action="store_true",
        default=False,
        help="Generate a hierarchical table of contents from Markdown headings",
    )
    parser.add_argument(
        "--no-toc",
        dest="toc",
        action="store_false",
        help="Disable a table of contents supplied by project configuration",
    )
    parser.add_argument(
        "--toc-depth",
        type=int,
        default=6,
        choices=range(1, 7),
        metavar="1..6",
        help="Maximum heading level to include in the TOC; default: 6",
    )
    parser.add_argument(
        "--toc-page-break",
        dest="toc_page_break",
        action="store_true",
        default=False,
        help="Start the main document body on a new page after the TOC",
    )
    parser.add_argument(
        "--no-toc-page-break",
        dest="toc_page_break",
        action="store_false",
        help="Disable the configured TOC page break",
    )
    parser.add_argument(
        "--h1-page-break",
        dest="h1_page_break",
        action="store_true",
        default=False,
        help="Start every top-level Markdown heading (# / h1) on a new page",
    )
    parser.add_argument(
        "--no-h1-page-break",
        dest="h1_page_break",
        action="store_false",
        help="Disable configured top-level heading page breaks",
    )
    parser.add_argument(
        "--debug-html", type=Path, help="Write the intermediate HTML for inspection"
    )
    parser.add_argument(
        "--page-size",
        default="A4",
        help='PDF page size, e.g. A4, Letter, "A4 landscape", or "210mm 297mm"',
    )
    parser.add_argument(
        "--dir",
        dest="document_direction",
        choices=["auto", "rtl", "ltr"],
        default=None,
        help="Document shell direction. Defaults to project config, front matter, then auto-detection.",
    )
    parser.add_argument("--margin-top", default="18mm", help="Top CSS page margin")
    parser.add_argument("--margin-bottom", default="20mm", help="Bottom CSS page margin")
    parser.add_argument("--margin-x", default="16mm", help="Left/right CSS page margin")
    parser.add_argument("--font-dir", type=Path, help="Directory containing Vazirmatn font files")
    quality_group = parser.add_argument_group("publication quality")
    quality_group.add_argument(
        "--quality-profile",
        choices=QUALITY_PROFILES,
        default="standard",
        help=(
            "Quality policy profile. strict-publication fails on incomplete MathJax, "
            "missing required fonts, and broken PDF navigation."
        ),
    )
    quality_group.add_argument(
        "--math-error-policy",
        choices=ERROR_POLICIES,
        default=None,
        help="How incomplete MathJax rendering is handled: error, warn, or ignore.",
    )
    quality_group.add_argument(
        "--font-error-policy",
        choices=ERROR_POLICIES,
        default=None,
        help="How missing required publication fonts are handled.",
    )
    quality_group.add_argument(
        "--navigation-error-policy",
        choices=ERROR_POLICIES,
        default=None,
        help="How incomplete PDF destinations and TOC links are handled.",
    )
    quality_group.add_argument(
        "--require-font",
        dest="required_fonts",
        action="append",
        default=[],
        metavar="FAMILY",
        help="Require a font family in Chromium; repeat for multiple families.",
    )
    quality_group.add_argument(
        "--quality-report",
        type=Path,
        help="Write structured MathJax, font, navigation, and render evidence as JSON.",
    )
    parser.add_argument("--chromium-path", help="Path to Chromium/Chrome executable")
    parser.add_argument(
        "--chromium-sandbox",
        choices=["auto", "on", "off"],
        default="auto",
        help=(
            "Chromium sandbox mode. auto keeps sandboxing on for normal users and disables it only "
            "when running as root; off is intended for trusted containers only."
        ),
    )
    parser.add_argument(
        "--style",
        choices=list(STYLES),
        default=None,
        help="Document shape and layout style. Controls spacing, cover shape, table density, and code block form.",
    )
    parser.add_argument(
        "--palette",
        choices=list(PALETTES_ORDER),
        default=None,
        help="Document accent color palette. Controls links, markers, cover accents, callouts, and diagram strokes.",
    )
    parser.add_argument(
        "--mode",
        choices=list(MODES),
        default=None,
        help="Document contrast mode: light or dark.",
    )
    parser.add_argument(
        "--no-cover",
        dest="no_cover",
        action="store_true",
        default=False,
        help="Do not generate the automatic cover page",
    )
    parser.add_argument(
        "--cover",
        dest="no_cover",
        action="store_false",
        help="Enable a cover disabled by project configuration",
    )
    parser.add_argument(
        "--branding",
        choices=BRANDING_MODES,
        default=None,
        help="Cover branding mode. Defaults to project config, front matter, or off.",
    )
    parser.add_argument(
        "--brand-name",
        help="Brand or organization name to show on the cover when branding is enabled",
    )
    parser.add_argument(
        "--brand-logo", type=Path, help="Brand logo image for the cover when branding is enabled"
    )
    parser.add_argument(
        "--brand-footer", help="Small brand subtitle/footer shown under the cover brand name"
    )
    parser.add_argument("--cover-logo", type=Path, help="Alias for --brand-logo")
    parser.add_argument(
        "--no-cover-logo",
        dest="no_cover_logo",
        action="store_true",
        default=False,
        help="Hide any logo on the generated cover brand block",
    )
    parser.add_argument(
        "--show-cover-logo",
        dest="no_cover_logo",
        action="store_false",
        help="Show a logo disabled by project configuration",
    )
    parser.add_argument(
        "--watermark",
        help="Text watermark to repeat on all content pages. The cover is never watermarked",
    )
    parser.add_argument(
        "--watermark-image",
        type=Path,
        help="Image watermark to repeat on all content pages. The cover is never watermarked",
    )
    parser.add_argument(
        "--watermark-opacity",
        type=float,
        default=0.065,
        help="Watermark opacity between 0 and 1; default: 0.065",
    )
    parser.add_argument(
        "--watermark-width",
        default="105mm",
        help="CSS width for image watermarks, e.g. 90mm or 45%%; default: 105mm",
    )
    parser.add_argument(
        "--no-header-footer",
        dest="no_header_footer",
        action="store_true",
        default=False,
        help="Disable page number footer",
    )
    parser.add_argument(
        "--header-footer",
        dest="no_header_footer",
        action="store_false",
        help="Enable page numbering disabled by project configuration",
    )
    parser.add_argument(
        "--no-mathjax",
        dest="no_mathjax",
        action="store_true",
        default=False,
        help="Do not load MathJax",
    )
    parser.add_argument(
        "--mathjax",
        dest="no_mathjax",
        action="store_false",
        help="Enable MathJax disabled by project configuration",
    )
    parser.add_argument(
        "--unsafe-html",
        dest="unsafe_html",
        action="store_true",
        default=False,
        help="Allow raw HTML without sanitizing it first. Use only for trusted local Markdown.",
    )
    parser.add_argument(
        "--safe-html",
        dest="unsafe_html",
        action="store_false",
        help="Force sanitized HTML when project configuration enables unsafe HTML",
    )
    parser.add_argument(
        "--allow-remote-assets",
        dest="allow_remote_assets",
        action="store_true",
        default=False,
        help="Allow remote http(s) images to be loaded by Chromium. Disabled by default for privacy.",
    )
    parser.add_argument(
        "--block-remote-assets",
        dest="allow_remote_assets",
        action="store_false",
        help="Block remote assets enabled by project configuration",
    )
    reference_group = parser.add_argument_group("cross-references and numbering")
    reference_toggle = reference_group.add_mutually_exclusive_group()
    reference_toggle.add_argument(
        "--references",
        dest="references_enabled",
        action="store_true",
        default=None,
        help="Enable labeled object numbering and @label cross-references.",
    )
    reference_toggle.add_argument(
        "--no-references",
        dest="references_enabled",
        action="store_false",
        help="Disable cross-references enabled by project configuration or front matter.",
    )
    reference_group.add_argument(
        "--numbering-scope",
        choices=["global", "chapter"],
        default=None,
        help="Number labeled objects globally or by chapter in Book Mode.",
    )
    for option, dest, title in (
        ("figures", "list_of_figures", "figures"),
        ("tables", "list_of_tables", "tables"),
        ("equations", "list_of_equations", "equations"),
        ("listings", "list_of_listings", "code listings"),
    ):
        toggle = reference_group.add_mutually_exclusive_group()
        toggle.add_argument(
            f"--list-of-{option}",
            dest=dest,
            action="store_true",
            default=None,
            help=f"Generate a list of numbered {title}.",
        )
        toggle.add_argument(
            f"--no-list-of-{option}",
            dest=dest,
            action="store_false",
            help=f"Disable a configured list of {title}.",
        )

    bibliography_group = parser.add_argument_group("bibliography and citations")
    citation_toggle = bibliography_group.add_mutually_exclusive_group()
    citation_toggle.add_argument(
        "--citations",
        dest="citations_enabled",
        action="store_true",
        default=None,
        help="Enable citations and a generated bibliography.",
    )
    citation_toggle.add_argument(
        "--no-citations",
        dest="citations_enabled",
        action="store_false",
        help="Disable citations enabled by project configuration or front matter.",
    )
    bibliography_group.add_argument(
        "--bibliography",
        dest="bibliography_sources",
        action="append",
        type=Path,
        default=None,
        metavar="PATH",
        help="Add a local BibTeX (.bib) or CSL JSON (.json) source; repeat for multiple files.",
    )
    bibliography_group.add_argument(
        "--citation-style",
        choices=["author-date", "numeric"],
        default=None,
        help="Render citations in author-date or numeric style.",
    )
    bibliography_group.add_argument(
        "--bibliography-title",
        default=None,
        help="Override the localized bibliography section title.",
    )
    uncited_toggle = bibliography_group.add_mutually_exclusive_group()
    uncited_toggle.add_argument(
        "--include-uncited",
        dest="bibliography_include_uncited",
        action="store_true",
        default=None,
        help="Include uncited bibliography entries in the generated bibliography.",
    )
    uncited_toggle.add_argument(
        "--cited-only",
        dest="bibliography_include_uncited",
        action="store_false",
        help="Include only cited entries when project configuration enables uncited entries.",
    )

    parser.add_argument(
        "--timeout-ms", type=int, default=120_000, help="Browser timeout in milliseconds"
    )
    parser.add_argument(
        "--progress",
        choices=["auto", "on", "off"],
        default="auto",
        help="Show a terminal progress bar during PDF generation. Default: auto, only on interactive terminals.",
    )
    parser.add_argument(
        "--list-styles", action="store_true", help="List available appearance styles and exit"
    )
    parser.add_argument(
        "--list-palettes", action="store_true", help="List available color palettes and exit"
    )
    parser.add_argument(
        "--list-modes", action="store_true", help="List available light/dark modes and exit"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _print_named_choices(title: str, descriptions: dict[str, str], order: tuple[str, ...]) -> None:
    print(title)
    for name in order:
        print(f"  {name:<12} {descriptions.get(name, '')}")


def _explicit_destinations(parser: argparse.ArgumentParser, argv: list[str]) -> set[str]:
    option_map = {
        option: action.dest for action in parser._actions for option in action.option_strings
    }
    explicit: set[str] = set()
    for token in argv:
        option = token.split("=", 1)[0]
        dest = option_map.get(option)
        if dest:
            explicit.add(dest)
            continue
        if token.startswith("-") and not token.startswith("--"):
            for candidate, candidate_dest in option_map.items():
                if len(candidate) == 2 and token.startswith(candidate):
                    explicit.add(candidate_dest)
                    break
    return explicit


def _load_config_for_namespace(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    *,
    input_path: Path,
    explicit_destinations: set[str],
) -> tuple[LoadedProjectConfig, dict[str, str]]:
    result = load_project_config(
        start=input_path,
        explicit_path=args.config,
        disabled=args.no_config,
    )
    if has_errors(result.diagnostics):
        parser.error(format_diagnostic(result.diagnostics[0]))
    sources = apply_config_values(
        args,
        result.config,
        explicit_destinations=explicit_destinations,
    )
    if isinstance(args.chromium_path, Path):
        args.chromium_path = str(args.chromium_path)
    return result.config, sources


def _validate_asset_arguments(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    brand_logo = args.brand_logo or args.cover_logo
    if brand_logo and not Path(brand_logo).is_file():
        parser.error(f"Brand logo must be a regular file: {brand_logo}")
    if args.watermark_image and not Path(args.watermark_image).is_file():
        parser.error(f"Watermark image must be a regular file: {args.watermark_image}")
    if args.font_dir and not Path(args.font_dir).is_dir():
        parser.error(f"Font directory must be a directory: {args.font_dir}")
    if not 0 <= args.watermark_opacity <= 1:
        parser.error("--watermark-opacity must be between 0 and 1")


def _conversion_main(argv: list[str]) -> int:
    parser = build_parser()
    explicit = _explicit_destinations(parser, argv)
    args = parser.parse_args(argv)
    if args.list_styles:
        _print_named_choices("Styles", STYLE_DESCRIPTIONS, STYLES)
        return 0
    if args.list_palettes:
        _print_named_choices("Palettes", PALETTE_DESCRIPTIONS, PALETTES_ORDER)
        return 0
    if args.list_modes:
        _print_named_choices("Modes", MODE_DESCRIPTIONS, MODES)
        return 0
    input_path = args.input
    if input_path is None:
        parser.error("input is required unless you use a project command or a --list-* option")
    if not input_path.exists():
        parser.error(f"Input file not found: {input_path}")
    if not input_path.is_file():
        parser.error(f"Input path is not a regular file: {input_path}")

    _load_config_for_namespace(parser, args, input_path=input_path, explicit_destinations=explicit)
    _validate_asset_arguments(parser, args)
    try:
        branding = validate_branding_mode(args.branding) if args.branding is not None else None
    except ValueError as exc:
        parser.error(f"--branding {exc}")
    try:
        page_size = validate_page_size(args.page_size)
    except ValueError as exc:
        parser.error(f"--page-size {exc}")

    output_path = args.output or input_path.with_suffix(".pdf")
    brand_logo = args.brand_logo or args.cover_logo
    options = PdfOptions(
        input_path=input_path,
        output_path=output_path,
        title=args.title,
        author=args.author,
        description=args.description,
        toc=args.toc,
        toc_depth=args.toc_depth,
        toc_page_break=args.toc_page_break,
        h1_page_break=args.h1_page_break,
        debug_html=args.debug_html,
        page_size=page_size,
        document_language=args.document_language,
        document_direction=args.document_direction,
        margin_top=args.margin_top,
        margin_bottom=args.margin_bottom,
        margin_x=args.margin_x,
        font_dir=args.font_dir,
        chromium_path=args.chromium_path,
        chromium_sandbox=args.chromium_sandbox,
        no_header_footer=args.no_header_footer,
        no_mathjax=args.no_mathjax,
        timeout_ms=args.timeout_ms,
        style=args.style,
        palette=args.palette,
        mode=args.mode,
        cover=not args.no_cover,
        cover_logo=brand_logo,
        cover_logo_enabled=not args.no_cover_logo,
        branding=branding,
        brand_name=args.brand_name,
        brand_logo=brand_logo,
        brand_footer=args.brand_footer,
        watermark_text=args.watermark,
        watermark_image=args.watermark_image,
        watermark_opacity=args.watermark_opacity,
        watermark_width=args.watermark_width,
        unsafe_html=args.unsafe_html,
        allow_remote_assets=args.allow_remote_assets,
        references_enabled=args.references_enabled,
        numbering_scope=args.numbering_scope,
        list_of_figures=args.list_of_figures,
        list_of_tables=args.list_of_tables,
        list_of_equations=args.list_of_equations,
        list_of_listings=args.list_of_listings,
        citations_enabled=args.citations_enabled,
        bibliography_sources=tuple(args.bibliography_sources or ()),
        citation_style=args.citation_style,
        bibliography_title=args.bibliography_title,
        bibliography_include_uncited=args.bibliography_include_uncited,
        quality_profile=args.quality_profile,
        math_error_policy=args.math_error_policy,
        font_error_policy=args.font_error_policy,
        navigation_error_policy=args.navigation_error_policy,
        required_fonts=tuple(args.required_fonts or ()),
        quality_report=args.quality_report,
        progress=_progress_callback(args.progress),
    )
    try:
        pdf_path = convert(options)
    except Exception as exc:
        if os.environ.get("MARDAS_DEBUG") == "1":
            raise
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"PDF created: {pdf_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv and raw_argv[0] in PROJECT_COMMANDS:
        command = raw_argv.pop(0)
        return run_project_command(command, raw_argv)
    return _conversion_main(raw_argv)


if __name__ == "__main__":
    raise SystemExit(main())

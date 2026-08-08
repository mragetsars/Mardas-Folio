from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib

from .appearance import MODES, PALETTES_ORDER, STYLES
from .diagnostics import Diagnostic
from .quality import ERROR_POLICIES, QUALITY_PROFILES
from .renderer import BRANDING_MODES, validate_page_size

CONFIG_FILENAME = "mardas.toml"
CONFIG_SCHEMA_VERSION = 1
MAX_CONFIG_BYTES = 1_048_576
MAX_BOOK_CHAPTERS = 512
MAX_BIBLIOGRAPHY_SOURCES = 32
MAX_CONFIG_TEXT_CHARS = 4_096


@dataclass(frozen=True, slots=True)
class LoadedProjectConfig:
    path: Path | None
    root: Path
    values: dict[str, Any]

    @property
    def discovered(self) -> bool:
        return self.path is not None


@dataclass(frozen=True, slots=True)
class ConfigLoadResult:
    config: LoadedProjectConfig
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class ConfigField:
    section: str
    key: str
    dest: str
    validator: Callable[[Any], Any]
    path_value: bool = False
    invert: bool = False

    @property
    def dotted_key(self) -> str:
        return f"{self.section}.{self.key}"


@dataclass(frozen=True, slots=True)
class RenderOptionSpec:
    validator: Callable[[Any], Any]
    nullable: bool = False


class ConfigValueError(ValueError):
    pass


def _validate_text(value: Any, *, allow_empty: bool) -> str:
    if not isinstance(value, str):
        raise ConfigValueError("expected a string")
    if len(value) > MAX_CONFIG_TEXT_CHARS:
        raise ConfigValueError(
            f"expected no more than {MAX_CONFIG_TEXT_CHARS} characters"
        )
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ConfigValueError("expected valid UTF-8 text") from exc
    if any(ord(character) < 32 and character not in "\t\n\r" for character in value):
        raise ConfigValueError("control characters are not allowed")
    if not allow_empty and not value.strip():
        raise ConfigValueError("expected a non-empty string")
    return value


def _string(value: Any) -> str:
    return _validate_text(value, allow_empty=False).strip()


def _optional_string(value: Any) -> str:
    return _validate_text(value, allow_empty=True)


def _book_chapters(value: Any) -> tuple[dict[str, str | None], ...]:
    if not isinstance(value, list):
        raise ConfigValueError("expected an ordered array of chapter paths")
    if not value:
        raise ConfigValueError("expected at least one chapter")
    if len(value) > MAX_BOOK_CHAPTERS:
        raise ConfigValueError(f"expected no more than {MAX_BOOK_CHAPTERS} chapters")

    chapters: list[dict[str, str | None]] = []
    for index, item in enumerate(value, start=1):
        if isinstance(item, str):
            path_value = _string(item)
            title = None
        elif isinstance(item, dict):
            unknown = set(item) - {"path", "title"}
            if unknown:
                names = ", ".join(sorted(str(key) for key in unknown))
                raise ConfigValueError(
                    f"chapter {index} contains unsupported keys: {names}"
                )
            if "path" not in item:
                raise ConfigValueError(f"chapter {index} requires a path")
            path_value = _string(item["path"])
            raw_title = item.get("title")
            title = _string(raw_title) if raw_title is not None else None
        else:
            raise ConfigValueError(
                f"chapter {index} must be a path string or a table with path/title"
            )
        chapters.append({"path": path_value, "title": title})
    return tuple(chapters)




def _string_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ConfigValueError("expected a string or an array of strings")
    if len(value) > 32:
        raise ConfigValueError("expected no more than 32 values")
    result: list[str] = []
    for item in value:
        normalized = _string(item)
        if normalized not in result:
            result.append(normalized)
    return tuple(result)


def _bibliography_sources(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ConfigValueError("expected a bibliography path or an array of paths")
    if not value:
        raise ConfigValueError("expected at least one bibliography source")
    if len(value) > MAX_BIBLIOGRAPHY_SOURCES:
        raise ConfigValueError(
            f"expected no more than {MAX_BIBLIOGRAPHY_SOURCES} bibliography sources"
        )
    sources: list[str] = []
    for index, item in enumerate(value, start=1):
        path = _string(item)
        if Path(path).suffix.lower() not in {".bib", ".json"}:
            raise ConfigValueError(
                f"bibliography source {index} must use .bib or .json"
            )
        sources.append(path)
    return tuple(sources)

def _boolean(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ConfigValueError("expected true or false")
    return value


def _integer(minimum: int, maximum: int) -> Callable[[Any], int]:
    def validate(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigValueError("expected an integer")
        if not minimum <= value <= maximum:
            raise ConfigValueError(f"expected a value between {minimum} and {maximum}")
        return value

    return validate


def _number(minimum: float, maximum: float) -> Callable[[Any], float]:
    def validate(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigValueError("expected a number")
        result = float(value)
        if not math.isfinite(result):
            raise ConfigValueError("expected a finite number")
        if not minimum <= result <= maximum:
            raise ConfigValueError(f"expected a value between {minimum} and {maximum}")
        return result

    return validate


def _choice(choices: tuple[str, ...] | list[str]) -> Callable[[Any], str]:
    allowed = tuple(choices)

    def validate(value: Any) -> str:
        result = _string(value).lower()
        if result not in allowed:
            raise ConfigValueError(f"expected one of: {', '.join(allowed)}")
        return result

    return validate




def _language_tag(value: Any) -> str:
    result = _string(value).replace("_", "-")
    if result.lower() in {"auto", "und"}:
        return result.lower()
    if len(result) > 35 or not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", result):
        raise ConfigValueError("expected a BCP 47 language tag such as fa-IR or en-US")
    parts = result.split("-")
    normalized = [parts[0].lower()]
    for part in parts[1:]:
        normalized.append(part.upper() if len(part) == 2 and part.isalpha() else part)
    return "-".join(normalized)

def _page_size(value: Any) -> str:
    try:
        return validate_page_size(_string(value))
    except ValueError as exc:
        raise ConfigValueError(str(exc)) from exc


def _css_length(value: Any) -> str:
    result = _string(value)
    match = re.fullmatch(
        r"(?:(?P<zero>0)|(?P<number>[0-9]+(?:\.[0-9]+)?)(?P<unit>mm|cm|in|pt|px|%))",
        result,
    )
    if len(result) > 64 or match is None:
        raise ConfigValueError("expected a non-negative CSS length such as 18mm, 1.5cm, or 45%")
    if match.group("zero"):
        return result
    number = float(match.group("number"))
    unit = str(match.group("unit"))
    if not math.isfinite(number):
        raise ConfigValueError("expected a finite CSS length")
    if unit == "%":
        if number > 100:
            raise ConfigValueError("percentage lengths cannot exceed 100%")
    else:
        millimetres = number * {
            "mm": 1.0,
            "cm": 10.0,
            "in": 25.4,
            "pt": 25.4 / 72.0,
            "px": 25.4 / 96.0,
        }[unit]
        if millimetres > 2_000:
            raise ConfigValueError("CSS lengths cannot exceed 2000mm")
    return result


CONFIG_FIELDS: tuple[ConfigField, ...] = (
    ConfigField("project", "title", "title", _optional_string),
    ConfigField("project", "author", "author", _optional_string),
    ConfigField("project", "description", "description", _optional_string),
    ConfigField("project", "language", "document_language", _language_tag),
    ConfigField("project", "direction", "document_direction", _choice(["auto", "rtl", "ltr"])),
    ConfigField("output", "toc", "toc", _boolean),
    ConfigField("output", "toc_depth", "toc_depth", _integer(1, 6)),
    ConfigField("output", "toc_page_break", "toc_page_break", _boolean),
    ConfigField("output", "h1_page_break", "h1_page_break", _boolean),
    ConfigField("output", "page_size", "page_size", _page_size),
    ConfigField("output", "margin_top", "margin_top", _css_length),
    ConfigField("output", "margin_bottom", "margin_bottom", _css_length),
    ConfigField("output", "margin_x", "margin_x", _css_length),
    ConfigField("output", "cover", "no_cover", _boolean, invert=True),
    ConfigField("output", "header_footer", "no_header_footer", _boolean, invert=True),
    ConfigField("output", "mathjax", "no_mathjax", _boolean, invert=True),
    ConfigField("appearance", "style", "style", _choice(list(STYLES))),
    ConfigField("appearance", "palette", "palette", _choice(list(PALETTES_ORDER))),
    ConfigField("appearance", "mode", "mode", _choice(list(MODES))),
    ConfigField("branding", "mode", "branding", _choice(list(BRANDING_MODES))),
    ConfigField("branding", "name", "brand_name", _optional_string),
    ConfigField("branding", "logo", "brand_logo", _string, path_value=True),
    ConfigField("branding", "footer", "brand_footer", _optional_string),
    ConfigField("branding", "show_logo", "no_cover_logo", _boolean, invert=True),
    ConfigField("watermark", "text", "watermark", _optional_string),
    ConfigField("watermark", "image", "watermark_image", _string, path_value=True),
    ConfigField("watermark", "opacity", "watermark_opacity", _number(0.0, 1.0)),
    ConfigField("watermark", "width", "watermark_width", _css_length),
    ConfigField("security", "unsafe_html", "unsafe_html", _boolean),
    ConfigField("security", "allow_remote_assets", "allow_remote_assets", _boolean),
    ConfigField("browser", "chromium_path", "chromium_path", _string, path_value=True),
    ConfigField("browser", "chromium_sandbox", "chromium_sandbox", _choice(["auto", "on", "off"])),
    ConfigField("browser", "timeout_ms", "timeout_ms", _integer(1_000, 3_600_000)),
    ConfigField("fonts", "directory", "font_dir", _string, path_value=True),
    ConfigField("quality", "profile", "quality_profile", _choice(list(QUALITY_PROFILES))),
    ConfigField("quality", "math_errors", "math_error_policy", _choice(list(ERROR_POLICIES))),
    ConfigField("quality", "font_errors", "font_error_policy", _choice(list(ERROR_POLICIES))),
    ConfigField(
        "quality",
        "navigation_errors",
        "navigation_error_policy",
        _choice(list(ERROR_POLICIES)),
    ),
    ConfigField("quality", "required_fonts", "required_fonts", _string_list),
    ConfigField("quality", "report", "quality_report", _string, path_value=True),
    ConfigField("bibliography", "enabled", "citations_enabled", _boolean),
    ConfigField("bibliography", "sources", "bibliography_sources", _bibliography_sources),
    ConfigField(
        "bibliography", "style", "citation_style", _choice(["author-date", "numeric"])
    ),
    ConfigField("bibliography", "title", "bibliography_title", _optional_string),
    ConfigField(
        "bibliography", "include_uncited", "bibliography_include_uncited", _boolean
    ),
    ConfigField("references", "enabled", "references_enabled", _boolean),
    ConfigField("references", "numbering_scope", "numbering_scope", _choice(["global", "chapter"])),
    ConfigField("references", "list_of_figures", "list_of_figures", _boolean),
    ConfigField("references", "list_of_tables", "list_of_tables", _boolean),
    ConfigField("references", "list_of_equations", "list_of_equations", _boolean),
    ConfigField("references", "list_of_listings", "list_of_listings", _boolean),
    ConfigField("book", "chapters", "book_chapters", _book_chapters),
    ConfigField("book", "output", "book_output", _string, path_value=True),
    ConfigField("book", "chapter_page_break", "book_chapter_page_break", _boolean),
)

_RENDER_DEST_ALIASES = {
    "no_cover": "cover",
    "no_cover_logo": "cover_logo_enabled",
    "watermark": "watermark_text",
}
_NULLABLE_RENDER_OPTIONS = frozenset(
    {
        "bibliography_sources",
        "bibliography_title",
        "bibliography_include_uncited",
        "brand_footer",
        "brand_logo",
        "brand_name",
        "branding",
        "chromium_path",
        "citation_style",
        "cover_logo",
        "debug_html",
        "description",
        "document_direction",
        "document_language",
        "font_dir",
        "font_error_policy",
        "list_of_equations",
        "list_of_figures",
        "list_of_listings",
        "list_of_tables",
        "math_error_policy",
        "mode",
        "navigation_error_policy",
        "numbering_scope",
        "palette",
        "quality_report",
        "references_enabled",
        "required_fonts",
        "style",
        "title",
        "author",
        "citations_enabled",
        "watermark_image",
        "watermark_text",
    }
)


def _strict_render_string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ConfigValueError("expected an array of strings")
    return _string_list(list(value))


def _strict_render_bibliography_sources(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ConfigValueError("expected an array of bibliography paths")
    if not value:
        return ()
    return _bibliography_sources(list(value))


RENDER_OPTION_SPECS: dict[str, RenderOptionSpec] = {}
for _config_field in CONFIG_FIELDS:
    _render_dest = _RENDER_DEST_ALIASES.get(_config_field.dest, _config_field.dest)
    if _render_dest.startswith("book_"):
        continue
    RENDER_OPTION_SPECS[_render_dest] = RenderOptionSpec(
        _config_field.validator,
        nullable=_render_dest in _NULLABLE_RENDER_OPTIONS,
    )
RENDER_OPTION_SPECS.update(
    {
        "bibliography_sources": RenderOptionSpec(
            _strict_render_bibliography_sources,
            nullable=True,
        ),
        "cover_logo": RenderOptionSpec(_string, nullable=True),
        "debug_html": RenderOptionSpec(_string, nullable=True),
        "required_fonts": RenderOptionSpec(_strict_render_string_list, nullable=True),
    }
)

_ALLOWED_SECTIONS = {field.section for field in CONFIG_FIELDS}
_ALLOWED_KEYS = {
    section: {field.key for field in CONFIG_FIELDS if field.section == section}
    for section in _ALLOWED_SECTIONS
}


def default_config_text() -> str:
    return """schema_version = 1

[project]
# title = "My document"
# author = "Author name"
# description = "Short document summary"
# language = "fa-IR"
direction = "auto"

[output]
page_size = "A4"
toc = true
toc_depth = 3
toc_page_break = true
h1_page_break = false
cover = true
header_footer = true
mathjax = true
margin_top = "18mm"
margin_bottom = "20mm"
margin_x = "16mm"

[appearance]
style = "modern"
palette = "blue"
mode = "light"

[branding]
mode = "off"
show_logo = true
# name = "Organization name"
# logo = "assets/logo.png"
# footer = "Department or project"

[security]
unsafe_html = false
allow_remote_assets = false

[quality]
profile = "standard"
# math_errors = "warn"
# font_errors = "warn"
# navigation_errors = "warn"
# required_fonts = ["Vazirmatn"]
# report = "build/render-quality.json"

[bibliography]
enabled = false
# sources = ["references.bib"]
style = "author-date"
include_uncited = false
# title = "References"

[references]
enabled = false
numbering_scope = "global"
list_of_figures = false
list_of_tables = false
list_of_equations = false
list_of_listings = false

# Enable multi-file Book Mode by listing chapters in deterministic order.
# [book]
# chapters = [
#   "chapters/01-introduction.md",
#   "chapters/02-content.md",
# ]
# output = "dist/book.pdf"
# chapter_page_break = true

[browser]
chromium_sandbox = "auto"
timeout_ms = 120000
"""


def discover_config(start: Path) -> Path | None:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate
    return None


def _toml_location(exc: Exception) -> tuple[int | None, int | None]:
    line = getattr(exc, "lineno", None)
    column = getattr(exc, "colno", None)
    if line is not None:
        return int(line), int(column) if column is not None else None
    match = re.search(r"line (\d+), column (\d+)", str(exc), flags=re.IGNORECASE)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def load_project_config(
    *,
    start: Path,
    explicit_path: Path | None = None,
    disabled: bool = False,
) -> ConfigLoadResult:
    root = (start.parent if start.is_file() else start).resolve()
    if disabled:
        return ConfigLoadResult(LoadedProjectConfig(None, root, {}), ())

    config_path = (
        explicit_path.expanduser() if explicit_path is not None else discover_config(start)
    )
    if config_path is None:
        return ConfigLoadResult(LoadedProjectConfig(None, root, {}), ())
    config_path = config_path.resolve()
    if not config_path.is_file():
        diagnostic = Diagnostic(
            "MARDAS-E101",
            "error",
            "Project configuration file was not found or is not a regular file.",
            path=config_path,
            hint=f"Create {CONFIG_FILENAME} with `mrs-md2pdf init` or provide a valid --config path.",
        )
        return ConfigLoadResult(
            LoadedProjectConfig(config_path, config_path.parent, {}), (diagnostic,)
        )

    try:
        size = config_path.stat().st_size
        if size > MAX_CONFIG_BYTES:
            diagnostic = Diagnostic(
                "MARDAS-E110",
                "error",
                f"Project configuration exceeds the {MAX_CONFIG_BYTES}-byte safety limit.",
                path=config_path,
                hint="Keep project configuration concise and move document content out of TOML.",
            )
            return ConfigLoadResult(
                LoadedProjectConfig(config_path, config_path.parent, {}),
                (diagnostic,),
            )
        raw = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError) as exc:
        diagnostic = Diagnostic(
            "MARDAS-E102",
            "error",
            f"Could not read project configuration: {exc}",
            path=config_path,
        )
        return ConfigLoadResult(
            LoadedProjectConfig(config_path, config_path.parent, {}), (diagnostic,)
        )
    except tomllib.TOMLDecodeError as exc:
        line, column = _toml_location(exc)
        diagnostic = Diagnostic(
            "MARDAS-E103",
            "error",
            f"Invalid TOML: {exc}",
            path=config_path,
            line=line,
            column=column,
            hint="Fix the TOML syntax before rendering or validating the project.",
        )
        return ConfigLoadResult(
            LoadedProjectConfig(config_path, config_path.parent, {}), (diagnostic,)
        )

    diagnostics: list[Diagnostic] = []
    schema_version = raw.get("schema_version", CONFIG_SCHEMA_VERSION)
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        diagnostics.append(
            Diagnostic(
                "MARDAS-E104",
                "error",
                "schema_version must be an integer.",
                path=config_path,
            )
        )
    elif schema_version != CONFIG_SCHEMA_VERSION:
        diagnostics.append(
            Diagnostic(
                "MARDAS-E105",
                "error",
                f"Unsupported schema_version {schema_version}; supported version is {CONFIG_SCHEMA_VERSION}.",
                path=config_path,
            )
        )

    for key, value in raw.items():
        if key == "schema_version":
            continue
        if key not in _ALLOWED_SECTIONS:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E106",
                    "error",
                    f"Unknown configuration section [{key}].",
                    path=config_path,
                )
            )
            continue
        if not isinstance(value, dict):
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E107",
                    "error",
                    f"Configuration section [{key}] must be a table.",
                    path=config_path,
                )
            )
            continue
        for child_key in value:
            if child_key not in _ALLOWED_KEYS[key]:
                diagnostics.append(
                    Diagnostic(
                        "MARDAS-E108",
                        "error",
                        f"Unknown configuration key {key}.{child_key}.",
                        path=config_path,
                        hint="Run `mrs-md2pdf explain-config <input>` to inspect supported effective values.",
                    )
                )

    validated: dict[str, Any] = {}
    for field in CONFIG_FIELDS:
        section = raw.get(field.section)
        if not isinstance(section, dict) or field.key not in section:
            continue
        value = section[field.key]
        try:
            value = field.validator(value)
        except ConfigValueError as exc:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E109",
                    "error",
                    f"Invalid value for {field.dotted_key}: {exc}.",
                    path=config_path,
                )
            )
            continue
        if field.dest == "bibliography_sources":
            resolved_sources: list[Path] = []
            project_root = config_path.parent.resolve()
            for raw_source in value:
                source_path = Path(str(raw_source)).expanduser()
                if source_path.is_absolute():
                    diagnostics.append(
                        Diagnostic(
                            "MARDAS-E118",
                            "error",
                            "Bibliography paths must be relative to the project configuration.",
                            path=config_path,
                            hint="Keep bibliography sources inside the project root.",
                        )
                    )
                    continue
                resolved_path = (project_root / source_path).resolve(strict=False)
                try:
                    resolved_path.relative_to(project_root)
                except ValueError:
                    diagnostics.append(
                        Diagnostic(
                            "MARDAS-E119",
                            "error",
                            "Bibliography path escapes the project root.",
                            path=resolved_path,
                            hint="Move the source inside the project or remove parent-directory traversal.",
                        )
                    )
                    continue
                resolved_sources.append(resolved_path)
            value = tuple(resolved_sources)
        elif field.dest == "book_chapters":
            resolved_chapters: list[dict[str, Any]] = []
            project_root = config_path.parent.resolve()
            for chapter in value:
                chapter_path = Path(str(chapter["path"])).expanduser()
                if chapter_path.is_absolute():
                    diagnostics.append(
                        Diagnostic(
                            "MARDAS-E116",
                            "error",
                            "Book chapter paths must be relative to the project configuration.",
                            path=config_path,
                            hint="Keep every chapter inside the project root and use a relative path.",
                        )
                    )
                    continue
                resolved_path = (project_root / chapter_path).resolve()
                try:
                    resolved_path.relative_to(project_root)
                except ValueError:
                    diagnostics.append(
                        Diagnostic(
                            "MARDAS-E117",
                            "error",
                            "Book chapter path escapes the project root.",
                            path=resolved_path,
                            hint="Move the chapter inside the project or remove parent-directory traversal.",
                        )
                    )
                    continue
                resolved_chapters.append(
                    {"path": resolved_path, "title": chapter.get("title")}
                )
            value = tuple(resolved_chapters)
        elif field.path_value:
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = config_path.parent / path
            value = path.resolve()
        if field.invert:
            value = not value
        validated[field.dest] = value

    return ConfigLoadResult(
        LoadedProjectConfig(config_path, config_path.parent, validated),
        tuple(diagnostics),
    )


def apply_config_values(
    namespace: Any,
    config: LoadedProjectConfig,
    *,
    explicit_destinations: set[str],
) -> dict[str, str]:
    """Apply project values not explicitly supplied on the CLI.

    Returns a destination-to-source map for explain-config output.
    """

    sources: dict[str, str] = {}
    for dest, value in config.values.items():
        if dest.startswith("book_"):
            continue
        if dest in explicit_destinations:
            sources[dest] = "command line"
            continue
        setattr(namespace, dest, value)
        sources[dest] = str(config.path) if config.path else "built-in default"
    return sources

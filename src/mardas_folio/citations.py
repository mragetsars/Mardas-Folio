from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import quote, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

from .diagnostics import Diagnostic
from .markdown import language_family, ui_label

CITATION_STYLES = ("author-date", "numeric")
MAX_BIBLIOGRAPHY_SOURCES = 32
MAX_BIBLIOGRAPHY_SOURCE_BYTES = 10 * 1024 * 1024
MAX_BIBLIOGRAPHY_ENTRIES = 10_000
_RESERVED_CITATION_PREFIXES = ("fig:", "tbl:", "eq:", "lst:")
_CITATION_KEY_PATTERN = (
    r"[A-Za-z0-9](?:[A-Za-z0-9_:+/-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9_:+/-]*[A-Za-z0-9])?)*"
)
_CITATION_KEY_RE = re.compile(_CITATION_KEY_PATTERN)
_PARENTHETICAL_CANDIDATE_RE = re.compile(r"\[\s*@[^\[\]\n]*\]")
_NARRATIVE_CANDIDATE_RE = re.compile(
    rf"(?<![\w@])@(?P<key>{_CITATION_KEY_PATTERN})(?![A-Za-z0-9_:+/-])"
)
_SKIP_PARENTS = {"a", "code", "pre", "script", "style", "textarea", "kbd", "samp"}


@dataclass(frozen=True, slots=True)
class BibliographyAuthor:
    family: str = ""
    given: str = ""
    literal: str = ""

    @property
    def display(self) -> str:
        if self.literal:
            return self.literal
        if self.family and self.given:
            return f"{self.family}, {self.given}"
        return self.family or self.given

    @property
    def short(self) -> str:
        return self.literal or self.family or self.given


@dataclass(frozen=True, slots=True)
class BibliographyEntry:
    key: str
    entry_type: str
    title: str
    authors: tuple[BibliographyAuthor, ...] = ()
    year: str = "n.d."
    container_title: str = ""
    publisher: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    url: str = ""
    edition: str = ""
    source_path: Path | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "type": self.entry_type,
            "title": self.title,
            "authors": [
                {"family": item.family, "given": item.given, "literal": item.literal}
                for item in self.authors
            ],
            "year": self.year,
            "container_title": self.container_title,
            "publisher": self.publisher,
            "volume": self.volume,
            "issue": self.issue,
            "pages": self.pages,
            "doi": self.doi,
            "url": self.url,
            "edition": self.edition,
            **({"source_path": str(self.source_path)} if self.source_path else {}),
        }


@dataclass(frozen=True, slots=True)
class BibliographyLibrary:
    entries: dict[str, BibliographyEntry]
    sources: tuple[Path, ...] = ()

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(self.entries)


@dataclass(frozen=True, slots=True)
class CitationOptions:
    enabled: bool = False
    style: str = "author-date"
    title: str | None = None
    include_uncited: bool = False


@dataclass(frozen=True, slots=True)
class CitationProcessResult:
    body_html: str
    bibliography_html: str
    cited_keys: tuple[str, ...]
    entries: tuple[BibliographyEntry, ...]
    diagnostics: tuple[Diagnostic, ...]


class BibliographyParseError(ValueError):
    def __init__(self, message: str, *, line: int | None = None, column: int | None = None):
        super().__init__(message)
        self.line = line
        self.column = column


class _BibTexParser:
    def __init__(self, text: str):
        self.text = text.removeprefix("\ufeff")
        self.length = len(self.text)
        self.pos = 0
        self.macros: dict[str, str] = {
            "jan": "January",
            "feb": "February",
            "mar": "March",
            "apr": "April",
            "may": "May",
            "jun": "June",
            "jul": "July",
            "aug": "August",
            "sep": "September",
            "oct": "October",
            "nov": "November",
            "dec": "December",
        }

    def _location(self, pos: int | None = None) -> tuple[int, int]:
        point = self.pos if pos is None else pos
        line = self.text.count("\n", 0, point) + 1
        previous = self.text.rfind("\n", 0, point)
        return line, point - previous

    def error(self, message: str, pos: int | None = None) -> BibliographyParseError:
        line, column = self._location(pos)
        return BibliographyParseError(message, line=line, column=column)

    def _skip(self) -> None:
        while self.pos < self.length:
            char = self.text[self.pos]
            if char.isspace():
                self.pos += 1
                continue
            if char == "%":
                newline = self.text.find("\n", self.pos)
                self.pos = self.length if newline < 0 else newline + 1
                continue
            break

    def _identifier(self) -> str:
        self._skip()
        start = self.pos
        while self.pos < self.length and (
            self.text[self.pos].isalnum() or self.text[self.pos] in "_-.:/"
        ):
            self.pos += 1
        if self.pos == start:
            raise self.error("Expected an identifier")
        return self.text[start : self.pos]

    def _expect(self, expected: str) -> None:
        self._skip()
        if self.pos >= self.length or self.text[self.pos] != expected:
            raise self.error(f"Expected {expected!r}")
        self.pos += 1

    def _balanced(self, opening: str, closing: str) -> str:
        self._skip()
        if self.pos >= self.length or self.text[self.pos] != opening:
            raise self.error(f"Expected {opening!r}")
        self.pos += 1
        start = self.pos
        depth = 1
        escaped = False
        chunks: list[str] = []
        while self.pos < self.length:
            char = self.text[self.pos]
            if escaped:
                chunks.append(char)
                escaped = False
                self.pos += 1
                continue
            if char == "\\":
                chunks.append(char)
                escaped = True
                self.pos += 1
                continue
            if char == opening:
                depth += 1
                if depth > 1:
                    chunks.append(char)
                self.pos += 1
                continue
            if char == closing:
                depth -= 1
                if depth == 0:
                    self.pos += 1
                    return "".join(chunks)
                chunks.append(char)
                self.pos += 1
                continue
            chunks.append(char)
            self.pos += 1
        raise self.error(f"Unterminated value starting at offset {start}", start)

    def _quoted(self) -> str:
        self._skip()
        if self.pos >= self.length or self.text[self.pos] != '"':
            raise self.error("Expected a quoted value")
        self.pos += 1
        chunks: list[str] = []
        escaped = False
        brace_depth = 0
        while self.pos < self.length:
            char = self.text[self.pos]
            if escaped:
                chunks.append("\\" + char)
                escaped = False
                self.pos += 1
                continue
            if char == "\\":
                escaped = True
                self.pos += 1
                continue
            if char == "{":
                brace_depth += 1
                chunks.append(char)
                self.pos += 1
                continue
            if char == "}" and brace_depth:
                brace_depth -= 1
                chunks.append(char)
                self.pos += 1
                continue
            if char == '"' and brace_depth == 0:
                self.pos += 1
                return "".join(chunks)
            chunks.append(char)
            self.pos += 1
        raise self.error("Unterminated quoted value")

    def _bare(self) -> str:
        self._skip()
        start = self.pos
        while self.pos < self.length and self.text[self.pos] not in ",#})\n\r\t ":
            self.pos += 1
        if self.pos == start:
            raise self.error("Expected a bibliography value")
        token = self.text[start : self.pos]
        return self.macros.get(token.lower(), token)

    def _value(self, *, normalize: bool = True) -> str:
        parts: list[str] = []
        while True:
            self._skip()
            if self.pos >= self.length:
                raise self.error("Unexpected end of bibliography value")
            char = self.text[self.pos]
            if char == "{":
                parts.append(self._balanced("{", "}"))
            elif char == '"':
                parts.append(self._quoted())
            else:
                parts.append(self._bare())
            self._skip()
            if self.pos < self.length and self.text[self.pos] == "#":
                self.pos += 1
                continue
            break
        combined = "".join(parts)
        if normalize:
            return _normalize_bibtex_text(combined)
        return _normalize_space(_decode_latex_text(combined).replace("~", "\u00a0"))

    def _skip_entry(self, opening: str, closing: str) -> None:
        self.pos -= 1
        self._balanced(opening, closing)

    def parse(self) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        while True:
            self._skip()
            if self.pos >= self.length:
                break
            if self.text[self.pos] != "@":
                raise self.error("Expected '@' at the start of a BibTeX entry")
            self.pos += 1
            entry_type = self._identifier().lower()
            self._skip()
            if self.pos >= self.length or self.text[self.pos] not in "{(":
                raise self.error("Expected '{' or '(' after the BibTeX entry type")
            opening = self.text[self.pos]
            closing = "}" if opening == "{" else ")"
            self.pos += 1

            if entry_type in {"comment", "preamble"}:
                self._skip_entry(opening, closing)
                continue
            if entry_type == "string":
                name = self._identifier().lower()
                self._expect("=")
                value = self._value()
                self.macros[name] = value
                self._skip()
                if self.pos < self.length and self.text[self.pos] == ",":
                    self.pos += 1
                self._expect(closing)
                continue

            self._skip()
            key_start = self.pos
            while self.pos < self.length and self.text[self.pos] not in "," + closing:
                self.pos += 1
            key = self.text[key_start : self.pos].strip()
            if not key:
                raise self.error("BibTeX entry is missing a citation key", key_start)
            if self.pos >= self.length or self.text[self.pos] != ",":
                raise self.error("BibTeX entry must contain fields after its citation key")
            self.pos += 1
            fields: dict[str, str] = {"id": key, "type": entry_type}
            while True:
                self._skip()
                if self.pos >= self.length:
                    raise self.error("Unterminated BibTeX entry")
                if self.text[self.pos] == closing:
                    self.pos += 1
                    break
                name = self._identifier().lower()
                self._expect("=")
                if name in fields:
                    raise self.error(f"BibTeX field is defined more than once: {name}")
                fields[name] = self._value(normalize=name != "author")
                self._skip()
                if self.pos < self.length and self.text[self.pos] == ",":
                    self.pos += 1
                    continue
                if self.pos < self.length and self.text[self.pos] == closing:
                    self.pos += 1
                    break
                raise self.error("Expected ',' or the end of the BibTeX entry")
            entries.append(fields)
        return entries


def _normalize_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


_LATEX_ACCENTS = {
    "'": "\u0301",
    "`": "\u0300",
    '"': "\u0308",
    "^": "\u0302",
    "~": "\u0303",
    "=": "\u0304",
    ".": "\u0307",
    "u": "\u0306",
    "v": "\u030c",
    "H": "\u030b",
    "r": "\u030a",
    "c": "\u0327",
    "k": "\u0328",
}
_LATEX_SPECIALS = {
    "ss": "ß",
    "ae": "æ",
    "AE": "Æ",
    "oe": "œ",
    "OE": "Œ",
    "o": "ø",
    "O": "Ø",
    "l": "ł",
    "L": "Ł",
    "i": "ı",
}


def _decode_latex_text(value: str) -> str:
    text = value
    for command, replacement in _LATEX_SPECIALS.items():
        text = re.sub(rf"\\{command}(?![A-Za-z])", replacement, text)

    accent_pattern = re.compile(
        r"\\(?P<accent>['`\"^~=\.uvHrck])\s*"
        r"(?:\{(?P<braced>[A-Za-zı])\}|(?P<plain>[A-Za-zı]))"
    )

    def replace_accent(match: re.Match[str]) -> str:
        letter = match.group("braced") or match.group("plain") or ""
        return unicodedata.normalize("NFC", letter + _LATEX_ACCENTS[match.group("accent")])

    text = accent_pattern.sub(replace_accent, text)
    text = re.sub(r"\\(?:emph|textit|textbf|textrm|texttt)\{([^{}]*)\}", r"\1", text)
    return text


def _normalize_bibtex_text(value: str) -> str:
    text = _decode_latex_text(value).replace("~", "\u00a0")
    text = re.sub(r"\\([&%_$#{}])", r"\1", text)
    text = re.sub(r"[{}]", "", text)
    return _normalize_space(text)


def _split_top_level_authors(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
            index += 1
            continue
        if char == "}" and depth:
            depth -= 1
            index += 1
            continue
        if depth == 0:
            match = re.match(r"\s+and\s+", value[index:], flags=re.IGNORECASE)
            if match:
                parts.append(value[start:index])
                index += match.end()
                start = index
                continue
        index += 1
    parts.append(value[start:])
    return parts


def _split_bibtex_authors(value: str) -> tuple[BibliographyAuthor, ...]:
    if not value.strip():
        return ()
    parts = _split_top_level_authors(value)
    authors: list[BibliographyAuthor] = []
    for raw in parts:
        raw_text = raw.strip()
        if raw_text.startswith("{") and raw_text.endswith("}"):
            literal = _normalize_bibtex_text(raw_text[1:-1])
            if literal:
                authors.append(BibliographyAuthor(literal=literal))
            continue
        text = _normalize_bibtex_text(raw_text).strip()
        if not text:
            continue
        comma_parts = [part.strip() for part in re.split(r"[,،]", text)]
        if len(comma_parts) >= 2:
            family = comma_parts[0]
            given = " ".join(part for part in comma_parts[1:] if part)
            authors.append(BibliographyAuthor(family=family, given=given))
            continue
        words = text.split()
        if len(words) == 1:
            authors.append(BibliographyAuthor(family=words[0]))
        else:
            authors.append(BibliographyAuthor(family=words[-1], given=" ".join(words[:-1])))
    return tuple(authors)


def _csl_authors(value: Any) -> tuple[BibliographyAuthor, ...]:
    if not isinstance(value, list):
        return ()
    authors: list[BibliographyAuthor] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        literal = _normalize_space(item.get("literal"))
        family = _normalize_space(item.get("family"))
        given = _normalize_space(item.get("given"))
        if literal or family or given:
            authors.append(BibliographyAuthor(family=family, given=given, literal=literal))
    return tuple(authors)


def _csl_year(item: dict[str, Any]) -> str:
    issued = item.get("issued")
    if isinstance(issued, dict):
        parts = issued.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            return _normalize_space(parts[0][0]) or "n.d."
        literal = _normalize_space(issued.get("literal"))
        if literal:
            match = re.search(r"\b(?:1[0-9]{3}|20[0-9]{2}|2100)\b", literal)
            return match.group(0) if match else literal
    return _normalize_space(item.get("year")) or "n.d."


def _entry_from_mapping(item: dict[str, Any], source: Path) -> BibliographyEntry:
    key = _normalize_space(item.get("id") or item.get("key"))
    entry_type = _normalize_space(item.get("type") or "article").lower()
    title = _normalize_space(item.get("title"))
    if not key:
        raise ValueError("Bibliography entry is missing an id")
    if not _CITATION_KEY_RE.fullmatch(key):
        raise ValueError(f"Invalid bibliography key: {key}")
    if key.lower().startswith(_RESERVED_CITATION_PREFIXES):
        raise ValueError(f"Bibliography key uses a reserved cross-reference prefix: {key}")
    if not title:
        raise ValueError(f"Bibliography entry {key!r} is missing a title")

    if "author" in item and isinstance(item.get("author"), list):
        authors = _csl_authors(item.get("author"))
    else:
        authors = _split_bibtex_authors(_normalize_space(item.get("author")))

    year = (
        _csl_year(item)
        if isinstance(item.get("issued"), dict)
        else (_normalize_space(item.get("year")) or "n.d.")
    )
    container_title = _normalize_space(
        item.get("container-title")
        or item.get("container_title")
        or item.get("journal")
        or item.get("booktitle")
    )
    return BibliographyEntry(
        key=key,
        entry_type=entry_type,
        title=title,
        authors=authors,
        year=year,
        container_title=container_title,
        publisher=_normalize_space(
            item.get("publisher") or item.get("institution") or item.get("school")
        ),
        volume=_normalize_space(item.get("volume")),
        issue=_normalize_space(item.get("issue") or item.get("number")),
        pages=_normalize_space(item.get("page") or item.get("pages")).replace("--", "–"),
        doi=_normalize_space(item.get("DOI") or item.get("doi")),
        url=_normalize_space(item.get("URL") or item.get("url")),
        edition=_normalize_space(item.get("edition")),
        source_path=source,
    )


def _parse_source(path: Path) -> list[BibliographyEntry]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise BibliographyParseError(f"Could not inspect bibliography source: {exc}") from exc
    if size > MAX_BIBLIOGRAPHY_SOURCE_BYTES:
        raise BibliographyParseError(
            f"Bibliography source exceeds the {MAX_BIBLIOGRAPHY_SOURCE_BYTES}-byte safety limit"
        )
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise BibliographyParseError(f"Could not read bibliography source: {exc}") from exc

    suffix = path.suffix.lower()
    mappings: list[dict[str, Any]]
    if suffix == ".bib":
        mappings = [dict(item) for item in _BibTexParser(text).parse()]
    elif suffix == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BibliographyParseError(
                f"Invalid CSL JSON: {exc.msg}", line=exc.lineno, column=exc.colno
            ) from exc
        if isinstance(payload, dict) and isinstance(payload.get("items"), list):
            payload = payload["items"]
        if not isinstance(payload, list):
            raise BibliographyParseError("CSL JSON must contain an array of bibliography items")
        mappings = []
        for index, item in enumerate(payload, start=1):
            if not isinstance(item, dict):
                raise BibliographyParseError(f"CSL JSON item {index} must be an object")
            mappings.append(item)
    else:
        raise BibliographyParseError("Supported bibliography extensions are .bib and .json")

    entries: list[BibliographyEntry] = []
    for index, item in enumerate(mappings, start=1):
        try:
            entries.append(_entry_from_mapping(item, path))
        except ValueError as exc:
            raise BibliographyParseError(f"Invalid bibliography entry {index}: {exc}") from exc
    return entries


def load_bibliography(
    sources: Sequence[Path],
) -> tuple[BibliographyLibrary, tuple[Diagnostic, ...]]:
    diagnostics: list[Diagnostic] = []
    if len(sources) > MAX_BIBLIOGRAPHY_SOURCES:
        diagnostics.append(
            Diagnostic(
                "MARDAS-E701",
                "error",
                f"Too many bibliography sources; maximum is {MAX_BIBLIOGRAPHY_SOURCES}.",
            )
        )
        return BibliographyLibrary({}), tuple(diagnostics)

    entries: dict[str, BibliographyEntry] = {}
    resolved_sources: list[Path] = []
    seen_sources: set[Path] = set()
    for source in sources:
        path = Path(source).expanduser().resolve(strict=False)
        if path in seen_sources:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E701",
                    "error",
                    "Bibliography source is listed more than once.",
                    path=path,
                    hint="Keep each bibliography source only once.",
                )
            )
            continue
        seen_sources.add(path)
        resolved_sources.append(path)
        if not path.is_file():
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E701",
                    "error",
                    "Bibliography source does not exist or is not a regular file.",
                    path=path,
                    hint="Use a local .bib or CSL .json file inside the project root.",
                )
            )
            continue
        try:
            parsed = _parse_source(path)
        except BibliographyParseError as exc:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E702",
                    "error",
                    str(exc),
                    path=path,
                    line=exc.line,
                    column=exc.column,
                    hint="Fix the bibliography syntax before rendering or validating the project.",
                )
            )
            continue
        for entry in parsed:
            if entry.key in entries:
                previous = entries[entry.key]
                diagnostics.append(
                    Diagnostic(
                        "MARDAS-E703",
                        "error",
                        f"Bibliography key is defined more than once: {entry.key}",
                        path=path,
                        hint=(
                            f"Keep the key unique across all sources; the first definition is in {previous.source_path}."
                            if previous.source_path
                            else "Keep every bibliography key unique across all sources."
                        ),
                    )
                )
                continue
            if len(entries) >= MAX_BIBLIOGRAPHY_ENTRIES:
                diagnostics.append(
                    Diagnostic(
                        "MARDAS-E706",
                        "error",
                        f"Bibliography exceeds the {MAX_BIBLIOGRAPHY_ENTRIES}-entry safety limit.",
                        path=path,
                    )
                )
                return BibliographyLibrary(entries, tuple(resolved_sources)), tuple(diagnostics)
            entries[entry.key] = entry
    return BibliographyLibrary(entries, tuple(resolved_sources)), tuple(diagnostics)


def validate_citation_style(value: str | None) -> str:
    style = str(value or "author-date").strip().lower()
    if style not in CITATION_STYLES:
        raise ValueError(f"must be one of: {', '.join(CITATION_STYLES)}")
    return style


def _literal_parent(node: NavigableString) -> bool:
    for parent in node.parents:
        if isinstance(parent, Tag):
            if parent.name in _SKIP_PARENTS:
                return True
            classes = set(parent.get("class", []))
            if "md2pdf-bibliography" in classes or "md2pdf-citation" in classes:
                return True
    return False


def _parse_parenthetical_group(text: str) -> tuple[list[tuple[str, str]], str | None]:
    inner = text[1:-1].strip()
    if not inner:
        return [], "empty citation group"
    items: list[tuple[str, str]] = []
    for raw in inner.split(";"):
        part = raw.strip()
        if not part.startswith("@"):
            return [], "each citation in a group must start with @"
        content = part[1:].strip()
        match = _CITATION_KEY_RE.match(content)
        if not match:
            return [], "citation key is missing or invalid"
        key = match.group(0)
        remainder = content[match.end() :].strip()
        locator = ""
        if remainder:
            if not remainder.startswith(","):
                return [], "a citation locator must follow a comma"
            locator = _normalize_space(remainder[1:])
            if not locator:
                return [], "citation locator cannot be empty"
        items.append((key, locator))
    return items, None


def _citation_marker(
    soup: BeautifulSoup,
    *,
    mode: str,
    items: Sequence[tuple[str, str]],
    original: str,
) -> Tag:
    tag = soup.new_tag("span")
    tag["class"] = ["md2pdf-citation", f"md2pdf-citation--{mode}"]
    tag["data-md2pdf-citation-mode"] = mode
    tag["data-md2pdf-citation-items"] = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    tag["data-md2pdf-citation-original"] = original
    tag["dir"] = "auto"
    tag.string = original
    return tag


def annotate_citation_markup(
    body_html: str,
    *,
    path: Path | None = None,
) -> tuple[str, tuple[Diagnostic, ...]]:
    soup = BeautifulSoup(body_html, "html.parser")
    diagnostics: list[Diagnostic] = []
    for node in list(soup.find_all(string=True)):
        if not isinstance(node, NavigableString) or _literal_parent(node):
            continue
        text = str(node)
        fragments: list[str | Tag] = []
        cursor = 0
        changed = False
        for match in _PARENTHETICAL_CANDIDATE_RE.finditer(text):
            if match.start() > cursor:
                fragments.append(text[cursor : match.start()])
            original = match.group(0)
            items, error = _parse_parenthetical_group(original)
            if error:
                diagnostics.append(
                    Diagnostic(
                        "MARDAS-E705",
                        "error",
                        f"Malformed citation {original!r}: {error}.",
                        path=path,
                        hint="Use forms such as [@doe2024] or [@doe2024, p. 12; @smith2023].",
                    )
                )
                fragments.append(original)
            else:
                fragments.append(
                    _citation_marker(soup, mode="parenthetical", items=items, original=original)
                )
            cursor = match.end()
            changed = True
        if cursor < len(text):
            fragments.append(text[cursor:])
        if not changed:
            fragments = [text]

        narrative_fragments: list[str | Tag] = []
        for fragment in fragments:
            if isinstance(fragment, Tag):
                narrative_fragments.append(fragment)
                continue
            segment = fragment
            start = 0
            for match in _NARRATIVE_CANDIDATE_RE.finditer(segment):
                key = match.group("key")
                if key.lower().startswith(_RESERVED_CITATION_PREFIXES):
                    continue
                if match.start() > start:
                    narrative_fragments.append(segment[start : match.start()])
                narrative_fragments.append(
                    _citation_marker(
                        soup,
                        mode="narrative",
                        items=[(key, "")],
                        original=match.group(0),
                    )
                )
                start = match.end()
                changed = True
            if start < len(segment):
                narrative_fragments.append(segment[start:])
        if not changed:
            continue
        for fragment in reversed(narrative_fragments):
            node.insert_after(fragment if isinstance(fragment, Tag) else NavigableString(fragment))
        node.extract()
    return str(soup), tuple(diagnostics)


def _safe_fragment(prefix: str, key: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", key).strip("-._") or "entry"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{slug}-{digest}"


def _localized_digits(value: str | int, family: str) -> str:
    text = str(value)
    if family != "fa":
        return text
    return text.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _author_short(entry: BibliographyEntry, family: str) -> str:
    authors = [item.short for item in entry.authors if item.short]
    if not authors:
        title = entry.title
        return title if len(title) <= 36 else title[:33].rstrip() + "..."
    if len(authors) == 1:
        return authors[0]
    if len(authors) == 2:
        connector = " و " if family == "fa" else " & "
        return connector.join(authors)
    return f"{authors[0]} و همکاران" if family == "fa" else f"{authors[0]} et al."


def _author_full(entry: BibliographyEntry, family: str) -> str:
    names = [item.display for item in entry.authors if item.display]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    connector = " و " if family == "fa" else ", & "
    if len(names) == 2:
        return connector.join(names)
    return ", ".join(names[:-1]) + connector + names[-1]


def _entry_sort_key(entry: BibliographyEntry) -> tuple[str, str, str, str]:
    author = entry.authors[0].short if entry.authors else ""
    return (author.casefold(), entry.year.casefold(), entry.title.casefold(), entry.key.casefold())


def _safe_external_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    return value if parsed.scheme.lower() in {"http", "https"} and parsed.netloc else ""


def _format_bibliography_entry(
    entry: BibliographyEntry,
    *,
    family: str,
    display_year: str | None = None,
) -> str:
    author = _author_full(entry, family)
    chunks: list[str] = []
    if author:
        chunks.append(f'<span class="md2pdf-bib-authors">{html.escape(author)}</span>')
    chunks.append(
        f'<span class="md2pdf-bib-year">('
        f"{html.escape(_localized_digits(display_year or entry.year, family))})</span>"
    )
    chunks.append(f'<span class="md2pdf-bib-title">{html.escape(entry.title)}</span>')
    if entry.container_title:
        chunks.append(
            f'<span class="md2pdf-bib-container"><em>{html.escape(entry.container_title)}</em></span>'
        )
    publication: list[str] = []
    if entry.volume:
        publication.append(entry.volume)
    if entry.issue:
        publication.append(f"({entry.issue})")
    if entry.pages:
        publication.append(entry.pages)
    if publication:
        chunks.append(
            f'<span class="md2pdf-bib-publication">{html.escape(", ".join(publication))}</span>'
        )
    if entry.publisher:
        chunks.append(f'<span class="md2pdf-bib-publisher">{html.escape(entry.publisher)}</span>')
    if entry.edition:
        chunks.append(f'<span class="md2pdf-bib-edition">{html.escape(entry.edition)}</span>')
    doi_url = _safe_external_url(
        f"https://doi.org/{quote(entry.doi, safe='/:')}" if entry.doi else ""
    )
    external_url = doi_url or _safe_external_url(entry.url)
    if external_url:
        label = f"doi:{entry.doi}" if entry.doi else entry.url
        chunks.append(
            f'<a class="md2pdf-bib-link" href="{html.escape(external_url, quote=True)}">'
            f"{html.escape(label)}</a>"
        )
    return ". ".join(chunk for chunk in chunks if chunk).rstrip(". ") + "."


def _citation_item_text(
    entry: BibliographyEntry,
    *,
    style: str,
    number: int,
    locator: str,
    family: str,
    narrative: bool,
    display_year: str | None = None,
) -> str:
    author = _author_short(entry, family)
    if style == "numeric":
        if narrative:
            localized_number = _localized_digits(number, family)
            result = f"{author} [{localized_number}]" if author else f"[{localized_number}]"
        else:
            result = _localized_digits(number, family)
    elif narrative:
        result = f"{author} ({_localized_digits(display_year or entry.year, family)})"
    else:
        localized_year = _localized_digits(display_year or entry.year, family)
        comma = "، " if family == "fa" else ", "
        result = f"{author}{comma}{localized_year}" if author else localized_year
    if locator:
        comma = "، " if family == "fa" else ", "
        result += f"{comma}{locator}"
    return result


def _alpha_suffix(index: int) -> str:
    value = index
    chunks: list[str] = []
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        chunks.append(chr(ord("a") + remainder))
    return "".join(reversed(chunks))


def _author_year_labels(
    entries: Sequence[BibliographyEntry],
    *,
    family: str,
) -> dict[str, str]:
    groups: dict[tuple[str, str], list[BibliographyEntry]] = {}
    for entry in entries:
        identity = _author_short(entry, family).casefold()
        groups.setdefault((identity, entry.year.casefold()), []).append(entry)
    labels = {entry.key: entry.year for entry in entries}
    for group in groups.values():
        if len(group) < 2:
            continue
        for index, entry in enumerate(sorted(group, key=_entry_sort_key), start=1):
            labels[entry.key] = f"{entry.year}{_alpha_suffix(index)}"
    return labels


def _marker_items(marker: Tag) -> list[tuple[str, str]]:
    try:
        raw_items = json.loads(str(marker.get("data-md2pdf-citation-items") or "[]"))
    except json.JSONDecodeError:
        return []
    items: list[tuple[str, str]] = []
    if isinstance(raw_items, list):
        for raw in raw_items:
            if isinstance(raw, list) and len(raw) == 2:
                items.append((_normalize_space(raw[0]), _normalize_space(raw[1])))
    return items


def _diagnostic_path_for_marker(marker: Tag, fallback: Path | None) -> Path | None:
    section = marker.find_parent(attrs={"data-book-source": True})
    if isinstance(section, Tag):
        source = str(section.get("data-book-source") or "").strip()
        if source:
            base = (
                fallback
                if fallback is not None and fallback.is_dir()
                else (fallback.parent if fallback is not None else Path.cwd())
            )
            return (base / source).resolve(strict=False)
    return fallback


def resolve_citations(
    body_html: str,
    *,
    library: BibliographyLibrary,
    options: CitationOptions,
    lang: str | None = None,
    path: Path | None = None,
) -> CitationProcessResult:
    if not options.enabled:
        return CitationProcessResult(body_html, "", (), (), ())
    style = validate_citation_style(options.style)
    soup = BeautifulSoup(body_html, "html.parser")
    diagnostics: list[Diagnostic] = []
    cited_order: list[str] = []
    citation_numbers: dict[str, int] = {}
    first_citation_ids: dict[str, str] = {}
    occurrences: dict[str, int] = {}
    family = language_family(lang, soup.get_text(" ", strip=True))
    markers = list(soup.select("span.md2pdf-citation[data-md2pdf-citation-items]"))
    candidate_keys: list[str] = []
    for marker in markers:
        for key, _locator in _marker_items(marker):
            if key in library.entries and key not in candidate_keys:
                candidate_keys.append(key)
    if options.include_uncited:
        for key in library.entries:
            if key not in candidate_keys:
                candidate_keys.append(key)
    display_years = _author_year_labels(
        [library.entries[key] for key in candidate_keys],
        family=family,
    )

    for marker in markers:
        original = str(marker.get("data-md2pdf-citation-original") or marker.get_text())
        mode = str(marker.get("data-md2pdf-citation-mode") or "parenthetical")
        items = _marker_items(marker)
        if not items:
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E705",
                    "error",
                    f"Malformed citation marker: {original}",
                    path=_diagnostic_path_for_marker(marker, path),
                )
            )
            marker.name = "span"
            marker.attrs = {"class": ["md2pdf-citation", "md2pdf-citation--unresolved"]}
            marker.string = original
            continue

        rendered: list[Tag] = []
        for key, locator in items:
            entry = library.entries.get(key)
            if entry is None:
                diagnostics.append(
                    Diagnostic(
                        "MARDAS-E704",
                        "error",
                        f"Citation key is not defined: {key}",
                        path=_diagnostic_path_for_marker(marker, path),
                        hint="Add the key to a configured .bib or CSL .json bibliography source.",
                    )
                )
                unresolved = soup.new_tag("span")
                unresolved["class"] = ["md2pdf-citation-item", "md2pdf-citation-item--unresolved"]
                unresolved.string = f"@{key}"
                rendered.append(unresolved)
                continue
            if key not in citation_numbers:
                citation_numbers[key] = len(citation_numbers) + 1
                cited_order.append(key)
            occurrences[key] = occurrences.get(key, 0) + 1
            cite_id = _safe_fragment("cite", f"{key}-{occurrences[key]}")
            first_citation_ids.setdefault(key, cite_id)
            anchor = soup.new_tag("a")
            anchor["id"] = cite_id
            anchor["href"] = f"#{_safe_fragment('bib', key)}"
            anchor["class"] = ["md2pdf-citation-item", "md2pdf-citation-item--resolved"]
            anchor["data-md2pdf-citation-key"] = key
            anchor["dir"] = "auto"
            anchor.string = _citation_item_text(
                entry,
                style=style,
                number=citation_numbers[key],
                locator=locator,
                family=family,
                narrative=mode == "narrative",
                display_year=display_years.get(key),
            )
            rendered.append(anchor)

        marker.clear()
        marker["class"] = [
            "md2pdf-citation",
            f"md2pdf-citation--{mode}",
            "md2pdf-citation--resolved",
        ]
        marker.attrs.pop("data-md2pdf-citation-items", None)
        marker.attrs.pop("data-md2pdf-citation-original", None)
        if mode == "parenthetical":
            marker.append(NavigableString("[" if style == "numeric" else "("))
            if style == "numeric":
                separator = "، " if family == "fa" else ", "
            else:
                separator = "؛ " if family == "fa" else "; "
            for index, item in enumerate(rendered):
                if index:
                    marker.append(NavigableString(separator))
                marker.append(item)
            marker.append(NavigableString("]" if style == "numeric" else ")"))
        else:
            for index, item in enumerate(rendered):
                if index:
                    marker.append(NavigableString("; "))
                marker.append(item)

    selected_keys = list(cited_order)
    if options.include_uncited:
        uncited = [entry for key, entry in library.entries.items() if key not in citation_numbers]
        uncited.sort(key=_entry_sort_key)
        for entry in uncited:
            if style == "numeric":
                citation_numbers[entry.key] = len(citation_numbers) + 1
            selected_keys.append(entry.key)
    selected_entries = [library.entries[key] for key in selected_keys if key in library.entries]
    if style == "author-date":
        selected_entries.sort(key=_entry_sort_key)

    title = options.title or ui_label(
        "bibliography_title", lang=lang, text_hint=soup.get_text(" ", strip=True)
    )
    bibliography_html = ""
    if selected_entries:
        list_tag = "ol" if style == "numeric" else "div"
        item_tag = "li" if style == "numeric" else "div"
        items_html: list[str] = []
        for entry in selected_entries:
            number = citation_numbers.get(entry.key)
            prefix = (
                f'<span class="md2pdf-bib-number">[{_localized_digits(number, family)}]</span> '
                if style == "numeric" and number
                else ""
            )
            backlink = ""
            first_id = first_citation_ids.get(entry.key)
            if first_id:
                backlink_label = "بازگشت به ارجاع" if family == "fa" else "Back to citation"
                backlink = (
                    f' <a class="md2pdf-bib-backref" href="#{html.escape(first_id)}" '
                    f'aria-label="{html.escape(backlink_label)}">↩</a>'
                )
            items_html.append(
                f'<{item_tag} class="md2pdf-bibliography-entry" dir="auto" '
                f'id="{html.escape(_safe_fragment("bib", entry.key))}" '
                f'data-md2pdf-bibliography-key="{html.escape(entry.key, quote=True)}">'
                f"{prefix}{_format_bibliography_entry(entry, family=family, display_year=display_years.get(entry.key))}{backlink}"
                f"</{item_tag}>"
            )
        bibliography_html = (
            '<section class="md2pdf-bibliography" id="bibliography">'
            f'<h2 class="md2pdf-bibliography-heading">{html.escape(title)}</h2>'
            f'<{list_tag} class="md2pdf-bibliography-items md2pdf-bibliography-items--{style}">'
            f"{''.join(items_html)}</{list_tag}></section>"
        )

    return CitationProcessResult(
        body_html=str(soup),
        bibliography_html=bibliography_html,
        cited_keys=tuple(cited_order),
        entries=tuple(selected_entries),
        diagnostics=tuple(diagnostics),
    )

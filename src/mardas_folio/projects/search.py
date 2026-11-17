"""Bounded project search, safe regular expressions, and bibliography lookup."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from ..citations import MAX_BIBLIOGRAPHY_ENTRIES, load_bibliography
from ..diagnostics import Diagnostic, has_errors
from ..render_contracts import CancellationCallback
from .discovery import _contains_path, _safe_workspace_file
from .files import (
    _read_bytes,
)
from .loading import (
    workspace_diagnostics_payload,
)
from .models import ProjectWorkspace, WorkspaceError

MAX_WORKSPACE_SEARCH_RESULTS = 500
MAX_WORKSPACE_SEARCH_QUERY_CHARS = 512
_PERSIAN_LETTER_FOLD = str.maketrans(
    {
        "ي": "ی",  # ARABIC YEH        -> FARSI YEH
        "ى": "ی",  # ALEF MAKSURA      -> FARSI YEH
        "ك": "ک",  # ARABIC KAF        -> KEHEH
    }
)
MAX_WORKSPACE_SEARCH_LINE_CHARS = 2_000
_UNSAFE_REGEX_TOKENS = (
    "(?=",
    "(?!",
    "(?<=",
    "(?<!",
    "(?P",
    "\\1",
    "\\2",
    "\\3",
    "\\4",
    "\\5",
    "\\6",
    "\\7",
    "\\8",
    "\\9",
    "\\g<",
)
_LARGE_REGEX_REPEAT = re.compile(r"\{\s*(\d+)(?:\s*,\s*(\d*)?)?\s*\}")
_MAX_REGEX_REPEAT = 1_000


def fold_persian_letters(value: str) -> str:
    """Spell the Persian/Arabic letter variants one way, preserving length."""

    return value.translate(_PERSIAN_LETTER_FOLD)


def _has_quantified_regex_group(query: str) -> bool:
    escaped = False
    in_character_class = False
    for index, character in enumerate(query):
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if in_character_class:
            if character == "]":
                in_character_class = False
            continue
        if character == "[":
            in_character_class = True
            continue
        if character != ")" or index + 1 >= len(query):
            continue
        following = query[index + 1]
        if following in {"*", "+", "?"}:
            return True
        if following == "{" and _LARGE_REGEX_REPEAT.match(query, index + 1):
            return True
    return False


def _variable_regex_quantifier_count(query: str) -> int:
    """Count variable-width quantifiers while ignoring literals and character classes."""

    count = 0
    escaped = False
    in_character_class = False
    index = 0
    while index < len(query):
        character = query[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\":
            escaped = True
            index += 1
            continue
        if in_character_class:
            if character == "]":
                in_character_class = False
            index += 1
            continue
        if character == "[":
            in_character_class = True
            index += 1
            continue
        if character in {"*", "+", "?"}:
            if character == "?" and index > 0 and query[index - 1] == "(":
                index += 1
                continue
            count += 1
            index += 1
            if index < len(query) and query[index] in {"?", "+"}:
                index += 1
            continue
        if character == "{":
            repeat = _LARGE_REGEX_REPEAT.match(query, index)
            if repeat is not None:
                lower = int(repeat.group(1))
                upper_text = repeat.group(2)
                if "," in repeat.group(0) and (not upper_text or int(upper_text) != lower):
                    count += 1
                index = repeat.end()
                if index < len(query) and query[index] in {"?", "+"}:
                    index += 1
                continue
        index += 1
    return count


def _compile_workspace_regex(query: str, flags: int) -> re.Pattern[str]:
    """Compile a deliberately limited regex suitable for interactive project search."""

    unsafe_repeat = any(
        int(match.group(1)) > _MAX_REGEX_REPEAT
        or (match.group(2) and int(match.group(2)) > _MAX_REGEX_REPEAT)
        for match in _LARGE_REGEX_REPEAT.finditer(query)
    )
    if (
        any(token in query for token in _UNSAFE_REGEX_TOKENS)
        or _has_quantified_regex_group(query)
        or unsafe_repeat
        or _variable_regex_quantifier_count(query) > 1
    ):
        raise WorkspaceError(
            "Project regex uses an advanced or potentially expensive construct.",
            code="unsafe_project_search_regex",
        )
    try:
        return re.compile(query, flags)
    except re.error as exc:
        raise WorkspaceError(
            f"Invalid regular expression: {exc}",
            code="invalid_project_search_regex",
        ) from exc


def search_workspace(
    workspace: ProjectWorkspace,
    query: str,
    *,
    regex: bool = False,
    case_sensitive: bool = False,
    max_results: int = 200,
    cancelled: CancellationCallback | None = None,
) -> dict[str, object]:
    """Search bounded UTF-8 project files without escaping the workspace root."""

    if not isinstance(query, str) or not query:
        raise WorkspaceError(
            "Project search query is required.",
            code="invalid_project_search",
        )
    if len(query) > MAX_WORKSPACE_SEARCH_QUERY_CHARS:
        raise WorkspaceError(
            f"Project search query exceeds {MAX_WORKSPACE_SEARCH_QUERY_CHARS} characters.",
            code="project_search_query_too_large",
            status=413,
        )
    limit = max(1, min(int(max_results or 200), MAX_WORKSPACE_SEARCH_RESULTS))
    flags = 0 if case_sensitive else re.IGNORECASE
    pattern: re.Pattern[str] | None = None
    # Both kinds of search run as a compiled pattern over the folded line, so a
    # reported column is an offset into the line as it is stored. Case-folding
    # the line instead would not be: `casefold` may return a longer string than
    # it was given — ß becomes ss — and every column after such a character
    # would be reported past where it is.
    if regex:
        # Folding the pattern is safe: none of the letters involved is a regular
        # expression metacharacter, and it keeps a regex answering the same way
        # a literal search does.
        pattern = _compile_workspace_regex(fold_persian_letters(query), flags)
    else:
        pattern = re.compile(re.escape(fold_persian_letters(query)), flags)
    matches: list[dict[str, object]] = []
    searched_files = 0
    truncated = False
    truncated_lines = 0

    for item in workspace.files:
        if cancelled and cancelled():
            raise WorkspaceError(
                "Project search was cancelled.",
                code="project_search_cancelled",
                status=499,
            )
        if item.kind not in {"markdown", "bibliography", "json", "toml", "text", "config"}:
            continue
        try:
            path = _safe_workspace_file(workspace, item.path)
            data = _read_bytes(path)
            content = data.decode("utf-8-sig")
        except (WorkspaceError, UnicodeDecodeError):
            continue
        searched_files += 1
        for line_number, line in enumerate(content.splitlines(), start=1):
            if cancelled and line_number % 128 == 0 and cancelled():
                raise WorkspaceError(
                    "Project search was cancelled.",
                    code="project_search_cancelled",
                    status=499,
                )
            search_line = line[:MAX_WORKSPACE_SEARCH_LINE_CHARS] if regex else line
            if len(search_line) < len(line):
                truncated_lines += 1
            # Literal search is linear, so search the entire bounded file.
            # Stream matches instead of allocating every column on a long line.
            for match in pattern.finditer(fold_persian_letters(search_line)):
                if len(matches) >= limit:
                    truncated = True
                    break
                start = max(0, match.start() - 100)
                end = min(len(line), start + 300)
                preview = line[start:end].strip()
                if start:
                    preview = "…" + preview
                if end < len(line):
                    preview += "…"
                matches.append(
                    {
                        "path": item.path,
                        "line": line_number,
                        "column": match.start() + 1,
                        "preview": preview,
                    }
                )
            if truncated:
                break
        if truncated:
            break

    return {
        "query": query,
        "regex": bool(regex),
        "case_sensitive": bool(case_sensitive),
        "searched_files": searched_files,
        "matches": matches,
        "truncated": truncated,
        "truncated_lines": truncated_lines,
        "regex_line_limit": MAX_WORKSPACE_SEARCH_LINE_CHARS if regex else None,
        "max_results": limit,
    }


def workspace_bibliography(
    workspace: ProjectWorkspace,
    *,
    query: str = "",
    cited_keys: Iterable[str] = (),
    max_results: int = 500,
) -> dict[str, object]:
    """Return a searchable, read-only bibliography index for the desktop UI."""

    raw_sources = tuple(workspace.config.values.get("bibliography_sources") or ())
    sources: list[Path] = []
    diagnostics: list[Diagnostic] = []
    root = workspace.root.resolve()
    for raw_source in raw_sources:
        source = Path(raw_source).expanduser().resolve(strict=False)
        if source.is_symlink() or not _contains_path(root, source):
            diagnostics.append(
                Diagnostic(
                    "MARDAS-E701",
                    "error",
                    "Project bibliography source must be a regular file inside the project root.",
                    path=source,
                )
            )
            continue
        sources.append(source)

    library, library_diagnostics = load_bibliography(sources)
    diagnostics.extend(library_diagnostics)
    normalized_query = str(query or "").strip().casefold()
    cited = {str(key).strip() for key in cited_keys if str(key).strip()}
    limit = max(1, min(int(max_results or 500), MAX_BIBLIOGRAPHY_ENTRIES))
    entries: list[dict[str, object]] = []
    matched_total = 0
    for key in sorted(library.entries, key=str.casefold):
        entry = library.entries[key]
        searchable = " ".join(
            [
                entry.key,
                entry.title,
                entry.year,
                entry.container_title,
                entry.publisher,
                " ".join(author.display for author in entry.authors),
            ]
        ).casefold()
        if normalized_query and normalized_query not in searchable:
            continue
        matched_total += 1
        if len(entries) >= limit:
            continue
        payload = entry.to_dict()
        payload["cited"] = entry.key in cited
        if entry.source_path is not None:
            payload["source_path"] = (
                entry.source_path.resolve(strict=False).relative_to(root).as_posix()
                if _contains_path(root, entry.source_path.resolve(strict=False))
                else entry.source_path.name
            )
        entries.append(payload)

    return {
        "sources": [
            source.relative_to(root).as_posix()
            for source in sources
            if _contains_path(root, source)
        ],
        "entries": entries,
        "entry_count": len(library.entries),
        "matched_count": matched_total,
        "query": str(query or ""),
        "diagnostics": workspace_diagnostics_payload(workspace, diagnostics),
        "ok": not has_errors(diagnostics),
        "truncated": matched_total > len(entries),
    }

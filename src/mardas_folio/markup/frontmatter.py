"""markup — frontmatter implementation."""
from __future__ import annotations

import re
from typing import Any
try:
    import yaml
except Exception:  # pragma: no cover - declared dependency
    yaml = None


FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)


MAX_FRONTMATTER_DEPTH = 16


MAX_FRONTMATTER_NODES = 2048


MAX_FRONTMATTER_SCALAR_CHARS = 256 * 1024


class MarkdownInputError(ValueError):
    """Raised when Markdown metadata or document structure is invalid or unsafe."""


def _validate_frontmatter_graph(value: Any) -> None:
    """Reject recursive or excessively amplified YAML object graphs."""
    node_count = 0
    scalar_chars = 0
    active: set[int] = set()

    def visit(item: Any, depth: int) -> None:
        nonlocal node_count, scalar_chars
        node_count += 1
        if node_count > MAX_FRONTMATTER_NODES:
            raise MarkdownInputError(
                f"Front matter exceeds the {MAX_FRONTMATTER_NODES}-item complexity limit."
            )
        if depth > MAX_FRONTMATTER_DEPTH:
            raise MarkdownInputError(
                f"Front matter exceeds the maximum nesting depth of {MAX_FRONTMATTER_DEPTH}."
            )

        if isinstance(item, dict):
            identity = id(item)
            if identity in active:
                raise MarkdownInputError("Front matter contains a recursive YAML alias.")
            active.add(identity)
            try:
                for key, child in item.items():
                    visit(key, depth + 1)
                    visit(child, depth + 1)
            finally:
                active.remove(identity)
            return
        if isinstance(item, (list, tuple, set)):
            identity = id(item)
            if identity in active:
                raise MarkdownInputError("Front matter contains a recursive YAML alias.")
            active.add(identity)
            try:
                for child in item:
                    visit(child, depth + 1)
            finally:
                active.remove(identity)
            return

        scalar_chars += len(str(item))
        if scalar_chars > MAX_FRONTMATTER_SCALAR_CHARS:
            raise MarkdownInputError(
                "Front matter scalar content exceeds the supported size limit."
            )

    visit(value, 0)


def extract_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw = match.group(1)
    body = text[match.end() :]
    if yaml is None:
        return {}, body
    try:
        data = yaml.safe_load(raw) or {}
    except Exception as exc:
        problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        mark = getattr(exc, "problem_mark", None)
        location = f" at line {mark.line + 1}, column {mark.column + 1}" if mark else ""
        raise MarkdownInputError(f"Invalid YAML front matter{location}: {problem}") from exc
    if not isinstance(data, dict):
        raise MarkdownInputError("YAML front matter must contain a mapping/object at the top level.")
    _validate_frontmatter_graph(data)
    return data, body

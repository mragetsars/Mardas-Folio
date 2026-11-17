"""Code-region protection and inline/display math transformation."""

from __future__ import annotations

import html
import re
from typing import Any

from markdown_it import MarkdownIt

INLINE_MATH_RE = re.compile(r"(?<!\\)\$(?![\s$])(.+?)(?<!\\)\$(?!\d)")
DISPLAY_MATH_FENCE_RE = re.compile(r"^\s*\$\$\s*$")
FENCE_RE = re.compile(r"^\s*(```+|~~~+)")
PROTECTED_CODE_TOKEN_PREFIX = "\ue000FOLIOCODE"  # nosec B105
PROTECTED_CODE_TOKEN_SUFFIX = "\ue001"  # nosec B105


def _replace_outside_inline_code(
    text: str,
    pattern: re.Pattern[str],
    repl: Any,
) -> str:
    """Apply a regex replacement only outside Markdown inline code spans.

    The Markdown parser will later turn backtick-delimited spans into ``<code>``.
    Pre-processing steps such as math and footnote expansion must therefore leave
    literal examples like ``$x$`` and ``[^note]`` untouched. This lightweight
    scanner follows the common Markdown rule that a code span opens with one or
    more backticks and closes with the same run length on the same line.
    """
    output: list[str] = []
    index = 0
    while index < len(text):
        marker_match = re.search(r"`+", text[index:])
        if not marker_match:
            output.append(pattern.sub(repl, text[index:]))
            break

        start = index + marker_match.start()
        marker = marker_match.group(0)
        output.append(pattern.sub(repl, text[index:start]))

        content_start = start + len(marker)
        close = text.find(marker, content_start)
        if close == -1:
            output.append(pattern.sub(repl, text[start:]))
            break

        output.append(text[start : close + len(marker)])
        index = close + len(marker)
    return "".join(output)


def _protected_code_token(index: int) -> str:
    return f"{PROTECTED_CODE_TOKEN_PREFIX}{index:08d}{PROTECTED_CODE_TOKEN_SUFFIX}"


def _protect_code_regions(markdown: str) -> tuple[str, list[str]]:
    """Protect fenced, indented, and multiline inline code before preprocessing."""
    protected: list[str] = []

    def store(value: str) -> str:
        token = _protected_code_token(len(protected))
        protected.append(value)
        return token

    lines = markdown.splitlines(keepends=True)
    block_output: list[str] = []
    parser = MarkdownIt("gfm-like", {"html": True, "linkify": False})
    code_ranges = {
        token.map[0]: token.map[1]
        for token in parser.parse(markdown)
        if token.type in {"fence", "code_block"} and token.map
    }
    index = 0
    while index < len(lines):
        end = code_ranges.get(index)
        if end is not None:
            segment = "".join(lines[index:end])
            ending = (
                "\r\n" if segment.endswith("\r\n") else ("\n" if segment.endswith("\n") else "")
            )
            block_output.append(store(segment) + ending)
            index = end
            continue

        block_output.append(lines[index])
        index += 1

    text = "".join(block_output)
    inline_output: list[str] = []
    cursor = 0
    while cursor < len(text):
        opening = re.search(r"`+", text[cursor:])
        if not opening:
            inline_output.append(text[cursor:])
            break
        start = cursor + opening.start()
        marker = opening.group(0)
        inline_output.append(text[cursor:start])
        search_from = start + len(marker)
        close = -1
        while True:
            candidate = text.find(marker, search_from)
            if candidate < 0:
                break
            before_is_tick = candidate > 0 and text[candidate - 1] == "`"
            after_index = candidate + len(marker)
            after_is_tick = after_index < len(text) and text[after_index] == "`"
            if not before_is_tick and not after_is_tick:
                close = candidate
                break
            search_from = candidate + len(marker)
        if close < 0:
            inline_output.append(text[start:])
            break
        end = close + len(marker)
        inline_output.append(store(text[start:end]))
        cursor = end
    return "".join(inline_output), protected


def _restore_code_regions(markdown: str, protected: list[str]) -> str:
    for index, value in enumerate(protected):
        token = _protected_code_token(index)
        if value.endswith("\r\n"):
            markdown = markdown.replace(token + "\r\n", value)
        elif value.endswith("\n"):
            markdown = markdown.replace(token + "\n", value)
        markdown = markdown.replace(token, value)
    return markdown


def _fence_transition(
    line: str, in_fence: bool, fence_char: str, fence_len: int
) -> tuple[bool, str, int]:
    match = FENCE_RE.match(line)
    if not match:
        return in_fence, fence_char, fence_len

    marker = match.group(1)
    marker_char = marker[0]
    marker_len = len(marker)
    if not in_fence:
        return True, marker_char, marker_len
    if marker_char == fence_char and marker_len >= fence_len:
        return False, "", 0
    return in_fence, fence_char, fence_len


def protect_and_transform_math(markdown: str) -> str:
    """Transform $...$ and $$...$$ into HTML MathJax wrappers outside code."""
    output: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    in_display_math = False
    display_buffer: list[str] = []

    def repl_inline(match: re.Match[str]) -> str:
        expr = match.group(1).strip()
        if not expr:
            return match.group(0)
        return f'<span class="math inline">\\\\({html.escape(expr)}\\\\)</span>'

    for line in markdown.splitlines(keepends=True):
        next_in_fence, next_fence_char, next_fence_len = _fence_transition(
            line, in_fence, fence_char, fence_len
        )
        fence_changed = (next_in_fence, next_fence_char, next_fence_len) != (
            in_fence,
            fence_char,
            fence_len,
        )
        if fence_changed and not in_display_math:
            in_fence, fence_char, fence_len = next_in_fence, next_fence_char, next_fence_len
            output.append(line)
            continue

        if in_fence:
            output.append(line)
            continue

        if DISPLAY_MATH_FENCE_RE.match(line):
            if in_display_math:
                expr = "".join(display_buffer).strip()
                output.append(f'<div class="math display">$${html.escape(expr)}$$</div>\n')
                display_buffer.clear()
                in_display_math = False
            else:
                in_display_math = True
                display_buffer.clear()
            continue

        if in_display_math:
            display_buffer.append(line)
            continue

        output.append(_replace_outside_inline_code(line, INLINE_MATH_RE, repl_inline))

    if in_display_math:
        output.append("$$\n")
        output.extend(display_buffer)
    return "".join(output)

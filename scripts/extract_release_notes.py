#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHANGELOG = ROOT / "docs" / "CHANGELOG.md"


def extract_release_notes(text: str, *, version: str) -> str:
    pattern = re.compile(
        rf"(?ms)^##\s+\[?{re.escape(version)}\]?[^\n]*\n(?P<body>.*?)(?=^##\s+|\Z)"
    )
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"Changelog does not contain a section for version {version}")
    body = match.group("body").strip()
    if not body:
        raise ValueError(f"Changelog section for version {version} is empty")
    if len(body.encode("utf-8")) > 128 * 1024:
        raise ValueError("Release notes exceed the size limit")
    return f"# Mardas Studio {version}\n\n{body}\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract release notes from the project changelog")
    parser.add_argument("--version", required=True)
    parser.add_argument("--changelog", type=Path, default=DEFAULT_CHANGELOG)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        changelog = args.changelog.expanduser().resolve(strict=True)
        notes = extract_release_notes(changelog.read_text(encoding="utf-8"), version=args.version)
        output = args.output.expanduser().resolve(strict=False)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_name(output.name + ".tmp")
        temporary.write_text(notes, encoding="utf-8", newline="\n")
        temporary.replace(output)
    except (OSError, ValueError) as exc:
        print(f"Release note extraction failed: {exc}", file=sys.stderr)
        return 2
    print(f"Release notes: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

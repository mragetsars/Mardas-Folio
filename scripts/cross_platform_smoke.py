#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import tempfile
from pathlib import Path

from mardas_folio.renderer import PdfOptions, convert
from pypdf import PdfReader


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a cross-platform Unicode-path smoke PDF")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-ms", type=int, default=180000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mardas-platform-") as temp_name:
        root = Path(temp_name) / "گزارش آزمایشی with spaces"
        root.mkdir()
        source = root / "سند mixed.md"
        source.write_text(
            "---\n"
            "title: Cross-platform smoke\n"
            "language: fa-IR\n"
            "direction: rtl\n"
            "---\n\n"
            "# آزمون Cross-platform\n\n"
            "متن فارسی و `inline code` و English 123.\n\n"
            "| ستون | Value |\n|---|---:|\n| نمونه | 42 |\n",
            encoding="utf-8",
        )
        convert(
            PdfOptions(
                input_path=source,
                output_path=output,
                cover=False,
                toc=True,
                timeout_ms=args.timeout_ms,
                progress=None,
            )
        )
    reader = PdfReader(str(output))
    if not reader.pages:
        raise SystemExit("Cross-platform smoke produced an empty PDF")
    language = str(reader.trailer["/Root"].get("/Lang", "")).lower()
    if language not in {"fa", "fa-ir", "fa_ir"}:
        raise SystemExit(f"Cross-platform smoke lost the document language: {language!r}")
    payload = {
        "ok": True,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "output": output.name,
        "size": output.stat().st_size,
        "pages": len(reader.pages),
        "language": language,
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

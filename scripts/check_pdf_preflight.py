#!/usr/bin/env python3
"""Preflight generated PDFs for release-quality visual QA.

The checker intentionally uses external command-line tools when available
(`pdffonts` and `pdftoppm`) because those are the same low-level utilities that
surface PDF portability problems in CI and desktop viewers.  It is conservative:
missing tools are reported as skipped checks by default, while render failures or
unexpected syntax warnings become actionable findings.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from visual_qa import run_command, write_json

BAD_BBOX_RE = re.compile(r"Bad bounding box in Type 3 glyph", re.IGNORECASE)
SYNTAX_WARNING_RE = re.compile(r"(?:Syntax|Syntax Error|Syntax Warning):\s*(.+)", re.IGNORECASE)


@dataclasses.dataclass(frozen=True, slots=True)
class FontRecord:
    name: str
    type: str
    encoding: str
    embedded: str
    subset: str
    unicode: str


@dataclasses.dataclass(frozen=True, slots=True)
class PreflightFinding:
    severity: str
    code: str
    message: str


def parse_pdffonts_output(output: str) -> list[FontRecord]:
    """Parse the fixed-width output produced by ``pdffonts``."""
    records: list[FontRecord] = []
    lines = output.splitlines()
    if len(lines) < 3:
        return records
    for line in lines[2:]:
        if not line.strip():
            continue
        # pdffonts aligns the first three columns in fixed-width fields; the
        # final object IDs are intentionally ignored because they are not stable.
        name = line[:37].strip()
        font_type = line[37:55].strip()
        encoding = line[55:72].strip()
        rest = line[72:].split()
        if len(rest) < 3 or not name:
            continue
        records.append(
            FontRecord(
                name=name,
                type=font_type,
                encoding=encoding,
                embedded=rest[0],
                subset=rest[1],
                unicode=rest[2],
            )
        )
    return records


def classify_preflight_stderr(stderr: str) -> list[PreflightFinding]:
    findings: list[PreflightFinding] = []
    for line in stderr.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if BAD_BBOX_RE.search(stripped):
            findings.append(
                PreflightFinding(
                    severity="warning",
                    code="bad_type3_bbox",
                    message=stripped,
                )
            )
            continue
        if SYNTAX_WARNING_RE.search(stripped):
            findings.append(
                PreflightFinding(
                    severity="error",
                    code="pdf_syntax_warning",
                    message=stripped,
                )
            )
    return findings


def _tool_missing(name: str) -> PreflightFinding | None:
    if shutil.which(name):
        return None
    return PreflightFinding(
        severity="warning",
        code="tool_missing",
        message=f"{name} is not installed; skipped that preflight check",
    )


def _run_pdffonts(pdf: Path, *, timeout: int) -> tuple[list[FontRecord], list[PreflightFinding]]:
    missing = _tool_missing("pdffonts")
    if missing:
        return [], [missing]
    completed = run_command(
        ["pdffonts", str(pdf)], timeout=timeout, description=f"pdffonts for {pdf}"
    )
    fonts = parse_pdffonts_output(completed.stdout)
    findings: list[PreflightFinding] = []
    for font in fonts:
        if font.embedded.lower() != "yes":
            findings.append(
                PreflightFinding(
                    severity="error",
                    code="font_not_embedded",
                    message=f"{pdf}: font is not embedded: {font.name}",
                )
            )
        if font.unicode.lower() != "yes":
            findings.append(
                PreflightFinding(
                    severity="warning",
                    code="font_without_unicode_map",
                    message=f"{pdf}: font has no ToUnicode map: {font.name}",
                )
            )
    return fonts, findings


def _run_pdftoppm(
    pdf: Path, *, pages: Sequence[int], dpi: int, timeout: int
) -> list[PreflightFinding]:
    missing = _tool_missing("pdftoppm")
    if missing:
        return [missing]
    findings: list[PreflightFinding] = []
    with tempfile.TemporaryDirectory(prefix="mardas-preflight-") as tmp:
        tmpdir = Path(tmp)
        for page in pages:
            prefix = tmpdir / f"page-{page:02d}"
            command = [
                "pdftoppm",
                "-png",
                "-r",
                str(dpi),
                "-f",
                str(page),
                "-singlefile",
                str(pdf),
                str(prefix),
            ]
            completed = run_command(
                command, timeout=timeout, description=f"pdftoppm preflight for {pdf} page {page}"
            )
            findings.extend(classify_preflight_stderr(completed.stderr))
            if not prefix.with_suffix(".png").is_file():
                findings.append(
                    PreflightFinding(
                        severity="error",
                        code="raster_missing",
                        message=f"{pdf}: pdftoppm did not create page {page} PNG",
                    )
                )
    return findings


def preflight_pdf(pdf: Path, *, pages: Sequence[int], dpi: int, timeout: int) -> dict[str, object]:
    fonts, font_findings = _run_pdffonts(pdf, timeout=timeout)
    raster_findings = _run_pdftoppm(pdf, pages=pages, dpi=dpi, timeout=timeout)
    findings = [*font_findings, *raster_findings]
    type3_fonts = sorted({font.name for font in fonts if "Type 3" in font.type})
    return {
        "pdf": str(pdf),
        "pages": list(pages),
        "font_count": len(fonts),
        "type3_fonts": type3_fonts,
        "findings": [dataclasses.asdict(finding) for finding in findings],
        "passed": not any(finding.severity == "error" for finding in findings),
    }


def _parse_pages(value: str) -> tuple[int, ...]:
    pages = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    if not pages or any(page < 1 for page in pages):
        raise argparse.ArgumentTypeError(
            "pages must be a comma-separated list of positive integers"
        )
    return pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdfs", nargs="+", type=Path, help="PDF files to preflight")
    parser.add_argument(
        "--output", "--output-dir", dest="output", type=Path, help="Write JSON report to this path"
    )
    parser.add_argument(
        "--pages",
        type=_parse_pages,
        default=(1, 2),
        help="Comma-separated 1-based pages to rasterize",
    )
    parser.add_argument("--dpi", type=int, default=72)
    parser.add_argument(
        "--timeout", type=int, default=60, help="Seconds per external preflight command"
    )
    parser.add_argument(
        "--fail-on-warning", action="store_true", help="Treat warning findings as failures"
    )
    args = parser.parse_args(argv)

    reports = [
        preflight_pdf(pdf, pages=args.pages, dpi=args.dpi, timeout=args.timeout)
        for pdf in args.pdfs
    ]
    payload = {"reports": reports}
    if args.output:
        write_json(args.output, payload)
    else:
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")

    failed = False
    for report in reports:
        for finding in report["findings"]:
            severity = str(finding["severity"])
            if severity == "error" or (args.fail_on_warning and severity == "warning"):
                failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run the bounded Chromium guide-render smoke check used by ``scripts/check.sh``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from visual_qa import run_command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.environ.get("TMPDIR", "/tmp")) / "mardas-folio-smoke.pdf",
        help="Output PDF path for the smoke render.",
    )
    parser.add_argument(
        "--command-timeout",
        type=float,
        default=float(os.environ.get("MARDAS_RENDER_SMOKE_TIMEOUT", "240")),
        help="Outer command timeout in seconds. Defaults to MARDAS_RENDER_SMOKE_TIMEOUT or 240.",
    )
    parser.add_argument(
        "--timeout-ms",
        default=os.environ.get("MARDAS_TIMEOUT_MS", "180000"),
        help="Chromium page timeout in milliseconds. Defaults to MARDAS_TIMEOUT_MS or 180000.",
    )
    args = parser.parse_args(argv)
    output_path = args.output if args.output.is_absolute() else (Path.cwd() / args.output).resolve()
    os.chdir(Path(__file__).resolve().parents[1])

    command = [
        sys.executable,
        "-m",
        "mardas_folio.cli",
        "docs/guides/GUIDE.en.md",
        "-o",
        str(output_path),
        "--toc",
        "--style",
        "github",
        "--palette",
        "blue",
        "--mode",
        "light",
        "--timeout-ms",
        str(args.timeout_ms),
        "--progress",
        "off",
    ]
    completed = run_command(command, timeout=args.command_timeout, description="render smoke")
    for stream_output in (completed.stdout, completed.stderr):
        if stream_output:
            print(stream_output, end="" if stream_output.endswith("\n") else "\n")
    if not output_path.is_file() or output_path.stat().st_size <= 0:
        raise SystemExit(f"Render smoke did not create a non-empty PDF: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

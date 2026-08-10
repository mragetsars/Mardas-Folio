#!/usr/bin/env python3
"""Benchmark representative Mardas Folio documents with reproducible inputs."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import platform
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    import resource as _resource
except ImportError:  # Windows has no POSIX resource module.
    _resource = None

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from pypdf import PdfReader  # noqa: E402

from mardas_md2pdf import __version__  # noqa: E402
from mardas_md2pdf.renderer import PdfOptions, RenderSession, convert  # noqa: E402


@dataclass(frozen=True, slots=True)
class BenchmarkProfile:
    name: str
    sections: int
    math_every: int
    code_every: int
    cover: bool = True


PROFILES = {
    "small": BenchmarkProfile("small", 2, 1, 1),
    "pages50": BenchmarkProfile("pages50", 50, 5, 4),
    "pages250": BenchmarkProfile("pages250", 250, 10, 7),
    "pages500": BenchmarkProfile("pages500", 500, 12, 9),
    "editor-loop": BenchmarkProfile("editor-loop", 20, 5, 4, cover=False),
}


def _document_text(profile: BenchmarkProfile) -> str:
    chunks = [
        "---\n",
        'title: "Mardas Performance Benchmark"\n',
        'author: "Mardas QA"\n',
        "lang: en\n",
        "---\n\n",
        "# Performance Benchmark\n",
    ]
    for index in range(1, profile.sections + 1):
        chunks.extend(
            [
                f"\n## Section {index}\n\n",
                f"Deterministic benchmark content for section {index}. ",
                "Mixed فارسی English ۱۴۰۵. " * 8,
                "\n\n| Metric | Value |\n|---|---:|\n",
                f"| Index | {index} |\n| Score | 0.98 |\n",
            ]
        )
        if profile.math_every and index % profile.math_every == 0:
            chunks.append(f"\n$$\nE_{{{index}}} = mc^2 + {index}\n$$\n")
        if profile.code_every and index % profile.code_every == 0:
            chunks.append(
                f'\n```python title="Section {index}"\n'
                f"for item in range({index % 20 + 1}):\n"
                "    print(item)\n"
                "```\n"
            )
        if index != profile.sections:
            chunks.append('\n<div class="page-break"></div>\n')
    return "".join(chunks)


def _run_profile(
    profile: BenchmarkProfile,
    *,
    output_dir: Path,
    repeats: int,
    reuse_browser: bool,
    timeout_ms: int,
) -> dict[str, object]:
    source = output_dir / f"{profile.name}.md"
    source.write_text(_document_text(profile), encoding="utf-8", newline="\n")
    session = RenderSession() if reuse_browser else None
    if session is not None:
        session.__enter__()
    runs: list[dict[str, object]] = []
    try:
        for repeat in range(repeats):
            output = output_dir / (
                f"{profile.name}-{'session' if reuse_browser else 'cold'}-{repeat + 1}.pdf"
            )
            started = time.perf_counter()
            convert(
                PdfOptions(
                    input_path=source,
                    output_path=output,
                    cover=profile.cover,
                    toc=True,
                    no_mathjax=False,
                    timeout_ms=timeout_ms,
                ),
                session=session,
            )
            elapsed = time.perf_counter() - started
            data = output.read_bytes()
            runs.append(
                {
                    "repeat": repeat + 1,
                    "seconds": elapsed,
                    "pdf_pages": len(PdfReader(str(output)).pages),
                    "size_bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
            gc.collect()
    finally:
        if session is not None:
            session.close()
    seconds = [float(run["seconds"]) for run in runs]
    warm_seconds = seconds[1:] if reuse_browser and len(seconds) > 1 else seconds
    return {
        "profile": profile.name,
        "sections": profile.sections,
        "mode": "session" if reuse_browser else "cold",
        "repeats": repeats,
        "browser_launches": session.launch_count if session is not None else repeats,
        "seconds_mean": statistics.mean(seconds),
        "seconds_min": min(seconds),
        "seconds_max": max(seconds),
        "warm_seconds_mean": statistics.mean(warm_seconds),
        "runs": runs,
    }


def _selected_profiles(value: str) -> list[BenchmarkProfile]:
    names = [item.strip() for item in value.split(",") if item.strip()]
    unknown = [name for name in names if name not in PROFILES]
    if unknown:
        raise ValueError(f"Unknown benchmark profile(s): {', '.join(unknown)}")
    return [PROFILES[name] for name in names]


def _modes(value: str) -> Iterable[bool]:
    if value == "cold":
        return (False,)
    if value == "session":
        return (True,)
    return (False, True)


def _peak_rss_kib() -> int | None:
    """Return process peak RSS in KiB when the platform exposes it."""

    if _resource is None:
        return None
    peak = int(_resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        # macOS reports bytes; Linux reports KiB.
        return peak // 1024
    return peak


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profiles",
        default="small,pages50,editor-loop",
        help=f"Comma-separated profiles. Available: {', '.join(PROFILES)}",
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--mode", choices=("cold", "session", "both"), default="both")
    parser.add_argument("--timeout-ms", type=int, default=240_000)
    parser.add_argument("--output-dir", type=Path, default=Path("build/performance"))
    parser.add_argument("--output", type=Path, help="JSON report path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.repeats < 1 or args.repeats > 20:
        parser.error("--repeats must be between 1 and 20")
    if args.timeout_ms < 1_000:
        parser.error("--timeout-ms must be at least 1000")
    try:
        profiles = _selected_profiles(args.profiles)
    except ValueError as exc:
        parser.error(str(exc))
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, object]] = []
    for profile in profiles:
        for reuse_browser in _modes(args.mode):
            results.append(
                _run_profile(
                    profile,
                    output_dir=output_dir,
                    repeats=args.repeats,
                    reuse_browser=reuse_browser,
                    timeout_ms=args.timeout_ms,
                )
            )
    payload = {
        "project": "Mardas Folio",
        "version": __version__,
        "python": sys.version,
        "platform": platform.platform(),
        "peak_rss_kib": _peak_rss_kib(),
        "results": results,
    }
    report_path = (args.output or output_dir / "benchmark.json").expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    print(f"Benchmark report written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

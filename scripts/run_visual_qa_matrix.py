#!/usr/bin/env python3
"""Run the full visual QA matrix in bounded, resumable chunks.

This wrapper is the release-grade entry point for exhaustive visual QA.  It keeps
individual subprocesses small, writes active-chunk heartbeat data, skips already
completed chunks when ``--resume`` is enabled, and delegates actual rendering to
the focused audit scripts.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path
from collections.abc import Callable
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from mardas_folio.appearance import MODES, PALETTES_ORDER, STYLES  # noqa: E402
from visual_qa import ensure_clean_dir, run_command, write_json  # noqa: E402


@dataclasses.dataclass(frozen=True, slots=True)
class AppearanceCase:
    style: str
    palette: str
    mode: str

    @property
    def name(self) -> str:
        return f"{self.style}-{self.palette}-{self.mode}"

    @property
    def triple(self) -> str:
        return f"{self.style}:{self.palette}:{self.mode}"


def chunked(items: Sequence[AppearanceCase], size: int) -> list[tuple[AppearanceCase, ...]]:
    if size < 1:
        raise ValueError("chunk size must be at least 1")
    return [tuple(items[index : index + size]) for index in range(0, len(items), size)]


def build_cases(
    *,
    styles: Iterable[str] = STYLES,
    palettes: Iterable[str] = PALETTES_ORDER,
    modes: Iterable[str] = MODES,
) -> tuple[AppearanceCase, ...]:
    return tuple(AppearanceCase(style, palette, mode) for style in styles for palette in palettes for mode in modes)


def _utc_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _child_manifest_complete(output_dir: Path, *, expected_count: int) -> bool:
    """Return whether a child audit chunk has a complete success manifest."""
    payload = _read_json(output_dir / "manifest.json")
    counts = payload.get("counts")
    if isinstance(counts, dict):
        return (
            counts.get("requested") == expected_count
            and counts.get("completed") == expected_count
            and counts.get("failed") == 0
        )
    matrix = payload.get("matrix")
    if isinstance(matrix, dict):
        return matrix.get("completed") == expected_count and matrix.get("failed") == 0
    return False


def _run(
    command: list[str],
    *,
    timeout: int,
    heartbeat_interval: float = 30.0,
    on_heartbeat: Callable[[float], None] | None = None,
) -> dict[str, object]:
    """Run a child audit chunk without pipe-related process hangs."""
    started = time.monotonic()

    def heartbeat(elapsed: float) -> None:
        if on_heartbeat is not None:
            on_heartbeat(elapsed)

    try:
        completed = run_command(
            command,
            timeout=timeout,
            description="visual QA chunk",
            heartbeat=heartbeat,
            heartbeat_interval=heartbeat_interval,
        )
    except RuntimeError as exc:
        return {
            "command": command,
            "returncode": 1,
            "duration_seconds": round(time.monotonic() - started, 3),
            "stdout_tail": "",
            "stderr_tail": str(exc)[-4000:],
        }
    return {
        "command": command,
        "returncode": completed.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def _append_common_args(
    command: list[str],
    *,
    output_dir: Path,
    render_png: bool,
    png_dpi: int,
    render_timeout: int,
    raster_timeout: int,
    resume: bool,
    fail_fast: bool,
) -> list[str]:
    command.extend(
        [
            "--output-dir",
            str(output_dir),
            "--timeout",
            str(render_timeout),
            "--raster-timeout",
            str(raster_timeout),
        ]
    )
    if render_png:
        command.extend(["--render-png", "--png-dpi", str(png_dpi)])
    if resume:
        command.append("--resume")
    if fail_fast:
        command.append("--fail-fast")
    return command


def _write_summary(path: Path, summary: dict[str, object]) -> None:
    write_json(path, summary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("build/visual-qa/full"))
    parser.add_argument("--clean", action="store_true", help="Delete output directory before running")
    parser.add_argument("--resume", action="store_true", help="Skip completed child audit chunks")
    parser.add_argument("--fail-fast", action="store_true", help="Stop after the first failed chunk")
    parser.add_argument("--render-png", action="store_true", help="Raster representative pages for galleries")
    parser.add_argument("--png-dpi", type=int, default=72)
    parser.add_argument("--appearance-chunk-size", type=int, default=7)
    parser.add_argument("--feature-chunk-size", type=int, default=4)
    parser.add_argument("--max-cases", type=int, help="Limit total appearance cases for quick local smoke runs")
    parser.add_argument("--render-timeout", type=int, default=120, help="Seconds per child PDF render")
    parser.add_argument("--raster-timeout", type=int, default=60, help="Seconds per child raster command")
    parser.add_argument("--chunk-timeout", type=int, default=900, help="Seconds allowed for each child audit chunk")
    parser.add_argument(
        "--chunk-heartbeat-seconds",
        type=float,
        default=30.0,
        help="Seconds between active-chunk heartbeat summary updates",
    )
    parser.add_argument("--skip-appearance", action="store_true")
    parser.add_argument("--skip-features", action="store_true")
    args = parser.parse_args(argv)

    if args.clean:
        ensure_clean_dir(args.output_dir)
    else:
        args.output_dir.mkdir(parents=True, exist_ok=True)

    cases = build_cases()
    if args.max_cases is not None:
        cases = cases[: args.max_cases]
    appearance_chunks = chunked(cases, args.appearance_chunk_size)
    feature_chunks = chunked(cases, args.feature_chunk_size)
    summary: dict[str, object] = {
        "case_count": len(cases),
        "appearance_chunk_count": 0 if args.skip_appearance else len(appearance_chunks),
        "feature_chunk_count": 0 if args.skip_features else len(feature_chunks),
        "started_at": _utc_timestamp(),
        "records": [],
    }
    summary_path = args.output_dir / "summary.json"

    def run_child(
        kind: str,
        index: int,
        total: int,
        output_dir: Path,
        command: list[str],
        *,
        expected_count: int,
    ) -> bool:
        print(f"{kind} chunk {index}/{total}", flush=True)
        if args.resume and _child_manifest_complete(output_dir, expected_count=expected_count):
            result = {
                "kind": kind,
                "chunk": index,
                "total": total,
                "command": command,
                "returncode": 0,
                "skipped": True,
                "reason": "completed manifest reused",
                "started_at": _utc_timestamp(),
                "finished_at": _utc_timestamp(),
                "duration_seconds": 0,
                "stdout_tail": "",
                "stderr_tail": "",
            }
            summary["records"].append(result)  # type: ignore[index]
            _write_summary(summary_path, summary)
            return True

        started_at = _utc_timestamp()
        summary["active_chunk"] = {
            "kind": kind,
            "chunk": index,
            "total": total,
            "started_at": started_at,
            "last_heartbeat_at": started_at,
            "elapsed_seconds": 0,
            "command": command,
        }
        _write_summary(summary_path, summary)

        def heartbeat(elapsed: float) -> None:
            active = dict(summary.get("active_chunk") or {})
            active.update({"last_heartbeat_at": _utc_timestamp(), "elapsed_seconds": round(elapsed, 3)})
            summary["active_chunk"] = active
            _write_summary(summary_path, summary)

        result = _run(
            command,
            timeout=args.chunk_timeout,
            heartbeat_interval=args.chunk_heartbeat_seconds,
            on_heartbeat=heartbeat,
        )
        result.update(
            {
                "kind": kind,
                "chunk": index,
                "total": total,
                "started_at": started_at,
                "finished_at": _utc_timestamp(),
            }
        )
        summary["records"].append(result)  # type: ignore[index]
        summary.pop("active_chunk", None)
        _write_summary(summary_path, summary)
        ok = result["returncode"] == 0
        if not ok and args.fail_fast:
            return False
        return True

    script_dir = Path(__file__).resolve().parent
    if not args.skip_appearance:
        for index, chunk in enumerate(appearance_chunks, start=1):
            output_dir = args.output_dir / "appearance" / f"chunk-{index:03d}"
            command = [
                sys.executable,
                str(script_dir / "audit_appearance_matrix.py"),
                "--appearances",
                ",".join(case.triple for case in chunk),
            ]
            _append_common_args(
                command,
                output_dir=output_dir,
                render_png=args.render_png,
                png_dpi=args.png_dpi,
                render_timeout=args.render_timeout,
                raster_timeout=args.raster_timeout,
                resume=args.resume,
                fail_fast=args.fail_fast,
            )
            if not run_child(
                "appearance", index, len(appearance_chunks), output_dir, command, expected_count=len(chunk)
            ):
                return 1

    if not args.skip_features:
        for index, chunk in enumerate(feature_chunks, start=1):
            output_dir = args.output_dir / "features" / f"chunk-{index:03d}"
            command = [
                sys.executable,
                str(script_dir / "audit_pdf_features.py"),
                "--appearances",
                ",".join(case.triple for case in chunk),
            ]
            _append_common_args(
                command,
                output_dir=output_dir,
                render_png=args.render_png,
                png_dpi=args.png_dpi,
                render_timeout=args.render_timeout,
                raster_timeout=args.raster_timeout,
                resume=args.resume,
                fail_fast=args.fail_fast,
            )
            if args.render_png:
                command.extend(["--pages", "1,2,3"])
            if not run_child(
                "features", index, len(feature_chunks), output_dir, command, expected_count=len(chunk)
            ):
                return 1

    failures = [record for record in summary["records"] if record["returncode"] != 0]  # type: ignore[index]
    summary["finished_at"] = _utc_timestamp()
    summary["failed_chunks"] = len(failures)
    _write_summary(summary_path, summary)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

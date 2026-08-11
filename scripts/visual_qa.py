#!/usr/bin/env python3
"""Small shared helpers for Mardas visual QA scripts.

The helpers intentionally avoid optional image dependencies.  They only rely on
``pdftoppm`` for PDF rasterization and Python's standard library for basic PNG
inspection and pixel comparisons.  This keeps the scripts suitable for CI
artifacts without adding runtime package dependencies.
"""

from __future__ import annotations

import dataclasses
import hashlib
import html
import json
import os
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any, Iterable, Sequence

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclasses.dataclass(frozen=True, slots=True)
class PngImage:
    width: int
    height: int
    pixels: bytes
    channels: int


@dataclasses.dataclass(frozen=True, slots=True)
class PngStats:
    path: str
    width: int
    height: int
    mean_luma: float
    dark_ratio: float
    light_ratio: float
    sha256: str


@dataclasses.dataclass(frozen=True, slots=True)
class PngDiff:
    path: str
    width: int
    height: int
    changed_ratio: float
    rms_delta: float
    max_delta: int


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_png_chunks(path: Path) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise ValueError(f"{path} is not a PNG file")
    offset = len(PNG_SIGNATURE)
    header: dict[str, Any] | None = None
    idat_parts: list[bytes] = []
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError(f"{path} has a truncated PNG chunk")
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        offset += 8
        chunk_data = data[offset : offset + length]
        offset += length + 4  # skip CRC
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            header = {
                "width": width,
                "height": height,
                "bit_depth": bit_depth,
                "color_type": color_type,
                "compression": compression,
                "filter_method": filter_method,
                "interlace": interlace,
            }
        elif chunk_type == b"IDAT":
            idat_parts.append(chunk_data)
        elif chunk_type == b"IEND":
            break
    if header is None:
        raise ValueError(f"{path} is missing a PNG header")
    return header, b"".join(idat_parts)


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def read_png(path: Path) -> PngImage:
    header, compressed = _read_png_chunks(path)
    width = int(header["width"])
    height = int(header["height"])
    bit_depth = int(header["bit_depth"])
    color_type = int(header["color_type"])
    interlace = int(header["interlace"])
    if bit_depth != 8:
        raise ValueError(f"{path} uses unsupported PNG bit depth {bit_depth}; expected 8")
    if interlace != 0:
        raise ValueError(f"{path} uses unsupported interlaced PNG encoding")
    channels_by_color_type = {0: 1, 2: 3, 6: 4}
    if color_type not in channels_by_color_type:
        raise ValueError(f"{path} uses unsupported PNG color type {color_type}")
    channels = channels_by_color_type[color_type]
    row_bytes = width * channels
    raw = zlib.decompress(compressed)
    expected = (row_bytes + 1) * height
    if len(raw) != expected:
        raise ValueError(f"{path} has unexpected decoded PNG size {len(raw)}; expected {expected}")

    rows: list[bytes] = []
    previous = bytearray(row_bytes)
    index = 0
    for _row in range(height):
        filter_type = raw[index]
        index += 1
        scanline = bytearray(raw[index : index + row_bytes])
        index += row_bytes
        for i, value in enumerate(scanline):
            left = scanline[i - channels] if i >= channels else 0
            up = previous[i]
            up_left = previous[i - channels] if i >= channels else 0
            if filter_type == 0:
                recon = value
            elif filter_type == 1:
                recon = value + left
            elif filter_type == 2:
                recon = value + up
            elif filter_type == 3:
                recon = value + ((left + up) // 2)
            elif filter_type == 4:
                recon = value + _paeth(left, up, up_left)
            else:
                raise ValueError(f"unsupported PNG filter type {filter_type}")
            scanline[i] = recon & 0xFF
        rows.append(bytes(scanline))
        previous = scanline
    return PngImage(width=width, height=height, pixels=b"".join(rows), channels=channels)


def png_stats(path: Path) -> PngStats:
    image = read_png(path)
    luma_values: list[float] = []
    channels = image.channels
    for i in range(0, len(image.pixels), channels):
        if channels == 1:
            red = green = blue = image.pixels[i]
        else:
            red, green, blue = image.pixels[i], image.pixels[i + 1], image.pixels[i + 2]
        luma_values.append((0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255.0)
    mean_luma = sum(luma_values) / len(luma_values) if luma_values else 0.0
    dark_ratio = sum(1 for value in luma_values if value < 0.08) / len(luma_values) if luma_values else 0.0
    light_ratio = sum(1 for value in luma_values if value > 0.92) / len(luma_values) if luma_values else 0.0
    return PngStats(
        path=str(path),
        width=image.width,
        height=image.height,
        mean_luma=round(mean_luma, 6),
        dark_ratio=round(dark_ratio, 6),
        light_ratio=round(light_ratio, 6),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def compare_pngs(baseline: Path, candidate: Path) -> PngDiff:
    left = read_png(baseline)
    right = read_png(candidate)
    if (left.width, left.height, left.channels) != (right.width, right.height, right.channels):
        return PngDiff(
            path=str(candidate),
            width=right.width,
            height=right.height,
            changed_ratio=1.0,
            rms_delta=255.0,
            max_delta=255,
        )
    changed = 0
    max_delta = 0
    squared_total = 0
    comparisons = 0
    for a, b in zip(left.pixels, right.pixels, strict=True):
        delta = abs(a - b)
        if delta:
            changed += 1
        max_delta = max(max_delta, delta)
        squared_total += delta * delta
        comparisons += 1
    rms_delta = (squared_total / comparisons) ** 0.5 if comparisons else 0.0
    return PngDiff(
        path=str(candidate),
        width=right.width,
        height=right.height,
        changed_ratio=round(changed / comparisons if comparisons else 0.0, 6),
        rms_delta=round(rms_delta, 6),
        max_delta=max_delta,
    )




def _command_env(extra_env: dict[str, str] | None = None) -> dict[str, str]:
    """Return an environment that can import the checkout-local ``src`` tree."""
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    src = repo_root() / "src"
    if src.is_dir():
        existing = env.get("PYTHONPATH", "")
        parts = [str(src), *(part for part in existing.split(os.pathsep) if part)]
        env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(parts))
    return env


def _process_group_kwargs() -> dict[str, object]:
    """Return subprocess kwargs that make timeout cleanup kill child processes too."""
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Terminate a process and its children as aggressively as the platform allows."""
    if process.poll() is not None:
        return
    if os.name != "nt":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except Exception:
            process.terminate()
    else:  # pragma: no cover - Windows-specific fallback.
        process.terminate()
    try:
        process.wait(timeout=3)
        return
    except subprocess.TimeoutExpired:
        pass
    if os.name != "nt":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except Exception:
            process.kill()
    else:  # pragma: no cover - Windows-specific fallback.
        process.kill()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:  # pragma: no cover - defensive; kill should finish.
        pass


def run_command(
    command: Sequence[str],
    *,
    timeout: float,
    description: str,
    heartbeat: Callable[[float], None] | None = None,
    heartbeat_interval: float = 30.0,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command with process-tree cleanup and captured output.

    ``subprocess.run(timeout=...)`` only kills the direct child.  The visual QA
    scripts frequently launch Python, Playwright, Chromium, and Poppler helpers;
    if any grandchild remains alive, the audit matrix can hang indefinitely.
    This helper starts a process group/session and terminates the whole tree on
    timeout so a single broken render becomes a reported failure instead of a
    blocked batch job.  Long runners may pass ``heartbeat`` so wrapper scripts can
    update a summary file while a child audit is still active.
    """
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as stdout_file, tempfile.TemporaryFile(
        mode="w+t", encoding="utf-8"
    ) as stderr_file:
        process = subprocess.Popen(
            list(command),
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            env=_command_env(env),
            **_process_group_kwargs(),
        )
        started = time.monotonic()
        deadline = started + timeout
        next_heartbeat = started + max(0.5, heartbeat_interval)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process_tree(process)
                stdout_file.seek(0)
                stderr_file.seek(0)
                stdout = stdout_file.read()
                stderr = stderr_file.read()
                output = "\n".join(part for part in [stdout, stderr] if part).strip()
                if output:
                    output = "\n" + output
                raise RuntimeError(f"{description} timed out after {timeout:g}s{output}")
            try:
                process.wait(timeout=min(remaining, max(0.5, heartbeat_interval)))
                break
            except subprocess.TimeoutExpired:
                now = time.monotonic()
                if heartbeat is not None and now >= next_heartbeat:
                    heartbeat(now - started)
                    next_heartbeat = now + max(0.5, heartbeat_interval)
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read()
        stderr = stderr_file.read()
    completed = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    if completed.returncode != 0:
        output = "\n".join(part for part in [completed.stdout, completed.stderr] if part).strip()
        if output:
            output = "\n" + output
        raise RuntimeError(f"{description} failed with exit code {completed.returncode}{output}")
    return completed


def render_pdf_pages(
    pdf_path: Path,
    output_dir: Path,
    *,
    pages: Sequence[int] = (1,),
    dpi: int = 72,
    prefix: str | None = None,
    raster_timeout: int = 60,
) -> list[Path]:
    if shutil.which("pdftoppm") is None:
        raise RuntimeError("pdftoppm is required for PNG visual QA renders")
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    stem = prefix or pdf_path.stem
    for page in pages:
        output_prefix = output_dir / f"{stem}-p{page:02d}"
        command = [
            "pdftoppm",
            "-png",
            "-r",
            str(dpi),
            "-f",
            str(page),
            "-singlefile",
            str(pdf_path),
            str(output_prefix),
        ]
        run_command(command, timeout=raster_timeout, description=f"pdftoppm render for {pdf_path} page {page}")
        png_path = output_prefix.with_suffix(".png")
        if not png_path.is_file():
            raise RuntimeError(f"pdftoppm did not create {png_path}")
        rendered.append(png_path)
    return rendered


def run_mardas_cli(
    source: Path,
    output_pdf: Path,
    *,
    style: str,
    palette: str,
    mode: str,
    toc: bool = True,
    timeout_ms: int = 180_000,
    extra_args: Sequence[str] = (),
    command_timeout: int = 120,
) -> None:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "mardas_folio.cli",
        str(source),
        "-o",
        str(output_pdf),
        "--style",
        style,
        "--palette",
        palette,
        "--mode",
        mode,
        "--timeout-ms",
        str(timeout_ms),
        "--progress",
        "off",
        *extra_args,
    ]
    if toc:
        command.append("--toc")
    try:
        run_command(
            command,
            timeout=command_timeout,
            description=f"folio render for {output_pdf}",
        )
    except RuntimeError as exc:
        if output_pdf.is_file() and output_pdf.stat().st_size > 0:
            raise RuntimeError(
                f"folio did not finish cleanly for {output_pdf}; "
                "a PDF was created but the render process did not exit cleanly.\n"
                f"{exc}"
            ) from exc
        raise
    if not output_pdf.is_file() or output_pdf.stat().st_size == 0:
        raise RuntimeError(f"expected non-empty PDF output at {output_pdf}")


def write_html_gallery(path: Path, *, title: str, items: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cards = []
    for item in items:
        label = html.escape(item.get("label", ""))
        image = html.escape(item.get("image", ""))
        meta = html.escape(item.get("meta", ""))
        cards.append(
            "<figure>"
            f'<img src="{image}" alt="{label}" loading="lazy">'
            f"<figcaption><strong>{label}</strong><br><span>{meta}</span></figcaption>"
            "</figure>"
        )
    content = "\n".join(cards)
    path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
body {{ margin: 24px; font-family: system-ui, sans-serif; background: #f8fafc; color: #0f172a; }}
main {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 16px; }}
figure {{ margin: 0; padding: 12px; border: 1px solid #cbd5e1; border-radius: 12px; background: #fff; }}
img {{ display: block; width: 100%; height: auto; border: 1px solid #e2e8f0; background: #fff; }}
figcaption {{ margin-top: 8px; font-size: 12px; line-height: 1.35; }}
span {{ color: #475569; }}
</style>
</head>
<body>
<h1>{html.escape(title)}</h1>
<main>
{content}
</main>
</body>
</html>
""",
        encoding="utf-8",
    )


def relative_to(path: Path, base: Path) -> str:
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()

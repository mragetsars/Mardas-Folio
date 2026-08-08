#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "src" / "mardas_md2pdf" / "assets" / "mardas-md2pdf-app-icon.svg"
DEFAULT_OUTPUT = ROOT / "apps" / "desktop" / "src-tauri" / "icons"


def generate(source: Path = DEFAULT_SOURCE, output: Path = DEFAULT_OUTPUT) -> Path:
    try:
        import cairosvg
        from PIL import Image
    except ImportError as exc:
        raise SystemExit("CairoSVG and Pillow are required to generate desktop icons") from exc
    source = source.expanduser().resolve(strict=True)
    output = output.expanduser().resolve(strict=False)
    output.mkdir(parents=True, exist_ok=True)
    images: dict[int, Image.Image] = {}
    for size in (32, 128, 256, 512, 1024):
        raw = cairosvg.svg2png(url=str(source), output_width=size, output_height=size)
        image = Image.open(io.BytesIO(raw)).convert("RGBA")
        images[size] = image
    images[32].save(output / "32x32.png", optimize=True)
    images[128].save(output / "128x128.png", optimize=True)
    images[256].save(output / "128x128@2x.png", optimize=True)
    images[512].save(output / "icon.png", optimize=True)
    images[256].save(
        output / "icon.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    images[1024].save(
        output / "icon.icns",
        sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)],
    )
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate native desktop icons")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    print(f"Desktop icons generated: {generate(args.source, args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

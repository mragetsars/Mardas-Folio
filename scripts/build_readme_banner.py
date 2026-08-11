#!/usr/bin/env python3
"""Render the repository landing banner from its SVG source.

Chromium renders it, rather than a standalone SVG rasterizer, because the
banner shows a line of Persian. CairoSVG shapes Arabic glyphs but does not
reorder them, so it lays the word out left to right and prints it backwards —
the one mistake this project cannot make on its own landing artwork. Chromium
is also the renderer the publishing engine uses, so the banner is produced by
the pipeline it advertises.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "assets" / "readme" / "mardas-folio.svg"
DEFAULT_OUTPUT = ROOT / "assets" / "readme" / "mardas-folio.png"
WIDTH = 1916
HEIGHT = 821


def build_banner(source: Path = DEFAULT_SOURCE, output: Path = DEFAULT_OUTPUT) -> Path:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise SystemExit("Playwright is required to render the banner") from exc

    source = source.expanduser().resolve(strict=True)
    output = output.expanduser().resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    svg = source.read_text(encoding="utf-8")
    html = f'<html><body style="margin:0;padding:0;background:#0d0d0d">{svg}</body></html>'

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(
                viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1
            )
            page.set_content(html)
            # Let the webfonts settle before the frame is captured.
            page.wait_for_timeout(400)
            page.screenshot(
                path=str(output),
                clip={"x": 0, "y": 0, "width": WIDTH, "height": HEIGHT},
            )
        finally:
            browser.close()
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    written = build_banner(args.source, args.output)
    print(f"README banner written: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

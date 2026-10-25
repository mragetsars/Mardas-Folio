#!/usr/bin/env python3
"""Render the guide's architecture diagram from its SVG source.

The diagram used to be a committed PNG with no source. It drifted: it still
carried the product's former name long after the rename, drew a logo the
project had retired, and was built in an emerald palette nothing else uses.
None of that was catchable, because the guard that keeps the old name out of
the tree reads text files and a PNG is opaque to it. Keeping the artwork in
SVG puts every word of it back under that guard.

The source now lives in ``assets/guides/`` rather than beside the PNG,
because ``docs/guides/images/`` is documentation media that ships with the
guides and is held to staying lightweight.

Chromium renders it, as it does the README banner, so both pieces of project
artwork come out of the same renderer the publishing engine uses.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "assets" / "guides" / "architecture.svg"
DEFAULT_OUTPUT = ROOT / "docs" / "guides" / "images" / "architecture.png"
WIDTH = 1200
HEIGHT = 600


def build_architecture(source: Path = DEFAULT_SOURCE, output: Path = DEFAULT_OUTPUT) -> Path:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise SystemExit("Playwright is required to render the diagram") from exc

    source = source.expanduser().resolve(strict=True)
    output = output.expanduser().resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    svg = source.read_text(encoding="utf-8")
    html = f'<html><body style="margin:0;padding:0;background:#f3f3f3">{svg}</body></html>'

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(
                viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1
            )
            page.set_content(html)
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
    written = build_architecture(args.source, args.output)
    print(f"Guide architecture diagram written: {written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

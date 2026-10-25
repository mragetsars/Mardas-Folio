#!/usr/bin/env python3
"""Build every logo and native icon from the canonical four-fold F mark.

Edit mardas-folio-mark.svg, then run this script. The app tile, monochrome
variants, transparent PNGs, guide copy and desktop icons share its geometry.
Repository illustrations have their own SVG sources and Chromium builders.
"""
from __future__ import annotations

import copy
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from generate_desktop_icons import generate

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src/mardas_folio/assets"
ORANGE = "#FF9F00"
WHITE = "#FFFFFF"
SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG)


def _svg(mark: ET.Element, *, title: str, tile: bool = False) -> str:
    drawing = ET.Element(f"{{{SVG}}}svg", {
        "width": "512", "height": "512", "viewBox": "0 0 512 512",
        "role": "img", "aria-labelledby": "brand-title",
    })
    ET.SubElement(drawing, f"{{{SVG}}}title", {"id": "brand-title"}).text = title
    if tile:
        # A continuous rounded square; generous corners stay soft at small sizes.
        ET.SubElement(drawing, f"{{{SVG}}}path", {
            "fill": ORANGE,
            "d": "M144 0H368C468 0 512 44 512 144V368C512 468 468 512 368 512"
                 "H144C44 512 0 468 0 368V144C0 44 44 0 144 0Z",
        })
    drawing.append(copy.deepcopy(mark))
    ET.indent(drawing, space="  ")
    return ET.tostring(drawing, encoding="unicode") + "\n"


def build() -> None:
    import cairosvg

    source = ASSETS / "mardas-folio-mark.svg"
    mark = ET.parse(source).getroot().find(f"{{{SVG}}}g")
    if mark is None or mark.get("fill") != ORANGE:
        raise ValueError("Canonical mark must use the shared orange brand seed")
    white = copy.deepcopy(mark)
    white.set("fill", WHITE)
    for filename, title, tile in (
        ("mardas-folio-mark-white.svg", "Mardas Folio", False),
        ("mardas-folio-mark-gui-mask.svg", "Mardas Folio monochrome mark mask", False),
        ("mardas-folio-app-icon.svg", "Mardas Folio", True),
    ):
        (ASSETS / filename).write_text(_svg(white, title=title, tile=tile), encoding="utf-8")
    for name, svg in (("mardas-folio-logo.png", source),
                      ("mardas-folio-logo-white.png", ASSETS / "mardas-folio-mark-white.svg")):
        cairosvg.svg2png(url=str(svg), write_to=str(ASSETS / name),
                        output_width=768, output_height=768)
    shutil.copyfile(ASSETS / "mardas-folio-logo.png", ROOT / "docs/guides/images/logo.png")
    shutil.copyfile(ASSETS / "mardas-folio-app-icon.svg",
                    ROOT / "apps/desktop/frontend/assets/app-icon.svg")
    generate()


if __name__ == "__main__":
    build()
    print("Brand assets generated from the canonical orange mark")

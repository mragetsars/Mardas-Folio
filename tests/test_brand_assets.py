from __future__ import annotations

import re
from pathlib import Path

from mardas_md2pdf import brand_assets
from mardas_md2pdf.renderer import _default_logo_path


def test_product_logo_candidates_prefer_canonical_png_assets():
    assert brand_assets.DEFAULT_LOGO_CANDIDATES[0] == brand_assets.PRODUCT_LOGO
    assert brand_assets.COVER_LABEL_LOGO_CANDIDATES[0] == brand_assets.PRODUCT_LOGO_WHITE
    assert _default_logo_path().name == brand_assets.PRODUCT_LOGO
    assert _default_logo_path(variant="cover-label").name == brand_assets.PRODUCT_LOGO_WHITE


def test_studio_brand_asset_routes_expose_only_current_application_logos():
    routes = brand_assets.GUI_BRAND_ASSET_ROUTES

    assert routes["/assets/mardas-md2pdf-logo.png"] == brand_assets.PRODUCT_LOGO
    assert routes["/assets/mardas-md2pdf-logo-white.png"] == brand_assets.PRODUCT_LOGO_WHITE
    assert routes["/assets/mardas-md2pdf-mark.svg"] == brand_assets.PRODUCT_MARK_SVG
    assert routes["/assets/mardas-md2pdf-mark-gui-mask.svg"] == brand_assets.PRODUCT_GUI_MARK_MASK_SVG
    assert brand_assets.gui_brand_asset_filename("/assets/" + "Mardas" + ".png") is None
    assert brand_assets.asset_content_type(brand_assets.PRODUCT_LOGO) == "image/png"


def test_the_product_is_named_mardas_folio_everywhere_it_is_named() -> None:
    """The product has one name.

    The rename left three kinds of identifier alone on purpose, because other
    systems resolve the project by them: the ``mardas_md2pdf`` import package
    and ``mardas-md2pdf`` distribution, the ``Mardas-MD2PDF-*`` release
    artifacts the update endpoint and attestation address, and the repository
    slug. Everything else names the product, and the product is Mardas Folio.
    """
    root = Path(__file__).resolve().parents[1]
    # Names other systems resolve the project by: the import package, the
    # distribution and its wheel, the release artifacts, the repository slug,
    # and the HTTP server token of the legacy browser GUI.
    allowed = re.compile(
        r"Mardas-MD2PDF|mardas-md2pdf|mardas_md2pdf|Mardas_MD2PDF|MardasMD2PDFGUI"
    )
    skip_dirs = {
        ".git", ".venv", "node_modules", "target", "build", "dist", "patches",
        "__pycache__", ".pytest_cache", ".ruff_cache", "artifacts",
        # Staged build output: a copy of the engine, renamed at its source.
        "resources",
    }
    skip_files = {
        # A record of what was released under the old name.
        root / "docs" / "CHANGELOG.md",
        # This file names the old name in order to forbid it.
        Path(__file__).resolve(),
    }

    offenders: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path in skip_files:
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.suffix.lower() not in {
            ".py", ".mjs", ".js", ".html", ".css", ".md", ".toml", ".rs", ".json", ".yml",
        }:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for match in re.finditer(r"Mardas[ _-]?MD2PDF|Mardas Studio", text):
            window = text[max(0, match.start() - 20) : match.end() + 20]
            if allowed.search(window):
                continue
            line = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(root)}:{line}: {match.group(0)}")

    assert offenders == [], "the product is still called by its old name here:\n" + "\n".join(
        offenders[:40]
    )

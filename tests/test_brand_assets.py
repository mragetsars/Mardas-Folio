from __future__ import annotations

import re
from pathlib import Path

from mardas_folio import brand_assets
from mardas_folio.renderer import _default_logo_path


def test_product_logo_candidates_prefer_canonical_png_assets():
    assert brand_assets.DEFAULT_LOGO_CANDIDATES[0] == brand_assets.PRODUCT_LOGO
    assert brand_assets.COVER_LABEL_LOGO_CANDIDATES[0] == brand_assets.PRODUCT_LOGO_WHITE
    assert _default_logo_path().name == brand_assets.PRODUCT_LOGO
    assert _default_logo_path(variant="cover-label").name == brand_assets.PRODUCT_LOGO_WHITE


def test_studio_brand_asset_routes_expose_only_current_application_logos():
    routes = brand_assets.GUI_BRAND_ASSET_ROUTES

    assert routes["/assets/mardas-folio-logo.png"] == brand_assets.PRODUCT_LOGO
    assert routes["/assets/mardas-folio-logo-white.png"] == brand_assets.PRODUCT_LOGO_WHITE
    assert routes["/assets/mardas-folio-mark.svg"] == brand_assets.PRODUCT_MARK_SVG
    assert routes["/assets/mardas-folio-mark-gui-mask.svg"] == brand_assets.PRODUCT_GUI_MARK_MASK_SVG
    assert brand_assets.gui_brand_asset_filename("/assets/" + "Mardas" + ".png") is None
    assert brand_assets.asset_content_type(brand_assets.PRODUCT_LOGO) == "image/png"


def test_the_product_is_named_mardas_folio_everywhere_it_is_named() -> None:
    """The product has one name, and so does every identifier naming it.

    The three kinds of identifier that once kept the old name — the
    ``mardas_folio`` import package and ``mardas-folio`` distribution with its
    ``folio*`` commands, the ``Mardas-Folio-*`` release artifacts the update
    endpoint and attestation address, and the
    ``io.github.mragetsars.mardas-folio`` bundle identifier — were all moved
    onto it before the first release, while no published artifact and no
    installed client addressed the old ones. Nothing is exempt any more, so
    this guard carries no allowlist: any spelling of the old name is a defect.
    """
    root = Path(__file__).resolve().parents[1]
    # Every spelling the project ever used: the product name, the import
    # package, the distribution and its wheel, the commands, and the browser
    # GUI's own former name.
    forbidden = re.compile(r"Mardas[ _-]?MD2PDF|mrs-md2pdf|Mardas Studio", re.IGNORECASE)
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
        for match in forbidden.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.relative_to(root)}:{line}: {match.group(0)}")

    assert offenders == [], "the product is still called by its old name here:\n" + "\n".join(
        offenders[:40]
    )

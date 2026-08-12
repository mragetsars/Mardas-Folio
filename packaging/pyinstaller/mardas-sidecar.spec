# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

project_root = Path(os.environ["MARDAS_PROJECT_ROOT"]).resolve()
entrypoint = project_root / "packaging" / "pyinstaller" / "entrypoint.py"

sys.path.insert(0, str(project_root / "scripts"))
from chromium_payload import chromium_datas, payload_summary  # noqa: E402

datas = collect_data_files("mardas_folio")
datas += copy_metadata("mardas-folio")
playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all("playwright")
datas += playwright_datas
binaries = list(playwright_binaries)
hiddenimports = list(playwright_hiddenimports)

chromium_source = os.environ.get("MARDAS_CHROMIUM_SOURCE")
if chromium_source:
    browser_root = Path(chromium_source).resolve()
    if not browser_root.is_dir():
        raise SystemExit(f"MARDAS_CHROMIUM_SOURCE is not a directory: {browser_root}")
    # Copy the payload file by file rather than wholesale: the browser ships a
    # translated UI this engine never displays and GPU backends it launches
    # with --disable-gpu, together about a quarter of the download.
    summary = payload_summary(browser_root)
    saved = summary["total_bytes"] - summary["kept_bytes"]
    print(
        f"Chromium payload: {summary['total_bytes'] / 1e6:.1f} MB"
        f" -> {summary['kept_bytes'] / 1e6:.1f} MB"
        f" (dropped {summary['total_files'] - summary['kept_files']} files,"
        f" {saved / 1e6:.1f} MB)"
    )
    datas.extend(chromium_datas(browser_root))

license_path = project_root / "LICENSE"
if license_path.is_file():
    datas.append((str(license_path), "."))

a = Analysis(
    [str(entrypoint)],
    pathex=[str(project_root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Pillow is not a dependency of this engine and nothing here imports it.
    # It arrives because pypdf offers optional image extraction, an API the
    # engine never calls: it writes PDFs and reads them back only for outlines
    # and links. The three modules that reach for Pillow all guard the import,
    # and the one that raises is only loaded by `page.images`. Left in, Pillow
    # and its bundled image libraries cost roughly 18 MB of every download.
    #
    # The rest never had a caller; they are listed so a transitive import
    # cannot quietly pull a GUI toolkit or the standard library's test corpus
    # into a published installer.
    excludes=[
        "PIL",
        "tkinter",
        "test",
        "unittest",
        "pydoc_data",
        "lib2to3",
        "idlelib",
        "pytest",
        "_pytest",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="mardas-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="mardas-sidecar",
)

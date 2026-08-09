# -*- mode: python ; coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

project_root = Path(os.environ["MARDAS_PROJECT_ROOT"]).resolve()
entrypoint = project_root / "packaging" / "pyinstaller" / "entrypoint.py"

datas = collect_data_files("mardas_md2pdf")
datas += copy_metadata("mardas-md2pdf")
playwright_datas, playwright_binaries, playwright_hiddenimports = collect_all("playwright")
datas += playwright_datas
binaries = list(playwright_binaries)
hiddenimports = list(playwright_hiddenimports)

chromium_source = os.environ.get("MARDAS_CHROMIUM_SOURCE")
if chromium_source:
    browser_root = Path(chromium_source).resolve()
    if not browser_root.is_dir():
        raise SystemExit(f"MARDAS_CHROMIUM_SOURCE is not a directory: {browser_root}")
    datas.append((str(browser_root), "runtime/chromium"))

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
    excludes=[],
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

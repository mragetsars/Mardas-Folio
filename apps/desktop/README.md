# Mardas Studio Desktop

This directory contains the native desktop product introduced in Mardas MD2PDF 1.24.

```text
frontend/       dependency-free Start Center and Quick Export UI
src-tauri/      native Tauri shell and sidecar process manager
tests/          Node.js frontend contract tests
dist/           generated frontend output; never commit
```

## Local contract checks

```bash
python scripts/build_desktop_frontend.py
python scripts/verify_desktop_frontend.py apps/desktop/dist
node --test apps/desktop/tests/*.test.mjs
python -m pytest -q tests/test_desktop_app.py
```

## Windows installer build

First build the frozen sidecar runtime with bundled Chromium. Then install Rust and Tauri CLI and run:

```powershell
cargo install tauri-cli --version 2.11.4 --locked
python scripts/build_desktop_app.py `
  --runtime build/standalone-runtime/Mardas-MD2PDF-X.Y.Z-runtime-windows-x86_64 `
  --clean
```

Do not commit `dist/`, `src-tauri/target/`, or staged files below `src-tauri/resources/sidecar/`.

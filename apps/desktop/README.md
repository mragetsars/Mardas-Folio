# Mardas Studio Desktop

This directory contains the native desktop product extended in Mardas MD2PDF 1.25.

```text
frontend/       dependency-free Start Center, Quick Export, and authoring workspace
src-tauri/      native Tauri shell and sidecar process manager
tests/          Node.js frontend contract tests
dist/           generated frontend output; never commit
```

## Authoring workspace

The 1.25 preview adds a conflict-safe document lifecycle on top of the sidecar API:

- multiple Markdown tabs and saved-session restore;
- bounded local recovery snapshots for dirty buffers;
- atomic save with revision-based external-change detection;
- outline, top-level front-matter form, assets, citations, and diagnostics panels;
- literal find/replace and Markdown formatting commands;
- validation and sanitized preview of unsaved text without overwriting the source file.

The current editor deliberately remains dependency-free. It is a hardened textarea-based foundation, not the final CodeMirror 6 integration. PDF export is authoritative for MathJax, Mermaid, pagination, and print fidelity.

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
